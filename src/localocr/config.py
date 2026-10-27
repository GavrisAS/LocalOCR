"""Portable typed settings and rotating application log."""

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from localocr.runtime import portable_root


@dataclass
class AppConfig:
    folder: str = ""
    ollama_url: str = "http://127.0.0.1:11434"
    provider: str = "openwebui"
    ollama_model: str = "glm-ocr:latest"
    openwebui_url: str = ""
    openwebui_model: str = ""
    api_token: str = ""
    openwebui_api: str = "proxy"
    ssl_verify: bool = False
    trust_env: bool = False
    precision: str = "f16"
    embedded_device: str = "auto"
    simple_mode: str = "server"
    ollama_num_ctx: int = 32768
    ollama_num_predict: int = 16000
    ollama_table_stop: bool = True
    ocr_max_calls: int = 24
    ocr_max_image_seconds: float = 180.0
    embedded_max_image_seconds: float = 600.0
    fail_soft: bool = False

    def settings(self, timeout=300):
        from localocr.embedded import EmbeddedSettings
        from localocr.ollama import Settings
        from localocr.providers import OpenWebUISettings

        if self.provider == "embedded":
            return EmbeddedSettings(
                precision=self.precision,
                device_mode=self.embedded_device,
                timeout=timeout,
                max_calls=self.ocr_max_calls,
                max_image_seconds=self.embedded_max_image_seconds,
            )
        if self.provider == "openwebui":
            return OpenWebUISettings(
                url=self.openwebui_url,
                model=self.openwebui_model,
                api_token=self.api_token,
                api=self.openwebui_api,
                ssl_verify=self.ssl_verify,
                trust_env=self.trust_env,
                timeout=timeout,
                max_calls=self.ocr_max_calls,
                max_image_seconds=self.ocr_max_image_seconds,
            )
        if self.provider == "ollama":
            return Settings(
                url=self.ollama_url,
                model=self.ollama_model,
                timeout=timeout,
                num_ctx=self.ollama_num_ctx,
                num_predict=self.ollama_num_predict,
                table_stop=self.ollama_table_stop,
                max_calls=self.ocr_max_calls,
                max_image_seconds=self.ocr_max_image_seconds,
            )
        raise ValueError("Неизвестный provider")


def config_dir() -> Path:
    return portable_root()


def legacy_config() -> Path:
    if os.name == "nt":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            / "LocalOCR"
            / "config.json"
        )
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "LocalOCR"
        / "config.json"
    )


def load_config() -> AppConfig:
    try:
        path = config_dir() / "config.json"
        migrating = not path.exists()
        data = json.loads((legacy_config() if migrating else path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return AppConfig()
        from dataclasses import fields

        config = AppConfig(
            **{
                f.name: data[f.name]
                for f in fields(AppConfig)
                if f.name in data and type(data[f.name]) is type(f.default)
            }
        )
        if migrating:
            try:
                save_config(config)
            except OSError as error:
                logging.getLogger("localocr").warning(
                    "Legacy import could not save portable config: %s", type(error).__name__
                )
        return config
    except OSError, ValueError:
        return AppConfig()


def save_config(config: AppConfig):
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(asdict(config), stream, ensure_ascii=False)
        os.replace(name, directory / "config.json")
    finally:
        Path(name).unlink(missing_ok=True)


def setup_logging():
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    from logging.handlers import RotatingFileHandler

    logger = logging.getLogger("localocr")
    target = str((directory / "localocr.log").resolve())
    for existing in list(logger.handlers):
        if isinstance(existing, RotatingFileHandler):
            if existing.baseFilename == target:
                return
            logger.removeHandler(existing)
            existing.close()
    handler = RotatingFileHandler(
        directory / "localocr.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
