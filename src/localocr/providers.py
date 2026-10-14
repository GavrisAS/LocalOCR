"""Backend settings and transport adapters; canonical tables stay in the service."""

import base64
from dataclasses import dataclass
from threading import Event
from typing import Protocol
from urllib.parse import urlsplit

from localocr.ollama import OCRServerError, OllamaClient, Settings


class OCRProvider(Protocol):
    def doctor(self) -> str: ...
    def recognize(self, image: bytes, *, single_table: bool = False) -> str: ...
    def check_cancel(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class OpenWebUISettings:
    url: str = "http://127.0.0.1:8080"
    model: str = "glm-ocr:latest"
    timeout: float = 300
    num_predict: int = 16000
    retries: int = 1
    api_token: str = ""
    api: str = "proxy"

    def validate(self):
        parsed = urlsplit(self.url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Укажите HTTP(S) URL OpenWebUI без credentials/query/fragment")
        try:
            parsed.port
        except ValueError as error:
            raise ValueError("Некорректный порт OpenWebUI") from error
        if self.api not in {"proxy", "chat"}:
            raise ValueError("Выберите OpenWebUI proxy или chat")
        if not self.model.strip() or not 1 <= self.timeout <= 7200:
            raise ValueError("Недопустимый model ID или timeout")
        if self.retries not in range(3) or not 256 <= self.num_predict <= 32768:
            raise ValueError("Недопустимые параметры OCR")
        if "\n" in self.api_token or "\r" in self.api_token:
            raise ValueError("Некорректный API-токен")


class OllamaDirectProvider(OllamaClient):
    pass


class OpenWebUIOllamaProxyProvider(OllamaClient):
    server_name = "OpenWebUI"
    settings: OpenWebUISettings

    def __init__(self, settings: OpenWebUISettings, cancel: Event | None = None):
        settings.validate()
        self.settings = settings
        self.cancel = cancel or Event()

    async def route(self):
        return (
            self.settings.url.rstrip("/"),
            {
                "Authorization": f"Bearer {self.settings.api_token}",
                "Content-Type": "application/json",
            },
            {},
        )

    def request(self, method: str, endpoint: str, payload=None):
        return super().request(method, "/ollama" + endpoint, payload)


class OpenWebUIChatProvider(OpenWebUIOllamaProxyProvider):
    def request(self, method: str, endpoint: str, payload=None):
        return OllamaClient.request(self, method, endpoint, payload)

    def normalize_result(self, result):
        # OpenWebUI versions expose either a bare array or an OpenAI envelope.
        return {"data": result} if isinstance(result, list) else result

    def doctor(self):
        data = self.request("GET", "/api/models")
        models = data.get("data", data.get("models"))
        if not isinstance(models, list):
            raise OCRServerError("Некорректный список моделей OpenWebUI")
        # Visibility of the list may be restricted: recognize remains authoritative.
        visible = any(
            isinstance(item, dict) and item.get("id", item.get("name")) == self.settings.model
            for item in models
        )
        suffix = "" if visible else " · model ID не виден в списке; проверьте при OCR"
        return f"Подключено · {self.settings.model}{suffix}"

    def recognize(self, image: bytes, *, single_table: bool = False) -> str:
        data = self.request(
            "POST",
            "/api/chat/completions",
            chat_payload(self.settings, image, single_table=single_table),
        )
        return chat_text(data, single_table=single_table)


def chat_payload(settings, image: bytes, *, single_table=False):
    mime = "image/jpeg" if image.startswith(b"\xff\xd8\xff") else "image/png"
    return {
        "model": settings.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Table Recognition:"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64," + base64.b64encode(image).decode("ascii")
                        },
                    },
                ],
            }
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": settings.num_predict,
        **({"stop": ["</table>"]} if single_table else {}),
    }


def chat_text(data, *, single_table=False) -> str:
    try:
        choice = data["choices"][0]
        text = choice["message"]["content"]
        if choice.get("finish_reason") == "length":
            raise OCRServerError("Усечённый ответ OCR; требуется меньший фрагмент")
        if not isinstance(text, str) or not text.strip():
            raise OCRServerError("Пустой OCR-ответ")
        if (
            single_table
            and choice.get("finish_reason") == "stop"
            and "<table" in text.lower()
            and "</table>" not in text.lower()
        ):
            # Restore only the requested stop delimiter, never rows or cell values.
            text += "</table>"
        return text
    except (KeyError, IndexError, TypeError) as error:
        raise OCRServerError("Некорректный Chat Completions OCR-ответ") from error


def create_provider(settings, cancel: Event | None = None) -> OCRProvider:
    from localocr.embedded import EmbeddedOCRProvider, EmbeddedSettings

    if isinstance(settings, EmbeddedSettings):
        return EmbeddedOCRProvider(settings, cancel)
    if isinstance(settings, OpenWebUISettings):
        settings.validate()
        cls = OpenWebUIChatProvider if settings.api == "chat" else OpenWebUIOllamaProxyProvider
        return cls(settings, cancel)
    if isinstance(settings, Settings):
        return OllamaDirectProvider(settings, cancel)
    raise ValueError("Неизвестные настройки OCR provider")
