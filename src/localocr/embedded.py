"""Owned, offline llama-server lifecycle. Never download or discover a remote model."""

import os
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock

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
        if self.precision not in {"f16", "q8_0"}:
            raise ValueError("Выберите f16 или q8_0")
        if not 1 <= self.timeout <= 7200 or not 1 <= self.startup_timeout <= 7200:
            raise ValueError("Недопустимый timeout Embedded")
        if not 256 <= self.num_predict <= 32768 or not 2048 <= self.ctx_size <= 131072:
            raise ValueError("Недопустимые параметры Embedded")
        for path in self.paths():
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
            if self.process is None or self.process.poll() is not None:
                raise OCRServerError("Локальный engine завершился")
            return f"Embedded {self.embedded.precision.upper()} · CPU · готов"
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
            engine, model, mmproj = self.embedded.paths()
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
                if not key.startswith(("LLAMA_", "HF_", "MTMD_"))
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
                    "--n-gpu-layers",
                    "0",
                    "--no-mmproj-offload",
                    "--offline",
                    "--alias",
                    self.settings.model,
                    "--api-key",
                    self.settings.api_token,
                ],
                cwd=engine.parent,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            deadline = time.monotonic() + self.embedded.startup_timeout
            while time.monotonic() < deadline:
                self.check_cancel()
                if self.process.poll() is not None:
                    raise OCRServerError("Embedded engine не загрузил модель; проверьте комплект")
                original = self.settings
                self.settings = replace(original, timeout=1, retries=0)
                try:
                    # Health is public: authenticated models + unguessable alias prove ownership.
                    data = self.request("GET", "/v1/models")
                    if any(
                        item.get("id") == original.model
                        for item in data.get("data", [])
                        if isinstance(item, dict)
                    ):
                        self.ready = True
                        return f"Embedded {self.embedded.precision.upper()} · CPU · готов"
                except OCRServerError:
                    pass
                finally:
                    self.settings = original
                self.cancel.wait(0.05)
            raise OCRServerError("Истекло время загрузки Embedded модели")
        except BaseException:
            self.close()
            raise

    def recognize(self, image: bytes, *, single_table: bool = False) -> str:
        self.doctor()
        try:
            return chat_text(
                self.request(
                    "POST",
                    "/v1/chat/completions",
                    chat_payload(self.settings, image, single_table=single_table),
                ),
                single_table=single_table,
            )
        except BaseException:
            self.close()
            raise

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
            self.ready = False
            if self.lock_file is not None:
                self.lock_file.close()
                self.lock_file = None
            if self.owns_lock:
                self.owns_lock = False
                _ENGINE_LOCK.release()
