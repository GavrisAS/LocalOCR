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
        bundle.writestr("LocalOCR/START_HERE_RU.md", b"synthetic instructions")
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


def test_standalone_engine_collects_frozen_cpp_runtime(tmp_path):
    prepare = load("prepare_embedded")
    root = tmp_path / "LocalOCR/embedded"
    (root / "engine").mkdir(parents=True)
    gui = root.parent / "_internal/PySide6"
    gui.mkdir(parents=True)
    for name in ["MSVCP140.dll", "MSVCP140_1.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll"]:
        (gui / name).write_bytes(name.encode())
    prepare.collect_runtime_dlls(root)
    assert (root / "engine/MSVCP140.DLL").read_bytes() == b"MSVCP140.dll"
    assert (root / "engine/VCRUNTIME140_1.DLL").read_bytes() == b"VCRUNTIME140_1.dll"


def test_renamed_numpy_runtime_does_not_satisfy_engine(tmp_path):
    prepare = load("prepare_embedded")
    root = tmp_path / "embedded"
    (root / "engine").mkdir(parents=True)
    numpy = root.parent / "_internal/numpy.libs"
    numpy.mkdir(parents=True)
    (numpy / "msvcp140-renamed.dll").write_bytes(b"fixture")
    with pytest.raises(ValueError, match=r"C\+\+ runtime"):
        prepare.collect_runtime_dlls(root)


BATCH_TRACE = """[00:00:00] Embedded F16 · CPU · CPU · выбран CPU · model load=1.500s
[0/2] small.png
[00:00:01] Embedded recognize latency=2.000s
[1/2] small.png: SUCCESS
[1/2] large.png
[00:00:03] Embedded recognize latency=3.000s
[00:00:06] Embedded recognize latency=4.000s
[2/2] large.png: SUCCESS
"""


def test_frozen_batch_timings_separate_startup_and_each_image(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    module = load("qualify_embedded")
    result = module.frozen_batch_metadata(BATCH_TRACE, ["small.png", "large.png"])
    assert result["shared_engine"] and result["startup_seconds"] == 1.5
    assert result["cases"]["small.png"]["ocr_request_seconds"] == [2.0]
    assert result["cases"]["large.png"]["ocr_request_seconds"] == [3.0, 4.0]


def test_embedded_qualification_reads_raw_observations_sidecar(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    module = load("qualify_embedded")
    sidecar = tmp_path / "observations.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tables": [
                    {
                        "rows": 2,
                        "columns": 2,
                        "cells": [
                            {"row": 0, "column": 0, "text": "0012"},
                            {"row": 0, "column": 1, "text": "5,50"},
                            {"row": 1, "column": 0, "text": ""},
                            {"row": 1, "column": 1, "text": "R2"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert module.observation_texts(sidecar, 2, 2) == [
        ["0012", "5,50"],
        ["", "R2"],
    ]
    with pytest.raises(ValueError, match="dimensions"):
        module.observation_texts(sidecar, 3, 2)


@pytest.mark.parametrize(
    "trace",
    [
        BATCH_TRACE + "Embedded F16 · CPU · CPU · model load=2.000s\n",
        BATCH_TRACE.replace("Embedded recognize latency=2.000s", "no latency"),
        BATCH_TRACE.replace("small.png: SUCCESS", "other.png: SUCCESS"),
    ],
)
def test_frozen_batch_rejects_restart_or_missing_evidence(monkeypatch, trace):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    with pytest.raises(ValueError):
        load("qualify_embedded").frozen_batch_metadata(trace, ["small.png", "large.png"])


@pytest.mark.parametrize(
    "error,always_fail,expected_calls",
    [
        ("ENGINE_STARTUP_TIMEOUT: observed deadline", False, 2),
        ("ENGINE_STARTUP_TIMEOUT: observed deadline", True, 2),
        ("Synthetic gold differs", True, 1),
    ],
)
def test_qualification_retry_is_bounded_and_retains_failure(
    tmp_path, monkeypatch, error, always_fail, expected_calls
):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    module = load("qualify_embedded")
    output = tmp_path / "qualification.json"
    calls = []

    def attempt(*args):
        calls.append(args)
        if len(calls) == 1 or always_fail:
            output.write_text(json.dumps({"status": "FAIL", "error": error}))
            raise ValueError(error)
        output.write_text(json.dumps({"status": "PASS", "cases": [3, 30]}))

    monkeypatch.setattr(module, "qualify_once", attempt)
    if always_fail:
        with pytest.raises(ValueError, match=error.split(":")[0]):
            module.qualify(tmp_path, output, "sha", True)
    else:
        module.qualify(tmp_path, output, "sha", True)
    report = json.loads(output.read_text())
    assert len(calls) == expected_calls and report["qualification_attempts"] == expected_calls
    assert len(report["prior_startup_failures"]) == expected_calls - 1
    if expected_calls == 2:
        assert report["prior_startup_failures"][0]["error"] == error
    assert report["status"] == ("FAIL" if always_fail else "PASS")
