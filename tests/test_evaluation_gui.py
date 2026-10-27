from PySide6.QtWidgets import QApplication

from localocr.config import AppConfig, load_config, save_config
from localocr.gui.app import SimpleWindow, Window
from localocr.ollama import Settings


def test_simple_uses_selected_direct_and_accepts_empty_web_token():
    app = QApplication.instance() or QApplication([])
    save_config(AppConfig(provider="ollama", ollama_model="synthetic-direct"))
    window = SimpleWindow()
    assert isinstance(window.runtime_settings(), Settings)
    assert window.runtime_settings().model == "synthetic-direct"
    window.close()
    save_config(
        AppConfig(
            provider="openwebui",
            api_token="",
            openwebui_url="http://127.0.0.1:8080",
            openwebui_model="synthetic",
        )
    )
    window = SimpleWindow()
    assert window.runtime_settings().api_token == ""
    window.close()
    app.processEvents()


def test_full_editor_from_simple_preserves_opt_in_and_has_server_fields():
    app = QApplication.instance() or QApplication([])
    window = SimpleWindow()
    window.show()
    window.fail_soft.setChecked(True)
    window.advanced.click()
    app.processEvents()
    full = window.full_window
    assert isinstance(full, Window) and full.isVisible() and not window.isVisible()
    assert full.fail_soft.isChecked()
    full.web_model.setText("synthetic-chat")
    full.api.setCurrentIndex(full.api.findData("chat"))
    full.close()
    assert load_config().fail_soft and load_config().openwebui_model == "synthetic-chat"
    window.deleteLater()
    app.processEvents()
