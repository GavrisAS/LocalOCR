import json
import sys
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication, QRadioButton

from localocr import runtime
from localocr.config import AppConfig, config_dir, load_config, save_config, setup_logging
from localocr.gui.app import SimpleWindow


def test_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT_OVERRIDE", None)
    monkeypatch.chdir(tmp_path)
    assert runtime.portable_root() == runtime.Path(runtime.__file__).resolve().parents[2]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    for root in (tmp_path / "original", tmp_path / "moved"):
        for exe in (root / "LocalOCR.exe", root / "LocalOCR-CLI/LocalOCR-CLI.exe"):
            monkeypatch.setattr(sys, "executable", str(exe))
            assert config_dir() == root


def test_defaults_and_legacy(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps(
            {
                "api_token": "test-only",
                "ssl_verify": True,
                "trust_env": "false",
                "folder": "Русский",
            }
        )
    )
    monkeypatch.setattr("localocr.config.legacy_config", lambda: legacy)
    before = legacy.read_bytes()
    config = load_config()
    assert config.api_token == "test-only" and config.ssl_verify is True
    assert config.trust_env is False and config.folder == "Русский"
    assert legacy.read_bytes() == before
    monkeypatch.setattr(
        "localocr.config.legacy_config", lambda: pytest.fail("legacy consulted twice")
    )
    assert load_config() == config
    defaults = AppConfig()
    assert (defaults.provider, defaults.openwebui_api, defaults.simple_mode) == (
        "openwebui",
        "proxy",
        "server",
    )
    assert not defaults.ssl_verify and not defaults.trust_env


def test_atomic_and_rotation(tmp_path, monkeypatch):
    traps = [tmp_path / name for name in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME")]
    for name, path in zip(("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME"), traps):
        monkeypatch.setenv(name, str(path))
    save_config(AppConfig(folder="Русский"))
    setup_logging()
    import logging
    from logging.handlers import RotatingFileHandler

    handler = next(
        h for h in logging.getLogger("localocr").handlers if isinstance(h, RotatingFileHandler)
    )
    handler.doRollover()
    assert (config_dir() / "localocr.log.1").exists()
    original = (config_dir() / "config.json").read_bytes()

    def fail(*args):
        raise PermissionError("read only")

    monkeypatch.setattr("localocr.config.os.replace", fail)
    with pytest.raises(PermissionError):
        save_config(AppConfig(folder="new"))
    assert (config_dir() / "config.json").read_bytes() == original
    assert not list(config_dir().glob("*.tmp"))
    assert all(not path.exists() for path in traps)


def test_simple_settings_and_controls():
    app = QApplication.instance() or QApplication([])
    config = replace(
        AppConfig(),
        provider="ollama",
        openwebui_api="chat",
        openwebui_url="https://example.invalid",
        openwebui_model="fixture",
        api_token="test-only",
        precision="q8_0",
    )
    save_config(config)
    window = SimpleWindow()
    window.show()
    app.processEvents()
    assert len(window.findChildren(QRadioButton)) == 3
    assert not window.web_url.isVisible()
    settings = window.runtime_settings()
    assert settings.api == "proxy" and settings.api_token == config.api_token
    for mode in ("gpu", "cpu"):
        window.mode_buttons[mode].setChecked(True)
        settings = window.runtime_settings()
        assert settings.device_mode == mode and settings.precision == "f16"
        assert window.current_config().provider == "ollama"
        assert window.current_config().openwebui_api == "chat"
        assert window.current_config().precision == "q8_0"
        window.update_progress(1, 2, "progress")
        assert window.mode_buttons[mode].text() in window.statusBar().currentMessage()
    window.open_results()
    assert "не существует" in window.status.toPlainText()
    window.close()


def test_unreadable_legacy_and_read_only_root(monkeypatch):
    monkeypatch.setattr("localocr.config.legacy_config", lambda: config_dir() / "absent")
    assert load_config() == AppConfig()

    def denied(*args, **kwargs):
        raise PermissionError("read-only portable")

    monkeypatch.setattr("localocr.config.tempfile.mkstemp", denied)
    with pytest.raises(PermissionError):
        save_config(AppConfig())
    app = QApplication.instance() or QApplication([])
    window = SimpleWindow()
    window.mode_buttons["cpu"].setChecked(True)
    window.launch(True)
    assert window.worker is None and window.start.isEnabled()
    assert "Переместите" in window.status.toPlainText()
    window.hide()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("full", [False, True])
def test_main_smoke_routes(full, monkeypatch):
    import localocr.gui.app as gui

    created = []
    original = gui.Window if full else gui.SimpleWindow

    def factory():
        window = original()
        created.append(window)
        return window

    monkeypatch.setattr(gui, "Window" if full else "SimpleWindow", factory)
    monkeypatch.setattr(
        sys, "argv", ["localocr-gui", "--smoke-test", *(["--full-gui"] if full else [])]
    )
    original_app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui, "QApplication", lambda args: original_app)
    assert gui.main() == 0
    assert len(created) == 1


def test_simple_proxy_worker_lifecycle(server, tmp_path):
    import time

    from PIL import Image

    app = QApplication.instance() or QApplication([])
    save_config(
        AppConfig(
            folder=str(tmp_path),
            provider="ollama",
            openwebui_api="chat",
            openwebui_url=server[0],
            openwebui_model="glm-ocr:latest",
            api_token="test-only",
        )
    )
    Image.new("RGB", (60, 60), "white").save(tmp_path / "input.png")
    window = SimpleWindow()

    def wait():
        deadline = time.monotonic() + 5
        while window.worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert window.worker is None
        assert all(control.isEnabled() for control in window.controls())
        assert not window.stop.isEnabled()

    window.launch(True)
    assert not window.mode_buttons["cpu"].isEnabled()
    wait()
    assert server[1]["requests"][0][0] == "/ollama/api/tags"
    assert "Подключено" in window.status.toPlainText()
    window.launch()
    wait()
    assert (tmp_path / "results/input.xlsx").is_file()
    assert "REVIEW" in window.status.toPlainText()
    assert server[1]["text"] not in window.status.toPlainText()
    server[1]["status"] = 502
    window.launch(True)
    wait()
    assert window.bar.value() == 0
    assert "HTTP 502" in window.status.toPlainText()
    server[1]["delay"] = 1
    window.launch(True)
    window.close()
    assert window.worker is not None and window.worker.cancel.is_set()
    wait()
    window.close()
