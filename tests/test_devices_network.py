import socket
import ssl
from dataclasses import replace

import httpx
import pytest
from test_embedded import fake_engine  # noqa: F401, F811

from localocr.config import AppConfig
from localocr.devices import candidates, offload_evidence, parse_devices
from localocr.embedded import EmbeddedOCRProvider, EmbeddedSettings
from localocr.network import category, exception_detail
from localocr.ollama import OCRServerError
from localocr.providers import OpenWebUISettings, create_provider


def test_modes_config_and_legacy(tmp_path):
    for mode in ("auto", "gpu", "cpu"):
        settings = AppConfig(provider="embedded", embedded_device=mode).settings()
        assert settings.device_mode == mode
        settings = replace(settings, engine=tmp_path / "engine" / "llama-server")
        assert [c.backend for c in candidates(settings)] == (
            ["cpu"] if mode == "cpu" else ["cuda", "vulkan"] + (["cpu"] if mode == "auto" else [])
        )
    assert AppConfig(provider="embedded").settings().device_mode == "auto"
    with pytest.raises(ValueError, match="auto"):
        EmbeddedSettings(device_mode="cuda").validate()


@pytest.mark.parametrize("backend", ["cuda", "vulkan"])
def test_gpu_proof(backend):
    prefix = "CUDA" if backend == "cuda" else "Vulkan"
    assert parse_devices(f"  {prefix}0: NVIDIA RTX A4000 (16000 MiB)", backend)[0] == prefix + "0"
    for text in ("garbage", f"{prefix}0: llvmpipe", f"{prefix}0: software renderer"):
        with pytest.raises(ValueError):
            parse_devices(text, backend)
    proof = f"offloaded 25/25 layers to GPU\nclip_model_load: {prefix}0 buffer size = 800 MiB\nreserve_compute_meta: {prefix}0 compute buffer size = 100 MiB"
    assert offload_evidence(proof, backend)
    for text in ("", proof.replace("25/25", "24/25"), proof.splitlines()[0]):
        with pytest.raises(ValueError, match="UNCONFIRMED"):
            offload_evidence(text, backend)


def test_selection_fallback_and_strict(fake_engine, monkeypatch):  # noqa: F811
    settings, _, _ = fake_engine
    # Candidate availability and probing are fixtures; actual owned CPU process still runs.
    monkeypatch.setattr(
        EmbeddedOCRProvider, "probe", lambda *args: (_ for _ in ()).throw(ValueError("DLL missing"))
    )
    with EmbeddedOCRProvider(replace(settings, device_mode="auto")) as client:
        assert "fallback" in client.doctor()
        assert "DLL missing" in client.runtime_status
    with EmbeddedOCRProvider(replace(settings, device_mode="gpu")) as client:
        with pytest.raises(OCRServerError, match="DLL missing"):
            client.doctor()
        assert client.process is None and not client.owns_lock


@pytest.mark.parametrize(
    "api,endpoint", [("proxy", "/prefix/ollama/api/tags"), ("chat", "/prefix/api/models")]
)
@pytest.mark.parametrize("status", [200, 401, 403, 404, 405, 502, 301, 302, 307, 308])
def test_http_trace_actual_request(api, endpoint, status, monkeypatch):
    lines, requests = [], []

    async def handle(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={
                "data": [{"id": "exact-model"}],
                "models": [{"name": "exact-model"}],
                "detail": "upstream detail",
            },
            headers={"Location": "/other"},
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    client = create_provider(
        OpenWebUISettings(
            url="https://host.example:8443/prefix",
            api=api,
            model="exact-model",
            api_token="secret-token",
        ),
        on_network_event=lines.append,
    )
    if status == 200:
        assert "Подключено" in client.doctor()
    else:
        with pytest.raises(OCRServerError):
            client.doctor()
    text = "\n".join(lines)
    assert f"GET https://host.example:8443{endpoint}" in text
    assert f"HTTP ← {status}" in text
    assert "secret-token" not in text
    assert "trust_env=False" in text
    assert len(requests) == (2 if status == 502 else 1)
    if status >= 300:
        assert "upstream detail" in text
    if 300 <= status < 400:
        assert "Location=/other" in text


@pytest.mark.parametrize(
    "cause,label",
    [
        (
            ssl.SSLCertVerificationError(1, "certificate verify failed"),
            "TLS_CERTIFICATE_VERIFY_FAILED",
        ),
        (socket.gaierror(-2, "Name or service not known"), "DNS_ERROR"),
        (ConnectionRefusedError(111, "Connection refused"), "CONNECT_REFUSED"),
    ],
)
def test_chains(cause, label):
    error = httpx.ConnectError("failed")
    error.__cause__ = cause
    assert category(error) == label
    assert type(cause).__name__ in exception_detail(error)


@pytest.mark.parametrize(
    "cls,label",
    [
        (httpx.ConnectTimeout, "CONNECT_TIMEOUT"),
        (httpx.ReadTimeout, "READ_TIMEOUT"),
        (httpx.WriteTimeout, "WRITE_TIMEOUT"),
        (httpx.PoolTimeout, "POOL_TIMEOUT"),
        (httpx.ProxyError, "PROXY_ERROR"),
    ],
)
def test_transport_exception_trace(cls, label, monkeypatch):
    lines = []

    async def handle(request):
        raise cls("original technical failure", request=request)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    client = create_provider(OpenWebUISettings(retries=0), on_network_event=lines.append)
    with pytest.raises(OCRServerError, match=label):
        client.doctor()
    assert "original technical failure" in "\n".join(lines)


def test_post_no_image_content(api="chat", monkeypatch=None):
    from localocr.network import payload_summary

    assert "SECRETB64" not in payload_summary({"model": "exact-id", "images": ["SECRETB64"]})


@pytest.mark.parametrize("mode", ["auto", "gpu", "cpu"])
def test_cli_device_override(mode):
    from localocr.cli import selected_settings

    args = ["embedded", None, None, None, None, None, None, None, None, None, False]
    assert selected_settings(*args, device=mode).device_mode == mode
    args[0] = "ollama"
    with pytest.raises(ValueError, match="Embedded"):
        selected_settings(*args, device=mode)


def test_gui_failure_and_batch_preflight_trace(server, tmp_path, monkeypatch):
    import time

    from PIL import Image
    from PySide6.QtWidgets import QApplication

    from localocr.config import save_config
    from localocr.gui.app import Window

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "config"))
    app = QApplication.instance() or QApplication([])
    Image.new("RGB", (20, 20), "white").save(tmp_path / "input.png")
    save_config(
        AppConfig(
            folder=str(tmp_path),
            provider="openwebui",
            openwebui_url=server[0] + "/prefix",
            api_token="test-token",
            embedded_device="gpu",
        )
    )
    server[1]["status"] = 502
    window = Window()
    assert window.device.count() == 3
    assert window.current_config().embedded_device == "gpu"
    for check in (True, False):
        window.launch(check)
        deadline = time.monotonic() + 5
        while window.worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert window.worker is None
        text = window.status.toPlainText()
        assert f"GET {server[0]}/prefix/ollama/api/tags" in text
        assert "HTTP ← 502" in text
        assert "попытка 2/2" in text
    window.close()


@pytest.mark.parametrize("failed,backend", [((), "cuda"), (("cuda",), "vulkan")])
def test_gpu_order_and_proof(fake_engine, monkeypatch, failed, backend):  # noqa: F811
    settings, _, _ = fake_engine
    attempts = []

    def probe(self, candidate):
        attempts.append(candidate.backend)
        if candidate.backend in failed:
            raise ValueError("driver unavailable")
        return candidate.backend.upper() + "0", "physical GPU"

    def start(self):
        self.diagnostics.extend(
            [
                "offloaded 18/18 layers to GPU",
                f"clip_ctx: CLIP using {self.active_candidate.backend}0 backend",
                f"reserve_compute_meta: {self.active_candidate.backend}0 compute buffer size = 100 MiB",
            ]
        )

    monkeypatch.setattr(EmbeddedOCRProvider, "probe", probe)
    monkeypatch.setattr(EmbeddedOCRProvider, "_start", start)
    with EmbeddedOCRProvider(replace(settings, device_mode="gpu")) as client:
        client.doctor()
        assert client.active_candidate.backend == backend
        assert attempts == (["cuda"] if not failed else ["cuda", "vulkan"])
        assert client.offload


def test_cpu_flags(fake_engine):  # noqa: F811
    settings, _, launches = fake_engine
    with EmbeddedOCRProvider(settings) as client:
        client.doctor()
    args = launches[0]
    assert args[args.index("--device") + 1] == "none"
    assert args[args.index("--n-gpu-layers") + 1] == "0"
    assert "--no-mmproj-offload" in args


@pytest.mark.parametrize(
    "api,endpoint", [("proxy", "/ollama/api/generate"), ("chat", "/api/chat/completions")]
)
def test_post_actual_payload_and_bounded_body(api, endpoint, monkeypatch):
    lines = []

    async def handle(request):
        assert str(request.url) == "https://ocr.example:9443/base" + endpoint
        assert b'"model":"model-exact"' in request.content
        return httpx.Response(422, text="detail error " + "!" * 10000)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    client = create_provider(
        OpenWebUISettings(url="https://ocr.example:9443/base", api=api, model="model-exact"),
        on_network_event=lines.append,
    )
    with pytest.raises(OCRServerError):
        client.recognize(b"sensitive-image" * 1000)
    text = "\n".join(lines)
    assert "POST https://ocr.example:9443/base" + endpoint in text
    assert "model=model-exact" in text and "HTTP_422" in text
    assert len(text) < 8000
    assert "c2Vuc2l0aXZl" not in text


def test_old_config_and_cli_saved_override(tmp_path, monkeypatch):
    from localocr.cli import selected_settings
    from localocr.config import config_dir, load_config, save_config

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config_dir().mkdir(parents=True)
    (config_dir() / "config.json").write_text(
        '{"folder":"old","ollama_url":"http://127.0.0.1:11434","provider":"embedded"}'
    )
    assert load_config().embedded_device == "auto"
    save_config(AppConfig(provider="embedded", embedded_device="cpu"))
    args = [None, None, None, None, None, None, None, None, None, None, True]
    assert selected_settings(*args).device_mode == "cpu"
    assert selected_settings(*args, device="gpu").device_mode == "gpu"


def test_unconfirmed_gpu_owned_cleanup(fake_engine, monkeypatch):  # noqa: F811
    settings, _, launches = fake_engine
    monkeypatch.setattr(EmbeddedOCRProvider, "probe", lambda *args: ("CUDA0", "GPU fixture"))
    with EmbeddedOCRProvider(replace(settings, device_mode="gpu")) as client:
        with pytest.raises(OCRServerError, match="UNCONFIRMED"):
            client.doctor()
        assert client.process is None and not client.owns_lock and client.lock_file is None
    assert len(launches) == 2
    with EmbeddedOCRProvider(settings) as client:
        assert "CPU" in client.doctor()


def test_final_error_redacts_token_and_preserves_chain(monkeypatch):
    lines = []

    async def handle(request):
        raise httpx.ConnectError("technical cause echoes secret-value", request=request)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    client = create_provider(
        OpenWebUISettings(api_token="secret-value", retries=0), on_network_event=lines.append
    )
    with pytest.raises(OCRServerError) as caught:
        client.doctor()
    assert "secret-value" not in str(caught.value)
    assert "TOKEN_OMITTED" in str(caught.value)
    assert caught.value.__cause__ is not None
    assert "secret-value" not in "\n".join(lines)


def test_validation_event_category():
    lines = []
    with pytest.raises(ValueError):
        create_provider(OpenWebUISettings(url="invalid-url"), on_network_event=lines.append)
    assert "URL_INVALID" in "\n".join(lines)
    assert "input=invalid-url" in "\n".join(lines)


def test_worker_final_error_redacts_unexpected_exception(monkeypatch):
    from localocr.gui.app import Worker

    class Client:
        def doctor(self):
            raise RuntimeError("unexpected echoes secret-value")

        def close(self):
            pass

    monkeypatch.setattr("localocr.gui.app.create_provider", lambda *a, **kw: Client())
    worker = Worker("", OpenWebUISettings(api_token="secret-value"), check=True)
    errors = []
    worker.error.connect(errors.append)
    worker.run()
    assert errors == ["unexpected echoes TOKEN_OMITTED"]


def test_native_gpu_oom_after_ready_keeps_technical_cause(fake_engine, monkeypatch):  # noqa: F811
    from test_embedded import FAKE

    settings, script, launches = fake_engine
    proof = "print('offloaded 18/18 layers to GPU', flush=True)\nprint('clip_ctx: CLIP using CUDA0 backend', flush=True)\nprint('reserve_compute_meta: CUDA0 compute buffer size = 100 MiB', flush=True)\n"
    body = FAKE.replace("server=HTTPServer", proof + "server=HTTPServer").replace(
        "  self.rfile.read(int(self.headers['Content-Length']))",
        "  print('OCR_PRIVATE_CONTENT_NOT_FOR_LOG', flush=True)\n  print('CUDA error: out of memory', flush=True)\n  raise SystemExit(1)\n  self.rfile.read(int(self.headers['Content-Length']))",
    )
    script.write_text("MODE='ready'\n" + body)
    monkeypatch.setattr(EmbeddedOCRProvider, "probe", lambda *args: ("CUDA0", "GPU fixture"))
    with EmbeddedOCRProvider(replace(settings, device_mode="gpu")) as client:
        assert "подтверждён" in client.doctor()
        with pytest.raises(OCRServerError, match="GPU_OOM"):
            client.recognize(b"image")
        assert client.process is None and not client.owns_lock
        assert "OCR_PRIVATE_CONTENT_NOT_FOR_LOG" not in "\n".join(
            [*client.diagnostics, *client.runtime_errors]
        )
    assert len(launches) == 1


@pytest.mark.parametrize(
    "line,expected",
    [
        ("CUDA error: out of memory", True),
        ("ggml_cuda_compute_forward: CUDA error 700 illegal memory access", True),
        ("ggml_backend_vk: error: device lost", True),
        ("slot: OCR_PRIVATE_CONTENT out of memory", False),
        ("recognized table CUDA error: out of memory", False),
        ("clip_ctx: CLIP using CUDA0 backend", False),
    ],
)
def test_native_gpu_error_filter(line, expected):
    from localocr.devices import native_gpu_failure

    assert native_gpu_failure(line) is expected


def test_request_construction_failure_emits_original_url(monkeypatch):
    lines = []

    def invalid(*args, **kwargs):
        raise httpx.InvalidURL("Invalid non-printable ASCII character in URL")

    monkeypatch.setattr(httpx.AsyncClient, "build_request", invalid)
    client = create_provider(
        OpenWebUISettings(url="https://host.example:8443/prefix"), on_network_event=lines.append
    )
    with pytest.raises(ValueError, match="URL_INVALID"):
        client.doctor()
    text = "\n".join(lines)
    assert "input=https://host.example:8443/prefix" in text
    assert "httpx.InvalidURL" in text and "Request build" in text
    assert "HTTP →" not in text


@pytest.mark.parametrize(
    "backend,output,category_label",
    [
        (
            "cuda",
            "CUDA error: CUDA driver version is insufficient for CUDA runtime version\nAvailable devices:",
            "GPU_DRIVER_INCOMPATIBLE",
        ),
        (
            "cuda",
            "load_backend: failed to load ggml-cuda.dll\nAvailable devices:",
            "GPU_RUNTIME_OR_DRIVER_MISSING",
        ),
        ("cuda", "loaded CPU backend from ggml-cpu.dll\nAvailable devices:", "GPU_NOT_FOUND"),
        ("vulkan", "Available devices:\n Vulkan0: llvmpipe (software)", "GPU_NOT_FOUND"),
        ("cuda", "incompatible list-devices output", "GPU_PROBE_INVALID"),
    ],
)
def test_zero_exit_probe_preserves_driver_and_dll_diagnostics(
    fake_engine,  # noqa: F811
    backend,
    output,
    category_label,  # noqa: F811
):
    from localocr.devices import RuntimeCandidate, failure_category

    settings, script, _ = fake_engine
    script.write_text("import sys\nprint(" + repr(output) + ")\nsys.exit(0)\n")
    client = EmbeddedOCRProvider(settings)
    with pytest.raises((ValueError, OCRServerError)) as caught:
        client.probe(RuntimeCandidate(backend, settings.paths()[0]))
    assert output in str(caught.value)
    assert failure_category(str(caught.value)) == category_label
    assert client.process is None and client.reader is None
