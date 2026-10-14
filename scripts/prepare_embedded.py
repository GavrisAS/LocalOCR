"""Build-time only: download pinned engine/weights and verify before installation."""

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(item, target: Path):
    if target.is_file() and digest(target) == item["sha256"]:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".download")
    try:
        with (
            urllib.request.urlopen(item["url"], timeout=120) as response,
            temporary.open("wb") as out,
        ):
            shutil.copyfileobj(response, out, 1024 * 1024)
        if temporary.stat().st_size != item["size"] or digest(temporary) != item["sha256"]:
            raise ValueError("Upstream size/SHA256 mismatch")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(root: Path, precision: str):
    lock = json.loads(Path(__file__).with_name("embedded-lock.json").read_text())
    root.mkdir(parents=True, exist_ok=True)
    for kind, item in lock["models"][precision].items():
        download(item, root / "models" / precision / (kind + ".gguf"))
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "engine.zip"
        download(lock["engine"], archive)
        with zipfile.ZipFile(archive) as bundle:
            # Keep the complete standalone DLL set, flatten the official bin directory.
            for info in bundle.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).name
                if name.endswith((".exe", ".dll")) or "LICENSE" in name.upper():
                    target = root / "engine" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        raise ValueError("Duplicate engine member")
                    with bundle.open(info) as source, target.open("wb") as out:
                        shutil.copyfileobj(source, out, 1024 * 1024)
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            files[path.relative_to(root).as_posix()] = {
                "size": path.stat().st_size,
                "sha256": digest(path),
            }
    manifest = {"upstream": lock, "precision": precision, "files": files}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--precision", choices=["f16", "q8_0"], default="f16")
    args = parser.parse_args()
    prepare(args.output, args.precision)
