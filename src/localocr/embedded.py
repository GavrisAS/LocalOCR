"""Owned, offline llama-server lifecycle. Never download or discover a remote model."""

import os
import secrets
import socket
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread

from localocr.devices import (
    candidates,
    failure_category,
    native_gpu_failure,
    offload_evidence,
    parse_devices,
)
from localocr.network import emit
from localocr.ollama import OCRServerError
from localocr.providers import OpenWebUIChatProvider, OpenWebUISettings, chat_payload, chat_text

_ENGINE_LOCK = Lock()


def portable_root() -> Path:
    if getattr(sys, "frozen", False):
        directory = Path(sys.executable).resolve().parent
        return directory.parent if directory.name == "LocalOCR-CLI" else directory
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class EmbeddedSettings:
    precision: str = "f16"
    device_mode: str = "auto"
    engine: Path | None = None
    model_path: Path | None = None
    mmproj_path: Path | None = None
    timeout: float = 300
    startup_timeout: float = 300
    num_predict: int = 16000
    ctx_size: int = 32768

    def paths(self) -> tuple[Path, Path, Path]:
        root = portable_root() / "embedded"
        name = "llama-server.exe" if os.name == "nt" else "llama-server"
        return (
            (self.engine or root / "engine" / name).resolve(),
            (self.model_path or root / "models" / self.precision / "model.gguf").resolve(),
            (self.mmproj_path or root / "models" / self.precision / "mmproj.gguf").resolve(),
        )

    def validate(self):
        if self.device_mode not in {"auto", "gpu", "cpu"}:
            raise ValueError("Вычисления: auto, gpu или cpu")
        if self.precision not in {"f16", "q8_0"}:
            raise ValueError("Выберите f16 или q8_0")
        if not 1 <= self.timeout <= 7200 or not 1 <= self.startup_timeout <= 7200:
            raise ValueError("Недопустимый timeout Embedded")
        if not 256 <= self.num_predict <= 32768 or not 2048 <= self.ctx_size <= 131072:
            raise ValueError("Недопустимые параметры Embedded")
        for path in self.paths()[1:]:
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f"Компонент Embedded не установлен: {path}")


class EmbeddedOCRProvider(OpenWebUIChatProvider):
    server_name = "Embedded llama-server"

    def __init__(self, settings: EmbeddedSettings, cancel: Event | None = None):
        settings.validate()
        self.embedded = settings
        self.process: subprocess.Popen | None = None
        self.owns_lock = False
        self.ready = False
        self.runtime_status = ""
        self.inference_seconds = []
        self.diagnostics = deque(maxlen=2048)
        self.runtime_errors = deque(maxlen=32)
        self.reader = None
        self.lock_file = None
        self.cancel = cancel or Event()
        self.settings = OpenWebUISettings(
            model="localocr-" + secrets.token_hex(16),
            api_token="localocr-" + secrets.token_urlsafe(32),
            timeout=settings.timeout,
            num_predict=settings.num_predict,
            retries=1,
            api="chat",
        )

    def doctor(self):
        if self.cancel.is_set():
            self.close()
        self.check_cancel()
        if self.ready:
            self.check_cancel()
            if self.process is None or self.process.poll() is not None:
                self.close()
                raise OCRServerError(self.runtime_failure("Локальный engine завершился"))
            return self.runtime_status
        failures = []
        for candidate in candidates(self.embedded):
            self.check_cancel()
            try:
                if not candidate.engine.is_file():
                    raise ValueError(
                        f"{candidate.backend}: runtime не установлен: {candidate.engine}"
                    )
                device, name = "none", "CPU"
                if candidate.backend != "cpu":
                    device, name = self.probe(candidate)
                self.active_candidate = candidate
                self.active_device = device
                self.device_name = name
                self.diagnostics.clear()
                self.runtime_errors.clear()
                started = time.monotonic()
                self._start()
                if candidate.backend != "cpu":
                    self.offload = offload_evidence(
                        "\n".join(list(self.diagnostics)), candidate.backend
                    )
                else:
                    self.offload = []
                self.load_seconds = time.monotonic() - started
                reason = "; ".join(failures)
                self.runtime_status = (
                    f"Embedded {self.embedded.precision.upper()} · {candidate.backend.upper()} · {name} · режим={self.embedded.device_mode.upper()} · "
                    + ("GPU offload: подтверждён (LLM + vision)" if self.offload else "выбран CPU")
                    + (
                        f" · {self.embedded.device_mode.upper()} fallback: {reason}"
                        if reason
                        else ""
                    )
                    + f" · model load={self.load_seconds:.3f}s"
                )
                callback = getattr(self, "on_runtime_status", None)
                if callback:
                    callback(self.runtime_status)
                emit(self, self.runtime_status)
                return self.runtime_status
            except (OSError, ValueError, OCRServerError) as error:
                self.close()
                detail = f"{candidate.backend.upper()} / {failure_category(str(error))}: {type(error).__name__}: {error}"
                failures.append(detail)
                emit(self, detail)
        raise OCRServerError("Embedded: " + "; ".join(failures))

    def probe(self, candidate):
        # Bounded, cancellable discovery; no models, network or downloads.
        self.process = subprocess.Popen(
            [str(candidate.engine), "--offline", "--list-devices"],
            cwd=candidate.engine.parent,
            env={
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("LLAMA_", "HF_", "MTMD_", "GGML_"))
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.diagnostics.clear()
        self.reader = Thread(target=self.drain, args=(self.process.stdout,), daemon=True)
        self.reader.start()
        deadline = time.monotonic() + 15
        try:
            while self.process.poll() is None:
                self.check_cancel()
                if time.monotonic() >= deadline:
                    raise OCRServerError(
                        "GPU_PROBE_TIMEOUT\n" + "\n".join(list(self.diagnostics))[-8192:]
                    )
                self.cancel.wait(0.05)
            self.reader.join(timeout=2)
            output = "\n".join(list(self.diagnostics))
            if self.process.returncode:
                raise OCRServerError(
                    f"GPU probe failed: exit={self.process.returncode} {output[:4096]}"
                )
            try:
                return parse_devices(output, candidate.backend)
            except ValueError as error:
                reason = str(error)
                if (
                    "available devices:" not in output.lower()
                    and failure_category(output) == "ENGINE_START_FAILED"
                ):
                    reason = "GPU_PROBE_INVALID: неподдерживаемый вывод --list-devices"
                raise OCRServerError(
                    f"{reason}\n--list-devices output:\n{output[-8192:] or '<empty>'}"
                ) from error
        finally:
            self.close()

    def drain(self, stream):
        try:
            for line in iter(lambda: stream.readline(2048), b""):
                text = line.decode("utf-8", errors="replace").rstrip()
                # Runtime output after readiness can contain OCR/prompt content.
                # Keep only startup diagnostics, never completion text.
                if not self.ready:
                    self.diagnostics.append(text)
                elif native_gpu_failure(text):
                    self.runtime_errors.append(text)
        finally:
            stream.close()

    def _start(self):
        if self.cancel.is_set():
            self.close()
        self.check_cancel()
        if self.ready:
            if self.process is None or self.process.poll() is not None:
                raise OCRServerError("Локальный engine завершился")
            return self.runtime_status
        if not _ENGINE_LOCK.acquire(blocking=False):
            raise OCRServerError("Другой Embedded engine уже выполняет задание")
        self.owns_lock = True
        try:
            from localocr.config import config_dir

            directory = config_dir()
            directory.mkdir(parents=True, exist_ok=True)
            self.lock_file = (directory / "embedded.lock").open("a+b")
            try:
                if os.name == "nt":
                    import msvcrt

                    self.lock_file.seek(0)
                    if self.lock_file.read(1) == b"":
                        self.lock_file.write(b"0")
                        self.lock_file.flush()
                    self.lock_file.seek(0)
                    msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise OCRServerError("Другой Embedded engine уже выполняет задание") from error
            _, model, mmproj = self.embedded.paths()
            engine = self.active_candidate.engine
            gpu = self.active_candidate.backend != "cpu"
            # Avoid the default OS ephemeral client-port ranges: readiness probes
            # must not claim the server port before the child binds it.
            for _ in range(32):
                port = 10000 + secrets.randbelow(20000)
                with socket.socket() as reservation:
                    try:
                        reservation.bind(("127.0.0.1", port))
                    except OSError:
                        continue
                break
            else:
                raise OCRServerError("Нет свободного loopback порта для Embedded")
            from dataclasses import replace

            self.settings = replace(self.settings, url=f"http://127.0.0.1:{port}")
            # Discard model output/logs; sensitive diagnostics are opt-in in the service.
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("LLAMA_", "HF_", "MTMD_", "GGML_"))
            }
            self.process = subprocess.Popen(
                [
                    str(engine),
                    "-m",
                    str(model),
                    "--mmproj",
                    str(mmproj),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--ctx-size",
                    str(self.embedded.ctx_size),
                    "--parallel",
                    "1",
                    "--flash-attn",
                    "off",
                    "--device",
                    self.active_device,
                    "--n-gpu-layers",
                    "all" if gpu else "0",
                    "--mmproj-offload" if gpu else "--no-mmproj-offload",
                    "--verbosity",
                    "4",
                    "--offline",
                    "--alias",
                    self.settings.model,
                    "--api-key",
                    self.settings.api_token,
                ],
                cwd=engine.parent,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.reader = Thread(target=self.drain, args=(self.process.stdout,), daemon=True)
            self.reader.start()
            deadline = time.monotonic() + self.embedded.startup_timeout
            while time.monotonic() < deadline:
                self.check_cancel()
                if self.process.poll() is not None:
                    raise OCRServerError(
                        "Embedded engine не загрузил модель: "
                        + "\n".join(list(self.diagnostics))[-8192:]
                    )
                original = self.settings
                self.settings = replace(original, timeout=1, retries=0)
                try:
                    # Health is public: authenticated models + unguessable alias prove ownership.
                    self.suppress_network_events = True
                    data = self.request("GET", "/v1/models")
                    if any(
                        item.get("id") == original.model
                        for item in data.get("data", [])
                        if isinstance(item, dict)
                    ):
                        self.ready = True
                        return self.runtime_status
                except OCRServerError:
                    pass
                finally:
                    self.suppress_network_events = False
                    self.settings = original
                self.cancel.wait(0.05)
            raise OCRServerError(
                "ENGINE_STARTUP_TIMEOUT: Истекло время загрузки Embedded модели\n"
                + "\n".join(list(self.diagnostics))[-8192:]
            )
        except BaseException:
            self.close()
            raise

    def runtime_failure(self, default: str) -> str:
        lines = "\n".join(list(self.runtime_errors))
        category = failure_category(lines)
        if category == "ENGINE_START_FAILED":
            category = "GPU_RUNTIME_ERROR"
        return f"{category} · {lines}" if lines else default

    def recognize(self, image: bytes, *, single_table: bool = False) -> str:
        self.doctor()
        started = time.monotonic()
        try:
            return chat_text(
                self.request(
                    "POST",
                    "/v1/chat/completions",
                    chat_payload(self.settings, image, single_table=single_table),
                ),
                single_table=single_table,
            )
        except BaseException as error:
            callback = getattr(self, "on_runtime_status", None)
            if callback:
                callback("Embedded: ошибка распознавания; состояние не подтверждено")
            self.close()
            if isinstance(error, OCRServerError) and self.runtime_errors:
                raise OCRServerError(self.runtime_failure(str(error))) from error
            raise
        finally:
            seconds = time.monotonic() - started
            self.inference_seconds.append(seconds)
            emit(self, f"Embedded recognize latency={seconds:.3f}s")

    def close(self):
        try:
            if self.process is not None:
                process, self.process = self.process, None
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
        finally:
            if self.reader is not None:
                self.reader.join(timeout=2)
                self.reader = None
            self.ready = False
            if self.lock_file is not None:
                self.lock_file.close()
                self.lock_file = None
            if self.owns_lock:
                self.owns_lock = False
                _ENGINE_LOCK.release()
