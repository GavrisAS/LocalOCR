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
    assert client.last_diagnostic["endpoint"].endswith("/api/generate")
    assert client.last_diagnostic["done_reason"] == "stop"
    assert client.last_diagnostic["response_length"] == len(state["text"])
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


def test_token_repeat_limit_is_classified_without_identical_provider_retry(server, caplog):
    url, state = server
    state["status"] = 500
    state["body"] = {
        "error": "prediction aborted, token repeat limit reached",
        "ocr": "PRIVATE_OCR",
    }
    events = []
    client = OllamaClient(Settings(url=url))
    setattr(client, "on_network_event", events.append)
    with (
        caplog.at_level("INFO"),
        pytest.raises(OCRServerError, match="TOKEN_REPEAT_LIMIT") as caught,
    ):
        client.recognize(b"image", single_table=True)
    assert len(state["requests"]) == 1
    assert caught.value.diagnostics["category"] == "TOKEN_REPEAT_LIMIT"
    assert "TOKEN_REPEAT_LIMIT" in "\n".join(events)
    assert "PRIVATE_OCR" not in caplog.text
    assert "PRIVATE_OCR" not in "\n".join(events)


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


def test_single_table_stop_not_fake_repair(server):
    url, state = server
    state["body"] = {"response": "<table><tr><td>x</td></tr>", "done": True, "done_reason": "stop"}
    client = OllamaClient(Settings(url=url))
    assert client.recognize(b"x", single_table=True).endswith("</table>")
    assert state["requests"][-1][1]["options"]["stop"] == ["</table>"]
    state["body"]["done_reason"] = "length"
    with pytest.raises(OCRServerError):
        client.recognize(b"x", single_table=True)
    assert client.last_diagnostic["done_reason"] == "length"
    state["body"]["done_reason"] = "stop"
    from localocr.domain import StructureError
    from localocr.tables import parse_response

    state["body"]["response"] = "<table><tr><td>unfinished"
    with pytest.raises(StructureError):
        parse_response(client.recognize(b"x", single_table=True))


def test_dns_mixed_answers_fail_closed(server, monkeypatch):
    import socket

    original = socket.getaddrinfo

    def mixed(host, port, *args, **kwargs):
        answers = original("127.0.0.1", port, *args, **kwargs)
        answers.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)))
        return answers

    monkeypatch.setattr(socket, "getaddrinfo", mixed)
    with pytest.raises(ValueError, match="LAN"):
        OllamaClient(Settings(url=server[0])).doctor()
    assert not server[1]["requests"]
