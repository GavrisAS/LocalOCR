import json
from threading import Event

import httpx
import pytest

from localocr.config import AppConfig, config_dir, load_config, save_config
from localocr.embedded import EmbeddedOCRProvider, EmbeddedSettings
from localocr.ollama import Cancelled, OCRServerError, Settings
from localocr.providers import (
    OllamaDirectProvider,
    OpenWebUIChatProvider,
    OpenWebUIOllamaProxyProvider,
    OpenWebUISettings,
    create_provider,
)


@pytest.mark.parametrize(
    "api,cls,path",
    [
        ("proxy", OpenWebUIOllamaProxyProvider, "/prefix/ollama/api/generate"),
        ("chat", OpenWebUIChatProvider, "/prefix/api/chat/completions"),
    ],
)
def test_web_payload(api, cls, path, monkeypatch):
    requests = []
    body = (
        {"response": "<table>x</table>", "done": True}
        if api == "proxy"
        else {"choices": [{"message": {"content": "<table>x</table>"}, "finish_reason": "stop"}]}
    )

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=body)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    client = create_provider(
        OpenWebUISettings(
            url="https://corporate.example:444/prefix/",
            model="custom-id",
            api_token="fixture-token",
            api=api,
        )
    )
    assert isinstance(client, cls)
    assert client.recognize(b"image") == "<table>x</table>"
    assert client.last_diagnostic["endpoint"] == f"https://corporate.example:444{path}"
    assert client.last_diagnostic["response_length"] == len("<table>x</table>")
    assert "fixture-token" not in str(client.last_diagnostic)
    request = requests[-1]
    assert request.url.path == path
    assert request.headers["Authorization"] == "Bearer fixture-token"
    payload = json.loads(request.content)
    assert payload["model"] == "custom-id" and payload["stream"] is False
    if api == "chat":
        content = payload["messages"][0]["content"]
        assert content[0]["text"] == "Table Recognition:"
        assert content[1]["image_url"]["url"] == "data:image/png;base64,aW1hZ2U="
    else:
        assert payload["images"] == ["aW1hZ2U="]
    client.close()


@pytest.mark.parametrize("api", ["proxy", "chat"])
@pytest.mark.parametrize("status", [401, 403, 404, 302, 500])
def test_web_errors(api, status, monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(status)), **kw
        ),
    )
    with pytest.raises(OCRServerError):
        create_provider(OpenWebUISettings(api=api)).recognize(b"x")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"error": "bad model"},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "x"}, "finish_reason": "length"}]},
    ],
)
def test_chat_invalid(body, monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)), **kw
        ),
    )
    with pytest.raises(OCRServerError):
        create_provider(OpenWebUISettings(api="chat")).recognize(b"x")


@pytest.mark.parametrize("body", [[], {"data": []}, {"models": [{"id": "custom"}]}])
def test_chat_doctor_visibility(body, monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)), **kw
        ),
    )
    assert "Подключено" in create_provider(OpenWebUISettings(api="chat")).doctor()


def test_factory_and_cancel():
    assert isinstance(create_provider(Settings()), OllamaDirectProvider)
    event = Event()
    event.set()
    for api in ["proxy", "chat"]:
        with pytest.raises(Cancelled):
            create_provider(OpenWebUISettings(api=api), event).recognize(b"x")
    with pytest.raises(ValueError):
        create_provider(object())
    with pytest.raises(ValueError):
        create_provider(OpenWebUISettings(api="auto"))


def test_config_migration_and_plain_token(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config_dir().mkdir(parents=True)
    (config_dir() / "config.json").write_text(
        json.dumps({"folder": "old", "ollama_url": "http://192.168.1.2:11434"})
    )
    old = load_config()
    assert old.folder == "old" and old.provider == "openwebui"
    config = AppConfig(
        folder="new",
        provider="openwebui",
        api_token="fixture-plain",
        openwebui_url="https://example.org/prefix",
        openwebui_model="selected",
        openwebui_api="chat",
        precision="q8_0",
    )
    save_config(config)
    assert load_config() == config
    assert json.loads((config_dir() / "config.json").read_text())["api_token"] == "fixture-plain"


def test_embedded_missing_local_files(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("network attempted"))
    with pytest.raises(ValueError, match="не установлен"):
        EmbeddedOCRProvider(EmbeddedSettings(engine=tmp_path / "missing"))


@pytest.mark.parametrize("api", ["proxy", "chat"])
def test_web_inflight_cancel_and_retry(api, monkeypatch):
    import asyncio
    import threading
    import time

    original = httpx.AsyncClient
    requests = []
    event = Event()

    async def slow(request):
        requests.append(request)
        await asyncio.sleep(2)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(slow), **kw)
    )
    timer = threading.Timer(0.15, event.set)
    timer.start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        create_provider(OpenWebUISettings(api=api), event).recognize(b"context")
    timer.join()
    assert time.monotonic() - started < 1

    def retry(request):
        requests.append(request)
        body = (
            {"response": "table", "done": True}
            if api == "proxy"
            else {"choices": [{"message": {"content": "table"}}]}
        )
        return httpx.Response(500 if len(requests) == 1 else 200, json=body)

    requests.clear()
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(retry), **kw)
    )
    assert create_provider(OpenWebUISettings(api=api)).recognize(b"context") == "table"
    assert len(requests) == 2 and requests[0].content == requests[1].content


def test_shared_pipeline_fidelity_across_server_adapters(tmp_path, monkeypatch, visible_text):
    from PIL import Image

    from localocr.quality import export
    from localocr.service import convert

    text = (
        "<table><tr><td>0012</td><td>1.20</td><td>=SUM(A1)</td></tr>"
        "<tr><td>A</td><td>B</td><td>C</td></tr></table>"
    )
    original = httpx.AsyncClient

    def handler(request):
        if request.url.path.endswith("tags"):
            body = {"models": [{"name": "glm-ocr:latest"}]}
        elif request.url.path.endswith("models"):
            body = {"data": []}
        elif request.url.path.endswith("generate"):
            body = {"response": text, "done": True}
        else:
            body = {"choices": [{"message": {"content": text}}]}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    image = tmp_path / "image.png"
    visible_text(Image.new("RGB", (100, 100), "white")).save(image)
    actual = []
    for index, settings in enumerate(
        [Settings(), OpenWebUISettings(), OpenWebUISettings(api="chat")]
    ):
        result = convert(image, settings, output_dir=tmp_path / str(index))[0]
        assert result.status == "REVIEW"
        actual.append(export(tmp_path / str(index) / "image.xlsx"))
    assert actual[0] == actual[1] == actual[2]
    cells = actual[0]["tables"][0]["cells"]
    assert cells[0]["value"] == "0012" and cells[2]["type"] == "s"
    assert cells[1]["number_format"] == "0.00"


def test_chat_single_table_stops_at_closed_table(monkeypatch):
    from localocr.tables import parse_response

    requests = []
    original = httpx.AsyncClient
    text = "<table><tr><td>0012</td></tr>"

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    client = create_provider(OpenWebUISettings(api="chat"))
    result = client.recognize(b"image", single_table=True)
    assert requests[-1]["stop"] == ["</table>"]
    assert parse_response(result).tables[0].cells[0].text == "0012"
    client.recognize(b"image", single_table=False)
    assert "stop" not in requests[-1]
