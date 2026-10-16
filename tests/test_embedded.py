import json
import socket
import subprocess
import sys
from threading import Event, Timer

import pytest

from localocr.embedded import EmbeddedOCRProvider, EmbeddedSettings
from localocr.ollama import Cancelled, OCRServerError

FAKE = """
import argparse,json,time
from http.server import BaseHTTPRequestHandler,HTTPServer
p=argparse.ArgumentParser()
p.add_argument('--port',type=int)
p.add_argument('--alias')
p.add_argument('--api-key')
a,unused=p.parse_known_args()
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  if MODE == 'hang': time.sleep(10)
  if MODE == 'exit': raise SystemExit(1)
  if self.headers.get('Authorization') != 'Bearer '+a.api_key:
   self.send_response(401);self.end_headers();return
  body=json.dumps({'data':[{'id':'foreign' if MODE=='foreign' else a.alias}]}).encode()
  self.send_response(200);self.end_headers();self.wfile.write(body)
 def do_POST(self):
  self.rfile.read(int(self.headers['Content-Length']))
  body=json.dumps({'choices':[{'message':{'content':'<table><tr><td>1</td></tr></table>'},'finish_reason':'stop'}]}).encode()
  self.send_response(200);self.end_headers();self.wfile.write(body)
server=HTTPServer(('127.0.0.1',a.port),Handler)
from pathlib import Path
Path(__file__).with_suffix('.ready').write_text('ready')
server.serve_forever()
"""


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "config"))
    engine = tmp_path / "engine"
    model = tmp_path / "model.gguf"
    mmproj = tmp_path / "mmproj.gguf"
    for path in [engine, model, mmproj]:
        path.write_bytes(b"local-fixture")
    script = tmp_path / "fake.py"
    script.write_text("MODE='ready'\n" + FAKE)
    original = subprocess.Popen
    launches = []

    def launch(args, **kwargs):
        launches.append(args)
        return original([sys.executable, str(script), *args[1:]], **kwargs)

    monkeypatch.setattr(subprocess, "Popen", launch)
    return (
        EmbeddedSettings(
            engine=engine,
            model_path=model,
            mmproj_path=mmproj,
            startup_timeout=2,
            device_mode="cpu",
        ),
        script,
        launches,
    )


def test_owned_lifecycle_reuse_no_external(fake_engine, monkeypatch, server):
    settings, _, launches = fake_engine
    connect = socket.socket.connect
    addresses = []

    def guarded(sock, address):
        if isinstance(address, tuple):
            addresses.append(address[0])
            assert address[0] == "127.0.0.1"
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    with EmbeddedOCRProvider(settings) as client:
        assert "CPU" in client.doctor()
        from localocr.config import config_dir

        assert client.lock_file is not None
        assert client.lock_file.name == str(config_dir() / "embedded.lock")
        process = client.process
        assert process is not None
        for _ in range(3):
            assert "<table>" in client.recognize(b"image")
        assert client.process is process and len(launches) == 1
        assert "--offline" in launches[0] and "-hf" not in launches[0]
        with pytest.raises(OCRServerError, match="уже"):
            EmbeddedOCRProvider(settings).doctor()
    assert process.poll() is not None
    assert addresses
    # The independent existing server remains alive after close.
    from localocr.ollama import OllamaClient, Settings

    assert "Подключено" in OllamaClient(Settings(url=server[0])).doctor()
    client.close()
    with EmbeddedOCRProvider(settings) as second:
        second.doctor()
    assert len(launches) == 2


@pytest.mark.parametrize("mode", ["foreign", "hang", "exit"])
def test_readiness_failure_shutdown(fake_engine, mode):
    settings, script, _ = fake_engine
    script.write_text(f"MODE={json.dumps(mode)}\n" + FAKE)
    client = EmbeddedOCRProvider(settings)
    with pytest.raises(OCRServerError):
        client.doctor()
    assert client.process is None and not client.owns_lock


def test_startup_cancel(fake_engine):
    import time

    settings, script, _ = fake_engine
    script.write_text("MODE='hang'\n" + FAKE)
    event = Event()
    client = EmbeddedOCRProvider(settings, event)

    def cancel_after_listening():
        deadline = time.monotonic() + 5
        while not script.with_suffix(".ready").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        event.set()

    timer = Timer(0.05, cancel_after_listening)
    timer.start()
    try:
        with pytest.raises(Cancelled):
            client.doctor()
    finally:
        timer.join()
    assert client.process is None and not client.owns_lock


def test_generated_key_with_leading_dash_is_safe(fake_engine, monkeypatch):
    import secrets

    monkeypatch.setattr(secrets, "token_urlsafe", lambda count: "-fixture-key")
    with EmbeddedOCRProvider(fake_engine[0]) as client:
        assert "CPU" in client.doctor()
        assert "<table>" in client.recognize(b"image")


@pytest.mark.parametrize("batch", [False, True])
def test_gui_runtime_status_main_thread(fake_engine, tmp_path, monkeypatch, batch):
    import time

    from PIL import Image
    from PySide6.QtCore import QThread, Slot
    from PySide6.QtWidgets import QApplication

    from localocr.gui.app import Window

    app = QApplication.instance() or QApplication([])
    threads = []

    class CheckedWindow(Window):
        @Slot(str)
        def update_embedded_status(self, message):
            threads.append(QThread.currentThread())
            super().update_embedded_status(message)

    window = CheckedWindow()
    window.provider.setCurrentIndex(window.provider.findData("embedded"))
    window.folder.setText(str(tmp_path))
    Image.new("RGB", (100, 100), "white").save(tmp_path / "input.png")
    monkeypatch.setattr("localocr.config.AppConfig.settings", lambda self: fake_engine[0])
    window.launch(not batch)
    deadline = time.monotonic() + 8
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.worker is None
    assert threads and all(thread == app.thread() for thread in threads)
    assert "режим=CPU" in window.embedded_status.text()
    assert "выбран CPU" in window.embedded_status.text()
    # Frozen qualification consumes this stable prefix.
    assert window.embedded_status.text().startswith("Embedded F16 · CPU ·")
    fake_engine[0].paths()[0].unlink()
    window.launch(True)
    deadline = time.monotonic() + 4
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert "не подтверждено" in window.embedded_status.text()
    window.close()
