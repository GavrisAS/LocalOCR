"""One application-owned root, independent of CWD and bundle internals."""

import sys
from pathlib import Path

# Explicit injection for tests; production never reads an environment override.
ROOT_OVERRIDE: Path | None = None


def portable_root() -> Path:
    if ROOT_OVERRIDE is not None:
        return ROOT_OVERRIDE
    if getattr(sys, "frozen", False):
        directory = Path(sys.executable).resolve().parent
        return directory.parent if directory.name.casefold() == "localocr-cli" else directory
    return Path(__file__).resolve().parents[2]


def write_error(error: OSError) -> str:
    return (
        f"Не удалось записать файлы LocalOCR в {portable_root()}: {error}. "
        "Переместите всю папку Portable в доступное для записи место (вне Program Files)."
    )
