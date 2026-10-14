"""Local version identity; frozen builds never invoke Git."""

import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def source_version(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "tag", "--points-at", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=5,
        )
        tags = [
            tag[1:]
            for tag in result.stdout.splitlines()
            if re.fullmatch(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", tag)
        ]
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=5,
        ).stdout
        return tags[0] if len(tags) == 1 and not dirty else "development (untagged/modified)"
    except OSError, subprocess.SubprocessError:
        return "development (unknown)"


def runtime_version() -> str:
    if getattr(sys, "frozen", False):
        try:
            from localocr._build_version import BUILD_VERSION  # ty: ignore[unresolved-import]

            return BUILD_VERSION
        except ImportError:
            return "development (missing build identity)"
    root = Path(__file__).resolve().parents[2]
    if (root / ".git").exists():
        return source_version(root)
    try:
        identity = version("localocr")
        return identity if re.fullmatch(r"\d+\.\d+", identity) else "development (" + identity + ")"
    except PackageNotFoundError:
        return "development (unknown)"


__version__ = runtime_version()


def build_commit() -> str:
    if getattr(sys, "frozen", False):
        try:
            from localocr._build_version import BUILD_COMMIT  # ty: ignore[unresolved-import]

            return BUILD_COMMIT
        except ImportError:
            return "unknown"
    return "development"
