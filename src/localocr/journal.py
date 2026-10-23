"""Durable private batch journal and exclusive single-writer output ownership."""

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from localocr.domain import PIPELINE_VERSION
from localocr.runtime import portable_root


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path: Path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".localocr-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def settings_identity(settings, client) -> dict:
    values = asdict(settings)
    values.pop("api_token", None)
    # GUI defaults can be ints while Typer returns floats. Equivalent timeout
    # values must produce the same cache identity across the shared service.
    for name in ("timeout", "startup_timeout", "max_image_seconds"):
        if name in values:
            values[name] = float(values[name])
    identity = dict(getattr(client, "model_identity", {}))
    if not identity.get("digest") and type(settings).__name__ == "EmbeddedSettings":
        # Embedded resolves default model paths during doctor(). Qualify the
        # actual loaded files, never the advertised precision alone.
        engine, model, projector = settings.paths()
        candidate = getattr(client, "active_candidate", None)
        actual_engine = getattr(candidate, "engine", engine)
        identity["active_backend"] = getattr(candidate, "backend", None)
        for name, path in (
            ("engine", actual_engine),
            ("model_path", model),
            ("mmproj_path", projector),
        ):
            if Path(path).is_file():
                identity[name] = file_hash(Path(path))
        if all(name in identity for name in ("engine", "model_path", "mmproj_path")):
            identity["digest"] = hashlib.sha256(
                json.dumps(identity, sort_keys=True).encode()
            ).hexdigest()
    return {
        "settings": values,
        "model": identity,
        "pipeline": PIPELINE_VERSION,
        "backend": type(client).__name__,
    }


class Journal:
    def __init__(self, directory: Path):
        self.path = directory / "jobs.jsonl"
        lock_key = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
        self.lock_path = portable_root() / "work" / "journal-locks" / (lock_key + ".lock")
        self.records: dict[str, dict] = {}

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = self.lock_path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.lock.seek(0)
                if not self.lock.read(1):
                    self.lock.write(b"0")
                    self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.lock.close()
            raise ValueError("Каталог результатов занят другим batch") from error
        try:
            if self.path.exists():
                # A power loss can truncate the last append. Other records remain
                # usable, but no incomplete entry is ever a cache hit.
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    try:
                        entry = json.loads(line)
                        if isinstance(entry, dict) and isinstance(entry.get("key"), str):
                            self.records[entry["key"]] = entry
                    except ValueError:
                        continue
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if os.name == "nt":
            import msvcrt

            self.lock.seek(0)
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_UNLCK, 1)
        self.lock.close()

    def append(self, entry):
        with self.path.open("ab") as stream:
            # Leading newline also isolates a torn final record on recovery.
            stream.write(
                b"\n" + json.dumps(entry, ensure_ascii=False, default=str).encode() + b"\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        self.records[entry["key"]] = entry

    def key(self, source: Path, identity: dict):
        fingerprint = {
            "source_path": str(source.resolve()),
            "source_hash": file_hash(source),
            "identity": identity,
            "settings_hash": hashlib.sha256(
                json.dumps(identity["settings"], sort_keys=True, default=str).encode()
            ).hexdigest(),
        }
        key = hashlib.sha256(
            json.dumps(fingerprint, sort_keys=True, default=str).encode()
        ).hexdigest()
        return key, fingerprint

    def completed(self, key, target: Path):
        entry = self.records.get(key, {})
        if entry.get("status") not in {"SUCCESS", "REVIEW", "PARTIAL"}:
            return None
        if entry.get("output") != str(target.resolve()) or not target.is_file():
            return None
        return entry if entry.get("output_hash") == file_hash(target) else None
