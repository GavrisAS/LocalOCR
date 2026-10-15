"""Bounded async native Ollama client with cancellation and LAN-only routing."""

import asyncio
import base64
import ipaddress
import json
import socket
import time
from dataclasses import dataclass
from threading import Event
from urllib.parse import urlsplit

import httpx

from localocr.network import category, emit, exception_detail, payload_summary, redact


class OCRServerError(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    url: str = "http://127.0.0.1:11434"
    model: str = "glm-ocr:latest"
    timeout: float = 300
    num_predict: int = 16000
    retries: int = 1

    def validate(self):
        if not 1 <= self.timeout <= 7200 or not 256 <= self.num_predict <= 32768:
            raise ValueError("Недопустимый timeout или num_predict")
        if self.retries not in range(3) or not self.model.strip():
            raise ValueError("Недопустимые параметры OCR")
        validate_url(self.url)


def local_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if ip.is_loopback:
        return True
    networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
    return any(ip in ipaddress.ip_network(network) for network in networks)


def validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Укажите HTTP(S) адрес локального/LAN Ollama без пути и credentials")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("Некорректный порт") from error


async def pinned_url(url: str) -> tuple[str, str, str]:
    """Resolve once and connect to a checked IP, preserving Host and TLS SNI."""
    validate_url(url)
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM), 5
        )
    except (OSError, TimeoutError) as error:
        raise OCRServerError("Не удалось разрешить адрес Ollama") from error
    if not addresses or any(not local_address(str(item[4][0])) for item in addresses):
        raise ValueError("Разрешены только loopback и частные LAN-адреса Ollama")
    address = str(addresses[0][4][0])
    literal = f"[{address}]" if ":" in address else address
    authority = f"[{host}]" if ":" in host else host
    return f"{parsed.scheme}://{literal}:{port}", f"{authority}:{port}", host


class OllamaClient:
    server_name = "Ollama"

    def __init__(self, settings: Settings, cancel: Event | None = None):
        settings.validate()
        self.settings = settings
        self.cancel = cancel or Event()

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled("Обработка отменена")

    async def route(self):
        base, host, sni = await pinned_url(self.settings.url)
        return base, {"Host": host}, {"sni_hostname": sni}

    def normalize_result(self, result):
        return result

    def close(self):
        """No persistent connection or subprocess in Direct Ollama."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    async def _request_async(self, method: str, endpoint: str, payload=None):
        try:
            base, headers, extensions = await self.route()
        except Exception as error:
            detail = f"{category(error)} · URL validation / DNS · input={self.settings.url} · {exception_detail(error)}"
            emit(self, detail)
            if isinstance(error, ValueError):
                raise
            raise OCRServerError(detail) from error
        deadline = time.monotonic() + self.settings.timeout
        timeout = httpx.Timeout(self.settings.timeout, connect=5, pool=5)
        verify = getattr(self.settings, "ssl_verify", True)
        trust_env = getattr(self.settings, "trust_env", False)
        async with httpx.AsyncClient(
            trust_env=trust_env, follow_redirects=False, verify=verify, timeout=timeout
        ) as client:
            for attempt in range(self.settings.retries + 1):
                self.check_cancel()
                status_seen = None
                try:
                    async with asyncio.timeout(max(0.01, deadline - time.monotonic())):
                        try:
                            request = client.build_request(
                                method,
                                base + endpoint,
                                json=payload,
                                headers=headers,
                                extensions=extensions,
                            )
                        except (httpx.InvalidURL, UnicodeError, ValueError) as error:
                            label = (
                                "URL_INVALID"
                                if isinstance(error, httpx.InvalidURL)
                                else "REQUEST_BUILD_ERROR"
                            )
                            detail = redact(
                                self.settings,
                                f"{label} · Request build / URL validation · input={self.settings.url} · {exception_detail(error)}",
                            )
                            emit(self, detail)
                            raise ValueError(detail) from error
                        operation = "doctor" if method == "GET" else "recognize"
                        emit(
                            self,
                            f"{self.server_name} · {operation} · попытка {attempt + 1}/{self.settings.retries + 1}",
                        )
                        emit(
                            self,
                            f"Настройки: input={self.settings.url} ; base={base} ; hostname={request.url.host} ; port={request.url.port} ; path={request.url.path} ; prefix={urlsplit(self.settings.url).path or '/'} ; TLS verify={verify} ; trust_env={trust_env} ; redirects=False ; connect=5s ; read/write/total={self.settings.timeout}s ; pool=5s ; token={'задан' if getattr(self.settings, 'api_token', '') else 'не задан'} ; Authorization Bearer={'отправляется' if 'Authorization' in request.headers else 'нет'}",
                        )
                        emit(
                            self,
                            f"HTTP → {request.method} {request.url} ; {payload_summary(payload)}",
                        )
                        started = time.monotonic()
                        response = await client.send(request, stream=True)
                        status_seen = response.status_code
                        network_stream = response.extensions.get("network_stream")
                        if network_stream is not None:
                            peer = network_stream.get_extra_info("server_addr")
                            if peer is not None:
                                emit(self, f"Transport peer (наблюдаемый): {peer}")
                        try:
                            emit(
                                self,
                                f"HTTP ← {response.status_code} {response.reason_phrase} ; content-type={response.headers.get('content-type', '')} ; elapsed={time.monotonic() - started:.3f}s",
                            )
                            if response.status_code >= 300:
                                fragment = bytearray()
                                async for chunk in response.aiter_bytes():
                                    fragment.extend(chunk[: 4096 - len(fragment)])
                                    if len(fragment) >= 4096:
                                        break
                                emit(
                                    self,
                                    f"Ответ сервера (фрагмент): {fragment.decode('utf-8', errors='replace')}",
                                )
                                if 300 <= response.status_code < 400:
                                    detail = f"HTTP_REDIRECT Location={response.headers.get('location', '')} ; redirects запрещены"
                                    emit(self, detail)
                                    raise OCRServerError(detail)
                                response.raise_for_status()
                            body = bytearray()
                            async for chunk in response.aiter_bytes():
                                self.check_cancel()
                                body.extend(chunk)
                                if len(body) > 4_500_000:
                                    raise OCRServerError(
                                        f"Ответ {self.server_name} слишком большой"
                                    )
                        finally:
                            await response.aclose()
                    try:
                        result = json.loads(body)
                    except (ValueError, UnicodeError) as error:
                        raise OCRServerError(
                            f"{'EMPTY_RESPONSE' if not body else 'INVALID_JSON'} от {self.server_name}"
                        ) from error
                    result = self.normalize_result(result)
                    if not isinstance(result, dict) or result.get("error"):
                        raise OCRServerError(f"MALFORMED_API_RESPONSE от {self.server_name}")
                    emit(
                        self,
                        f"Результат HTTP API: PASS ; elapsed_total={time.monotonic() - started:.3f}s (доступ модели/OCR проверяется отдельно)",
                    )
                    return result
                except (httpx.TimeoutException, TimeoutError) as error:
                    detail = f"{category(error)} ; истекло время ожидания ; HTTP status: {status_seen if status_seen is not None else 'нет'} ; {exception_detail(error)}"
                    emit(self, detail)
                    raise OCRServerError(detail) from error
                except httpx.HTTPStatusError as error:
                    emit(
                        self,
                        f"FAIL / HTTP_{error.response.status_code} ; {exception_detail(error)}",
                    )
                    if error.response.status_code >= 500 and attempt < self.settings.retries:
                        await asyncio.sleep(0.2)
                        continue
                    raise OCRServerError(
                        f"{self.server_name} HTTP {error.response.status_code}"
                    ) from error
                except httpx.RequestError as error:
                    detail = f"{category(error)} ; HTTP status: {status_seen if status_seen is not None else 'нет'} ; {exception_detail(error)}"
                    emit(self, detail)
                    if attempt < self.settings.retries:
                        await asyncio.sleep(0.2)
                        continue
                    raise OCRServerError(detail) from error
        raise OCRServerError(f"{self.server_name} не ответил")

    async def _cancellable(self, method, endpoint, payload):
        task = asyncio.create_task(self._request_async(method, endpoint, payload))
        try:
            while not task.done():
                self.check_cancel()
                await asyncio.sleep(0.05)
            return await task
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def request(self, method: str, endpoint: str, payload=None):
        self.check_cancel()
        try:
            return asyncio.run(self._cancellable(method, endpoint, payload))
        except Cancelled:
            emit(self, "CANCELLED · запрос отменён")
            raise
        except OCRServerError as error:
            emit(self, f"Результат: FAIL · {exception_detail(error)}")
            safe = redact(self.settings, str(error))
            if safe != str(error):
                raise OCRServerError(safe) from error
            raise

    def doctor(self):
        data = self.request("GET", "/api/tags")
        models = data.get("models")
        if not isinstance(models, list):
            raise OCRServerError("MALFORMED_API_RESPONSE: Некорректный список моделей Ollama")
        if not any(
            isinstance(model, dict) and model.get("name") == self.settings.model for model in models
        ):
            emit(
                self,
                f"MODEL_NOT_FOUND/NOT_VISIBLE · HTTP API доступен, модель {self.settings.model} не видна",
            )
            raise OCRServerError(f"Модель {self.settings.model} не установлена на сервере Ollama")
        emit(self, f"doctor PASS · модель {self.settings.model} видна; OCR ещё не выполнялся")
        return f"Подключено · {self.settings.model}"

    def recognize(self, image: bytes, *, single_table: bool = False) -> str:
        data = self.request(
            "POST",
            "/api/generate",
            {
                "model": self.settings.model,
                "prompt": "Table Recognition:",
                "images": [base64.b64encode(image).decode("ascii")],
                "stream": False,
                "options": {
                    "temperature": 0,
                    "seed": 0,
                    "num_ctx": 32768,
                    "num_predict": self.settings.num_predict,
                    **({"stop": ["</table>"]} if single_table else {}),
                },
            },
        )
        text = data.get("response")
        if not isinstance(text, str) or not text.strip():
            raise OCRServerError("EMPTY_RESPONSE: Пустой OCR-ответ")
        if data.get("done") is not True or data.get("done_reason") == "length":
            raise OCRServerError("Усечённый ответ OCR; требуется меньший фрагмент")
        # Ollama omits the matched stop sequence from response. Restore only that
        # delimiter after a confirmed stop, never cell values or incomplete rows.
        if single_table and data.get("done_reason") == "stop" and "</table>" not in text.lower():
            text += "</table>"
        return text
