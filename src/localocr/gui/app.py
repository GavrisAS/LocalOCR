"""Responsive Qt window, shared service, cancellable worker threads."""

import sys
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from localocr import __version__
from localocr.config import AppConfig, load_config, save_config, setup_logging
from localocr.ollama import Cancelled, OllamaClient, Settings
from localocr.service import convert


class Worker(QThread):
    progress = Signal(int, int, str)
    result = Signal(object)
    error = Signal(str)

    def __init__(self, folder: str, url: str, check=False):
        super().__init__()
        self.folder, self.url, self.check = folder, url, check
        self.cancel = Event()

    def run(self):
        try:
            settings = Settings(url=self.url)
            if self.check:
                self.result.emit(OllamaClient(settings, self.cancel).doctor())
            else:
                self.result.emit(
                    convert(
                        Path(self.folder),
                        settings,
                        cancel=self.cancel,
                        progress=lambda a, b, c: self.progress.emit(a, b, c),
                    )
                )
        except Cancelled:
            self.error.emit("Операция отменена")
        except Exception as error:
            self.error.emit(str(error))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LocalOCR")
        self.resize(680, 440)
        self.worker: Worker | None = None
        config = load_config()
        self.folder = QLineEdit(config.folder)
        self.url = QLineEdit(config.ollama_url)
        self.browse = QPushButton("Обзор...")
        self.check = QPushButton("Проверить подключение")
        self.start = QPushButton("Начать обработку")
        self.stop = QPushButton("Остановить")
        self.stop.setEnabled(False)
        self.open = QPushButton("Открыть папку результатов")
        self.bar = QProgressBar()
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(QLabel("Папка с изображениями"))
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(self.browse)
        layout.addLayout(row)
        layout.addWidget(QLabel("Ollama API URL"))
        layout.addWidget(self.url)
        for button in [self.check, self.start, self.stop]:
            layout.addWidget(button)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addWidget(self.open)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"Версия {__version__}")
        self.browse.clicked.connect(self.choose)
        self.check.clicked.connect(lambda: self.launch(True))
        self.start.clicked.connect(lambda: self.launch(False))
        self.stop.clicked.connect(self.cancel)
        self.open.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(self.folder.text()) / "results"))
            )
        )

    def choose(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка с изображениями", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def launch(self, check=False):
        if self.worker is not None:
            return
        try:
            save_config(AppConfig(self.folder.text(), self.url.text()))
        except OSError as error:
            self.status.appendPlainText(f"Не удалось сохранить настройки: {error}")
        self.bar.setRange(0, 0)
        self.worker = Worker(self.folder.text(), self.url.text(), check)
        self.worker.progress.connect(self.update_progress)
        self.worker.result.connect(self.completed)
        self.worker.error.connect(self.status.appendPlainText)
        self.worker.finished.connect(self.finished)
        for control in [self.start, self.check, self.browse, self.folder, self.url]:
            control.setEnabled(False)
        self.stop.setEnabled(True)
        self.worker.start()

    def update_progress(self, done, total, message):
        self.bar.setRange(0, total + 1)
        self.bar.setValue(done)
        self.bar.setFormat(f"{done} / {total}")
        self.status.appendPlainText(message)

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

    def finished(self):
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        for control in [self.start, self.check, self.browse, self.folder, self.url]:
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
                save_config(AppConfig(self.folder.text(), self.url.text()))
            except OSError:
                self.status.appendPlainText("Не удалось сохранить настройки")
            event.accept()


def main():
    setup_logging()
    app = QApplication(sys.argv)
    window = Window()
    window.show()
    if "--smoke-test" in sys.argv:
        index = sys.argv.index("--expected-version") if "--expected-version" in sys.argv else -1
        if index >= 0 and sys.argv[index + 1] != __version__:
            return 2
        QTimer.singleShot(300, window.close)
        QTimer.singleShot(500, app.quit)
    return app.exec()
