import base64
import threading
import time

import pytest

from localocr.ollama import Cancelled, OCRServerError, OllamaClient, Settings, local_address


def test_payload_and_proxy(server, monkeypatch):
    url, state = server
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    client = OllamaClient(Settings(url=url))
    assert "Подключено" in client.doctor()
    assert "<table>" in client.recognize(b"image")
    path, payload = state["requests"][-1]
    assert path == "/api/generate"
    assert payload["prompt"] == "Table Recognition:" and payload["stream"] is False
    assert base64.b64decode(payload["images"][0]) == b"image"
    assert payload["options"]["temperature"] == 0


@pytest.mark.parametrize(
    "body", [b"not json", {"models": []}, {"models": {}}, {"error": "failure"}, []]
)
def test_doctor_errors(server, body):
    url, state = server
    state["body"] = body
    with pytest.raises(OCRServerError):
        OllamaClient(Settings(url=url)).doctor()


@pytest.mark.parametrize(
    "body",
    [
        {"response": "", "done": True},
        {"response": "x", "done": False},
        {"response": "<table></table>", "done": True, "done_reason": "length"},
        {"response": 42, "done": True},
    ],
)
def test_response_errors(server, body):
    url, state = server
    state["body"] = body
    with pytest.raises(OCRServerError):
        OllamaClient(Settings(url=url)).recognize(b"x")


@pytest.mark.parametrize("status", [302, 404, 500])
def test_http_errors(server, status):
    url, state = server
    state["status"] = status
    with pytest.raises(OCRServerError):
        OllamaClient(Settings(url=url)).doctor()
    assert len(state["requests"]) == (2 if status == 500 else 1)


def test_timeout_and_cancel(server):
    url, state = server
    state["delay"] = 2
    with pytest.raises(OCRServerError, match="время"):
        OllamaClient(Settings(url=url, timeout=1)).doctor()
    event = threading.Event()
    timer = threading.Timer(0.15, event.set)
    timer.start()
    start = time.monotonic()
    with pytest.raises(Cancelled):
        OllamaClient(Settings(url=url), event).doctor()
    assert time.monotonic() - start < 1
    timer.join()


def test_unavailable():
    with pytest.raises(OCRServerError):
        OllamaClient(Settings(url="http://127.0.0.1:1", retries=0)).doctor()


@pytest.mark.parametrize(
    "url", ["http://8.8.8.8:11434", "http://169.254.169.254", "https://100.64.0.1"]
)
def test_public_denied(url):
    with pytest.raises(ValueError):
        OllamaClient(Settings(url=url)).doctor()


@pytest.mark.parametrize(
    "url",
    [
        "ftp://localhost",
        "http://user:pass@localhost",
        "http://localhost/path",
        "http://localhost?x=1",
        "http://localhost:wrong",
    ],
)
def test_bad_url(url):
    with pytest.raises(ValueError):
        OllamaClient(Settings(url=url))


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "::1", "192.168.1.100", "10.0.0.2", "172.16.1.1", "fd00::1"]
)
def test_local(address):
    assert local_address(address)
