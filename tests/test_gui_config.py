import time

from PySide6.QtWidgets import QApplication

from localocr.config import AppConfig, load_config, save_config
from localocr.gui.app import Window


def test_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config = AppConfig("Русская папка", "http://192.168.1.100:11434")
    save_config(config)
    assert load_config() == config
    from localocr.config import config_dir

    (config_dir() / "config.json").write_text("broken")
    assert load_config() == AppConfig()


def test_gui_responsive_connection_cancel(server, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    url, state = server
    save_config(AppConfig(str(tmp_path), url))
    window = Window()
    window.show()
    assert window.url.text() == url
    state["delay"] = 2
    window.launch(True)
    worker = window.worker
    window.launch(True)
    assert window.worker is worker and not window.start.isEnabled()
    start = time.monotonic()
    count = 0
    while time.monotonic() - start < 0.2:
        app.processEvents()
        count += 1
        time.sleep(0.005)
    assert count > 10 and window.worker is not None
    window.cancel()
    deadline = time.monotonic() + 2
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.worker is None and window.start.isEnabled()
    state["delay"] = 0
    window.launch(True)
    deadline = time.monotonic() + 3
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert "Подключено" in window.status.toPlainText()
    window.update_progress(1, 2, "test")
    assert window.bar.value() < window.bar.maximum()
    window.close()


def test_gui_batch_progress_results(server, tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "config"))
    app = QApplication.instance() or QApplication([])
    Image.new("RGB", (100, 100), "white").save(tmp_path / "input.png")
    window = Window()
    window.folder.setText(str(tmp_path))
    window.url.setText(server[0])
    window.launch()
    deadline = time.monotonic() + 5
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.worker is None
    assert "REVIEW" in window.status.toPlainText()
    assert window.bar.value() == window.bar.maximum()
    assert (tmp_path / "results" / "input.xlsx").exists()
    assert window.start.isEnabled()
    window.close()


def test_gui_backend_fields_persist_independently(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = Window()
    window.show()
    window.url.setText("http://192.168.1.2:11434")
    window.model.setText("direct-model")
    window.provider.setCurrentIndex(window.provider.findData("openwebui"))
    app.processEvents()
    assert window.token.isVisible() and not window.url.isVisible()
    window.web_url.setText("https://corporate.example/prefix")
    window.web_model.setText("chat-model")
    window.token.setText("fixture-plain-token")
    window.api.setCurrentIndex(window.api.findData("chat"))
    window.provider.setCurrentIndex(window.provider.findData("embedded"))
    app.processEvents()
    assert window.precision.isVisible() and not window.token.isVisible()
    window.close()
    restored = Window()
    assert restored.provider.currentData() == "embedded"
    assert restored.url.text() == "http://192.168.1.2:11434"
    assert restored.model.text() == "direct-model"
    assert restored.web_model.text() == "chat-model"
    assert restored.token.text() == "fixture-plain-token"
    assert restored.api.currentData() == "chat"
    restored.close()
