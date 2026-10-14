"""Per-user settings; never inside a frozen bundle."""

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppConfig:
    folder: str = ""
    ollama_url: str = "http://127.0.0.1:11434"


def config_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "LocalOCR"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "LocalOCR"


def load_config() -> AppConfig:
    try:
        data = json.loads((config_dir() / "config.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict) or any(not isinstance(v, str) for v in data.values()):
            return AppConfig()
        return AppConfig(
            folder=data.get("folder", ""),
            ollama_url=data.get("ollama_url", "http://127.0.0.1:11434"),
        )
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

    handler = RotatingFileHandler(
        directory / "localocr.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("localocr")
    if not logger.handlers:
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
