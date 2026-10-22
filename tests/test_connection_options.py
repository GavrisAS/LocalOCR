import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from localocr.config import AppConfig, config_dir, load_config, save_config
from localocr.gui.app import Window
from localocr.ollama import OCRServerError
from localocr.providers import OpenWebUISettings, create_provider
from localocr.service import convert


def test_config_migration_and_gui(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_config(
        AppConfig(api_token="fixture-token", openwebui_url="https://example.invalid/prefix")
    )
    path = config_dir() / "config.json"
    data = json.loads(path.read_text())
    del data["ssl_verify"]
    del data["trust_env"]
    data.update(folder=42, unknown=False)
    path.write_text(json.dumps(data))
    config = load_config()
    assert config.ssl_verify is False and config.trust_env is False
    assert config.folder == "" and config.api_token == "fixture-token"
    data.update(ssl_verify="false", trust_env=True)
    path.write_text(json.dumps(data))
    assert load_config().ssl_verify is False
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.ssl_verify.setChecked(False)
    window.trust_env.setChecked(True)
    window.close()
    restored = Window()
    assert not restored.ssl_verify.isChecked() and restored.trust_env.isChecked()
    assert restored.token.text() == config.api_token
    assert restored.web_url.text() == config.openwebui_url
    assert type(json.loads(path.read_text())["ssl_verify"]) is bool
    restored.close()
    app.processEvents()


@pytest.mark.parametrize("api", ["proxy", "chat"])
@pytest.mark.parametrize(
    "verify,trust", [(True, False), (False, False), (True, True), (False, True)]
)
def test_client_options_doctor_convert(api, verify, trust, tmp_path, monkeypatch, visible_text):
    calls, events, urls = [], [], []
    original = httpx.AsyncClient

    def respond(request):
        urls.append(str(request.url))
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"models": [{"name": "glm-ocr:latest"}], "data": [{"id": "glm-ocr:latest"}]},
            )
        text = "<table><tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr></table>"
        return httpx.Response(
            200,
            json={
                "response": text,
                "done": True,
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            },
        )

    def factory(**kwargs):
        calls.append(kwargs.copy())
        return original(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    settings = OpenWebUISettings(
        url="https://example.invalid/prefix", api=api, ssl_verify=verify, trust_env=trust
    )
    client = create_provider(settings, on_network_event=events.append)
    client.doctor()
    visible_text(Image.new("RGB", (100, 100), "white")).save(tmp_path / "input.png")
    convert(tmp_path, settings, on_network_event=events.append)
    assert len(calls) >= 3
    assert all(
        c["verify"] is verify and c["trust_env"] is trust and c["follow_redirects"] is False
        for c in calls
    )
    endpoints = (
        ["/api/models", "/api/chat/completions"]
        if api == "chat"
        else ["/ollama/api/tags", "/ollama/api/generate"]
    )
    assert all("https://example.invalid/prefix" + endpoint in urls for endpoint in endpoints)
    assert any(f"TLS verify={verify} ; trust_env={trust}" in e for e in events)
    assert any("HTTP → POST" in e for e in events)


@pytest.mark.parametrize("api", ["proxy", "chat"])
def test_real_tls_and_proxy_environment(tmp_path, monkeypatch, api):
    if not shutil.which("openssl"):
        pytest.skip("openssl unavailable for synthetic HTTPS fixture")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b'{"models": [{"name": "glm-ocr:latest"}], "data": [{"id": "glm-ocr:latest"}]}'
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"https://127.0.0.1:{server.server_port}"
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.delenv("no_proxy", raising=False)
    events = []
    try:
        with pytest.raises(OCRServerError, match="TLS_CERTIFICATE_VERIFY_FAILED"):
            create_provider(
                OpenWebUISettings(url=url, api_token="synthetic-token", api=api, retries=0),
                on_network_event=events.append,
            ).doctor()
        assert (
            "Подключено"
            in create_provider(
                OpenWebUISettings(url=url, api_token="synthetic-token", api=api, ssl_verify=False)
            ).doctor()
        )
        with pytest.raises(OCRServerError):
            create_provider(
                OpenWebUISettings(
                    url=url,
                    api_token="synthetic-token",
                    api=api,
                    ssl_verify=False,
                    trust_env=True,
                    retries=0,
                )
            ).doctor()
        monkeypatch.setenv("NO_PROXY", "127.0.0.1")
        assert (
            "Подключено"
            in create_provider(
                OpenWebUISettings(
                    url=url,
                    api_token="synthetic-token",
                    api=api,
                    ssl_verify=False,
                    trust_env=True,
                )
            ).doctor()
        )
    finally:
        server.shutdown()
        server.server_close()


def test_cli_config_and_overrides(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from localocr.cli import app

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_config(AppConfig(provider="openwebui", ssl_verify=False, trust_env=True))
    observed = []

    class Client:
        def doctor(self):
            return "synthetic"

        def close(self):
            pass

    def factory(settings, **kwargs):
        observed.append(settings)
        return Client()

    monkeypatch.setattr("localocr.cli.create_provider", factory)
    runner = CliRunner()
    assert runner.invoke(app, ["doctor", "--use-config"]).exit_code == 0
    assert observed[-1].ssl_verify is False and observed[-1].trust_env is True
    assert (
        runner.invoke(app, ["doctor", "--use-config", "--ssl-verify", "--no-trust-env"]).exit_code
        == 0
    )
    assert observed[-1].ssl_verify is True and observed[-1].trust_env is False
