"""Bounded technical HTTP diagnostics, independent of Qt and OCR content."""

import base64
import binascii
import errno
import logging
import re
import socket
import ssl
from collections.abc import Callable
from datetime import datetime

import httpx

NetworkCallback = Callable[[str], None]


def exception_detail(error: BaseException | None) -> str:
    parts = []
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        parts.append(
            f"{type(error).__module__}.{type(error).__name__}: {error}"
            + (f" (errno={error.errno})" if isinstance(error, OSError) else "")
        )
        error = error.__cause__ or error.__context__
    return " ; cause: ".join(parts)[:4096]


def category(error: BaseException) -> str:
    chain = exception_detail(error).lower()
    if isinstance(error, httpx.ProxyError):
        return "PROXY_ERROR"
    for cls, label in (
        (httpx.ConnectTimeout, "CONNECT_TIMEOUT"),
        (httpx.ReadTimeout, "READ_TIMEOUT"),
        (httpx.WriteTimeout, "WRITE_TIMEOUT"),
        (httpx.PoolTimeout, "POOL_TIMEOUT"),
        (TimeoutError, "DEADLINE_TIMEOUT"),
    ):
        if isinstance(error, cls):
            return label
    if "certificate_verify_failed" in chain or "sslcertverificationerror" in chain:
        return "TLS_CERTIFICATE_VERIFY_FAILED"
    if "ssl" in chain or isinstance(error, ssl.SSLError):
        return "TLS_ERROR"
    if "gaierror" in chain or isinstance(error, socket.gaierror):
        return "DNS_ERROR"
    if "connectionrefusederror" in chain or "connection refused" in chain:
        return "CONNECT_REFUSED"
    if str(errno.ENETUNREACH) in chain and "errno" in chain or "unreachable" in chain:
        return "CONNECT_UNREACHABLE"
    if isinstance(error, ValueError):
        return "URL_INVALID"
    return "NETWORK_ERROR"


def emit(owner, message: str):
    if getattr(owner, "suppress_network_events", False):
        return
    token = getattr(owner.settings, "api_token", "")
    if token:
        message = message.replace(token, "TOKEN_OMITTED")
    message = re.sub(r"[A-Za-z0-9+/]{128,}={0,2}", "IMAGE_BASE64_OMITTED", message)
    line = f"[{datetime.now():%H:%M:%S}] {message}"
    logging.getLogger("localocr").info("%s", line)
    callback = getattr(owner, "on_network_event", None)
    if callback:
        callback(line)


def payload_summary(payload) -> str:
    if payload is None:
        return "GET без body"
    image = next(iter(payload.get("images", [])), "")
    mime = "не известно"
    if not image:
        for message in payload.get("messages", []):
            content = message.get("content", [])
            if isinstance(content, list):
                for part in content:
                    url = part.get("image_url", {}).get("url", "")
                    if url.startswith("data:") and ";base64," in url:
                        mime, image = url[5:].split(";base64,", 1)
                        break
    elif image:
        try:
            header = base64.b64decode(image[:24])
        except ValueError, binascii.Error:
            header = b""
        mime = (
            "image/jpeg"
            if header.startswith(b"\xff\xd8\xff")
            else "image/png"
            if header.startswith(b"\x89PNG")
            else "не известно"
        )
    size = len(image) * 3 // 4 - (len(image) - len(image.rstrip("="))) if image else 0
    return (
        f"POST JSON keys={','.join(payload)} ; model={payload.get('model')} ; "
        f"stream={payload.get('stream')} ; max_tokens={payload.get('max_tokens')} ; "
        f"num_predict={payload.get('options', {}).get('num_predict')} ; "
        f"image={bool(image)} ; mime={mime} ; image_bytes={size} (IMAGE_BASE64_OMITTED)"
    )
