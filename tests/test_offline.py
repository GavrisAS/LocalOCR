"""Enforce no external sockets while running a real HTTP+XLSX pipeline."""

import ipaddress
import socket

from PIL import Image

from localocr.ollama import Settings
from localocr.service import convert


def test_runtime_with_external_connect_forbidden(server, tmp_path, monkeypatch, visible_text):
    original = socket.socket.connect
    attempts = []

    def guarded(sock, address):
        if isinstance(address, tuple):
            attempts.append(address)
            assert ipaddress.ip_address(address[0]).is_loopback, "External connection attempted"
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setenv("HTTP_PROXY", "http://8.8.8.8:1234")
    image = tmp_path / "source.png"
    visible_text(Image.new("RGB", (100, 100), "white")).save(image)
    result = convert(image, Settings(url=server[0]))
    assert result[0].status == "REVIEW"
    assert attempts
    assert all(ipaddress.ip_address(address[0]).is_loopback for address in attempts)
