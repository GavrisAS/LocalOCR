import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_split_streaming_assembly(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    package = load("package_portable")
    archive = tmp_path / "portable.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("LocalOCR/embedded/models/f16/model.gguf", b"local fixture" * 500)
    parts = package.split(archive, tmp_path, limit=127)
    assert len(parts) > 2 and all(p["size"] <= 127 for p in parts)
    restored = b"".join((tmp_path / p["name"]).read_bytes() for p in parts)
    assert restored == archive.read_bytes()
    for part in parts:
        assert hashlib.sha256((tmp_path / part["name"]).read_bytes()).hexdigest() == part["sha256"]
    descriptor = {
        "schema": 1,
        "precision": "f16",
        "archive_size": archive.stat().st_size,
        "archive_sha256": hashlib.sha256(restored).hexdigest(),
        "parts": parts,
        "files": {
            "models/f16/model.gguf": {
                "size": 6500,
                "sha256": hashlib.sha256(b"local fixture" * 500).hexdigest(),
            }
        },
    }
    (tmp_path / "portable-manifest.json").write_text(json.dumps(descriptor))
    shutil.copyfile(SCRIPTS / "assemble_portable.ps1", tmp_path / "assemble_portable.ps1")
    if sys.platform == "win32":
        shell = shutil.which("pwsh") or "powershell"
        destination = tmp_path / "assembled"
        subprocess.run(
            [
                shell,
                "-NoProfile",
                "-File",
                str(tmp_path / "assemble_portable.ps1"),
                "-Destination",
                str(destination),
            ],
            check=True,
        )
        assert (
            destination / "LocalOCR/embedded/models/f16/model.gguf"
        ).read_bytes() == b"local fixture" * 500
        (tmp_path / parts[0]["name"]).write_bytes(b"corrupt")
        result = subprocess.run(
            [
                shell,
                "-NoProfile",
                "-File",
                str(tmp_path / "assemble_portable.ps1"),
                "-Destination",
                str(tmp_path / "bad"),
            ]
        )
        assert result.returncode != 0 and not (tmp_path / "bad").exists()


def test_packaging_requires_real_windows_qualification(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    package = load("package_portable")
    root = tmp_path / "root"
    (root / "embedded").mkdir(parents=True)
    (root / "embedded/manifest.json").write_text("{}")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"status": "PASS", "platform": "linux"}))
    with pytest.raises(ValueError, match="Windows F16"):
        package.package(root, tmp_path / "release", "v1.0", "a" * 40, evidence)
    assert not (tmp_path / "release").exists()


def test_manifest_release_rerun_exact_assets(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    release = load("release_manifest")
    verifier = load("verify_release")
    name = "LocalOCR-v1.0-windows-x64.zip"
    with zipfile.ZipFile(tmp_path / name, "w") as bundle:
        bundle.writestr("LocalOCR/LocalOCR.exe", b"synthetic")
        bundle.writestr("LocalOCR/LocalOCR-CLI/LocalOCR-CLI.exe", b"synthetic")
    digest = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
    (tmp_path / (name + ".sha256")).write_text(digest + "  " + name)
    (tmp_path / "part001").write_bytes(b"fixture part")
    release.write(tmp_path, "v1.0", "sha")
    metadata = {
        "tagName": "v1.0",
        "isPrerelease": True,
        "isDraft": False,
        "name": "LocalOCR v1.0 candidate",
        "assets": [
            {
                "name": p.name,
                "size": p.stat().st_size,
                "digest": "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in tmp_path.iterdir()
        ],
    }
    assert verifier.verify(metadata, tmp_path, "v1.0", "sha", "sha") == name
    assert verifier.verify(metadata, tmp_path, "v1.0", "sha", "sha") == name
    (tmp_path / "part001").write_bytes(b"modified")
    with pytest.raises(ValueError, match="digest"):
        verifier.verify(metadata, tmp_path, "v1.0", "sha", "sha")
