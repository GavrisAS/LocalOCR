"""Responsive Qt window, shared service, cancellable worker threads."""

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from localocr import __version__, build_commit
from localocr.config import AppConfig, load_config, save_config, setup_logging
from localocr.network import redact
from localocr.ollama import Cancelled
from localocr.providers import create_provider
from localocr.runtime import write_error
from localocr.service import convert


class Worker(QThread):
    progress = Signal(int, int, str)
    result = Signal(object)
    error = Signal(str)
    network = Signal(str)
    runtime_status = Signal(str)

    def __init__(self, folder: str, settings, check=False):
        super().__init__()
        self.folder, self.settings, self.check = folder, settings, check
        self.cancel = Event()

    def run(self):
        try:
            settings = self.settings
            if self.check:
                client = create_provider(
                    settings,
                    self.cancel,
                    on_network_event=self.network.emit,
                    on_runtime_status=self.runtime_status.emit,
                )
                try:
                    self.result.emit(client.doctor())
                finally:
                    client.close()
            else:
                self.result.emit(
                    convert(
                        Path(self.folder),
                        settings,
                        cancel=self.cancel,
                        on_network_event=self.network.emit,
                        on_runtime_status=self.runtime_status.emit,
                        progress=lambda a, b, c: self.progress.emit(a, b, c),
                    )
                )
        except Cancelled:
            self.runtime_status.emit("Embedded: операция отменена; состояние не подтверждено")
            self.error.emit("Операция отменена")
        except Exception as error:
            self.runtime_status.emit("Embedded: ошибка; состояние не подтверждено")
            self.error.emit(
                redact(
                    self.settings, write_error(error) if isinstance(error, OSError) else str(error)
                )
            )


_ACTIVE_WORKER: Worker | None = None


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LocalOCR")
        self.resize(680, 440)
        self.worker: Worker | None = None
        config = load_config()
        self.folder = QLineEdit(config.folder)
        self.config = config
        self.provider = QComboBox()
        for label, value in [
            ("Встроенная GLM-OCR", "embedded"),
            ("Ollama", "ollama"),
            ("OpenWebUI", "openwebui"),
        ]:
            self.provider.addItem(label, value)
        self.provider.setCurrentIndex(max(0, self.provider.findData(config.provider)))
        self.url = QLineEdit(config.ollama_url)
        self.model = QLineEdit(config.ollama_model)
        self.web_url = QLineEdit(config.openwebui_url)
        self.web_model = QLineEdit(config.openwebui_model)
        self.token = QLineEdit(config.api_token)
        self.api = QComboBox()
        self.api.addItem("Ollama Proxy", "proxy")
        self.api.addItem("Chat Completions", "chat")
        self.api.setCurrentIndex(max(0, self.api.findData(config.openwebui_api)))
        self.ssl_verify = QCheckBox("Проверять SSL/TLS-сертификат")
        self.ssl_verify.setChecked(config.ssl_verify)
        self.trust_env = QCheckBox("Использовать системный прокси")
        self.trust_env.setChecked(config.trust_env)
        self.precision = QComboBox()
        self.precision.addItem("F16 (основной)", "f16")
        from localocr.embedded import EmbeddedSettings

        if all(path.is_file() for path in EmbeddedSettings(precision="q8_0").paths()):
            self.precision.addItem("Q8_0", "q8_0")
        self.precision.setCurrentIndex(max(0, self.precision.findData(config.precision)))
        self.device = QComboBox()
        for label in ("Auto", "GPU", "CPU"):
            self.device.addItem(label, label.lower())
        self.device.setCurrentIndex(max(0, self.device.findData(config.embedded_device)))
        self.embedded_status = QLabel(
            "Проверить локальный комплект: кнопка «Проверить подключение»"
        )
        self.browse = QPushButton("Обзор...")
        self.check = QPushButton("Проверить подключение")
        self.start = QPushButton("Начать обработку")
        self.stop = QPushButton("Остановить")
        self.stop.setEnabled(False)
        self.open = QPushButton("Открыть папку результатов")
        self.bar = QProgressBar()
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setMaximumBlockCount(3000)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("Папка с изображениями"))
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(self.browse)
        layout.addLayout(row)
        layout.addWidget(self.provider)
        self.mode_widgets = {}
        for mode, fields in {
            "ollama": [("Ollama URL", self.url), ("Model ID", self.model)],
            "openwebui": [
                ("OpenWebUI URL", self.web_url),
                ("Model ID", self.web_model),
                ("API-токен", self.token),
                ("Тип API", self.api),
                ("", self.ssl_verify),
                ("", self.trust_env),
            ],
            "embedded": [
                ("Набор весов", self.precision),
                ("Вычисления", self.device),
                ("Статус", self.embedded_status),
            ],
        }.items():
            widgets = []
            for title, widget in fields:
                label = QLabel(title)
                layout.addWidget(label)
                layout.addWidget(widget)
                widgets.extend([label, widget])
            self.mode_widgets[mode] = widgets
        self.provider.currentIndexChanged.connect(self.update_mode)
        self.update_mode()
        for button in [self.check, self.start, self.stop]:
            layout.addWidget(button)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addWidget(self.open)
        self.setCentralWidget(central)
        self.show_status("Готово")
        self.browse.clicked.connect(self.choose)
        self.check.clicked.connect(lambda: self.launch(True))
        self.start.clicked.connect(lambda: self.launch(False))
        self.stop.clicked.connect(self.cancel)
        self.open.clicked.connect(self.open_results)

    def mode_label(self):
        return self.provider.currentText()

    def show_status(self, message):
        self.statusBar().showMessage(f"Версия {__version__} · {self.mode_label()} · {message}")

    def update_mode(self):
        for mode, widgets in self.mode_widgets.items():
            for widget in widgets:
                widget.setVisible(mode == self.provider.currentData())

    def current_config(self):
        return AppConfig(
            simple_mode=self.config.simple_mode,
            folder=self.folder.text(),
            ollama_url=self.url.text(),
            provider=self.provider.currentData(),
            ollama_model=self.model.text(),
            openwebui_url=self.web_url.text(),
            openwebui_model=self.web_model.text(),
            api_token=self.token.text(),
            openwebui_api=self.api.currentData(),
            precision=self.precision.currentData(),
            embedded_device=self.device.currentData(),
            ssl_verify=self.ssl_verify.isChecked(),
            trust_env=self.trust_env.isChecked(),
        )

    def controls(self):
        return [
            self.start,
            self.check,
            self.browse,
            self.folder,
            self.url,
            self.model,
            self.provider,
            self.web_url,
            self.web_model,
            self.token,
            self.api,
            self.ssl_verify,
            self.trust_env,
            self.precision,
            self.device,
        ]

    def choose(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка с изображениями", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def runtime_settings(self):
        return self.current_config().settings()

    def open_results(self):
        folder = Path(self.folder.text())
        if (
            not self.folder.text().strip()
            or not folder.is_dir()
            or not (folder / "results").is_dir()
        ):
            self.status.appendPlainText(
                "Папка результатов не существует; выберите папку с изображениями"
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str((folder / "results").resolve())))

    def launch(self, check=False):
        global _ACTIVE_WORKER
        if _ACTIVE_WORKER is not None:
            self.status.appendPlainText("Другая задача LocalOCR уже выполняется")
            return
        if self.worker is not None:
            return
        try:
            settings = self.runtime_settings()
            save_config(self.current_config())
        except (OSError, ValueError) as error:
            self.status.appendPlainText(
                write_error(error) if isinstance(error, OSError) else str(error)
            )
            return
        self.bar.setRange(0, 0)
        self.worker = Worker(self.folder.text(), settings, check)
        _ACTIVE_WORKER = self.worker
        from localocr.embedded import EmbeddedSettings

        if isinstance(settings, EmbeddedSettings):
            self.embedded_status.setText("Embedded: проверка runtime…")
            self.worker.runtime_status.connect(self.update_embedded_status)
        self.worker.network.connect(self.status.appendPlainText)
        self.worker.progress.connect(self.update_progress)
        self.worker.result.connect(self.completed)
        self.worker.error.connect(self.task_error)
        self.worker.finished.connect(self.finished)
        for control in self.controls():
            control.setEnabled(False)
        self.stop.setEnabled(True)
        self.worker.start()

    @Slot(str)
    def task_error(self, message):
        self.status.appendPlainText(message)
        self.show_status("Ошибка / отмена")

    @Slot(str)
    def update_embedded_status(self, message):
        self.embedded_status.setText(message)
        self.status.appendPlainText(message)
        self.show_status(message)

    def update_progress(self, done, total, message):
        self.bar.setRange(0, total + 1)
        self.bar.setValue(done)
        self.bar.setFormat(f"{done} / {total}")
        self.status.appendPlainText(message)
        self.show_status(f"{done}/{total}")

    def completed(self, result):
        if isinstance(result, str):
            self.status.appendPlainText(result)
        else:
            counts = {
                status: sum(r.status == status for r in result)
                for status in ["SUCCESS", "REVIEW", "FAILED", "SKIPPED"]
            }
            self.status.appendPlainText(
                f"Обработано файлов: {len(result)}\n"
                f"Успешно: {counts['SUCCESS']} · Требуют проверки (REVIEW): {counts['REVIEW']}\n"
                f"Ошибок: {counts['FAILED']} · Пропущено: {counts['SKIPPED']}\n"
                f"Каталог результатов: {Path(self.folder.text()) / 'results'}"
            )
            for item in result:
                if item.status in {"REVIEW", "FAILED"}:
                    self.status.appendPlainText(
                        f"{item.source}: {item.status}; предупреждений: {item.warnings}. {item.message}"
                    )
        if self.worker and not self.worker.cancel.is_set():
            self.bar.setRange(0, 1)
            self.bar.setValue(1)
            self.bar.setFormat("Завершено")
            self.show_status("Завершено")

    def finished(self):
        global _ACTIVE_WORKER
        _ACTIVE_WORKER = None
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        for control in self.controls():
            control.setEnabled(True)
        self.stop.setEnabled(False)
        if self.bar.maximum() == 0:
            self.bar.setRange(0, 1)
            self.bar.setValue(0)

    def cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.stop.setEnabled(False)
            self.status.appendPlainText("Остановка…")

    def closeEvent(self, event):
        if self.worker is not None:
            self.cancel()
            self.status.appendPlainText("Дождитесь завершения отмены перед закрытием")
            event.ignore()
        else:
            try:
                save_config(self.current_config())
            except OSError as error:
                self.status.appendPlainText(write_error(error))
                event.ignore()
                return
            event.accept()


class SimpleWindow(Window):
    """Compact view sharing the full window's worker and task lifecycle."""

    def __init__(self):
        super().__init__()
        old = self.takeCentralWidget()
        assert old is not None
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("Папка с изображениями:"))
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(self.browse)
        layout.addLayout(row)
        layout.addWidget(QLabel("Способ распознавания:"))
        self.modes = QButtonGroup(self)
        self.mode_buttons = {}
        row = QHBoxLayout()
        for mode, label in [
            ("server", "Сервер"),
            ("gpu", "GPU (локально)"),
            ("cpu", "CPU (локально)"),
        ]:
            button = QRadioButton(label)
            self.modes.addButton(button)
            self.mode_buttons[mode] = button
            row.addWidget(button)
            button.toggled.connect(self.mode_status)
        selected = (
            self.config.simple_mode if self.config.simple_mode in self.mode_buttons else "server"
        )
        self.mode_buttons[selected].setChecked(True)
        layout.addLayout(row)
        row = QHBoxLayout()
        for button in (self.check, self.start, self.stop):
            row.addWidget(button)
        layout.addLayout(row)
        for widget in (self.bar, self.status, self.open):
            layout.addWidget(widget)
        # Keep advanced controls alive, hidden, as the single configuration editor.
        old.setParent(central)
        old.hide()
        self.setCentralWidget(central)
        self.resize(760, 480)

    def mode(self):
        return next(
            (mode for mode, button in self.mode_buttons.items() if button.isChecked()), "server"
        )

    def mode_label(self):
        if not hasattr(self, "mode_buttons"):
            return "Сервер"
        return self.mode_buttons[self.mode()].text()

    def mode_status(self):
        self.show_status("Готово")

    def current_config(self):
        return replace(self.config, folder=self.folder.text(), simple_mode=self.mode())

    def runtime_settings(self):
        config = self.current_config()
        if self.mode() == "server":
            if not all(
                value.strip()
                for value in (config.openwebui_url, config.openwebui_model, config.api_token)
            ):
                from localocr.config import config_dir

                raise ValueError(
                    f"Укажите openwebui_url, openwebui_model и api_token в {config_dir() / 'config.json'} или в полном GUI (--full-gui)"
                )
            return replace(config, provider="openwebui", openwebui_api="proxy").settings()
        return replace(
            config, provider="embedded", precision="f16", embedded_device=self.mode()
        ).settings()

    def controls(self):
        return [*super().controls(), *self.mode_buttons.values()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-gui", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--expected-version")
    parser.add_argument("--expected-commit")
    args, qt_args = parser.parse_known_args()
    app = QApplication([sys.argv[0], *qt_args])
    try:
        setup_logging()
        window = Window() if args.full_gui else SimpleWindow()
        save_config(window.current_config())
    except OSError as error:
        QMessageBox.critical(None, "LocalOCR: каталог недоступен для записи", write_error(error))
        return 2
    window.show()
    if args.smoke_test:
        if args.expected_version and args.expected_version != __version__:
            return 2
        if args.expected_commit and args.expected_commit != build_commit():
            return 2
        QTimer.singleShot(300, window.close)
        QTimer.singleShot(500, app.quit)
    return app.exec()
