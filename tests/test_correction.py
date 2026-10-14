import hashlib
import subprocess
import zipfile
from pathlib import Path

import pytest

from localocr import source_version
from localocr.quality import compare, template


def test_tagged_untagged_rerun(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True)

    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("commit", "--allow-empty", "-m", "initial")
    assert source_version(tmp_path).startswith("development")
    git("tag", "v0.5")
    assert source_version(tmp_path) == source_version(tmp_path) == "0.5"
    git("commit", "--allow-empty", "-m", "next")
    assert source_version(tmp_path).startswith("development")


def test_geometry_success_does_not_prove_text():
    gold = template(1, 1)
    assert compare({}, gold)["status"] == "QUALITY_PENDING"
    gold["human_verified"] = True
    gold["tables"][0]["cells"][0].update(text="correct", spans=[1, 1], type="text")
    actual = dict(
        tables=[
            dict(
                rows=1,
                columns=1,
                cells=[
                    dict(row=1, column=1, spans=[1, 1], text="wrong", value="wrong", review=False)
                ],
            )
        ],
        review_count=0,
    )
    result = compare(actual, gold)
    assert result["counts"]["unflagged_mismatches"] == 1
    assert result["counts"].get("shape_mismatches", 0) == 0


def test_release_contract(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "verify_release", Path("scripts/verify_release.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    name = "LocalOCR-v0.5-windows-x64.zip"
    with zipfile.ZipFile(tmp_path / name, "w") as archive:
        archive.writestr("LocalOCR/LocalOCR.exe", b"synthetic")
        archive.writestr("LocalOCR/LocalOCR-CLI/LocalOCR-CLI.exe", b"synthetic")
    digest = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
    (tmp_path / (name + ".sha256")).write_text(digest + "  " + name + "\n")
    assets = [
        dict(
            name=p.name,
            size=p.stat().st_size,
            digest="sha256:" + hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in tmp_path.iterdir()
    ]
    metadata = dict(
        tagName="v0.5",
        isPrerelease=True,
        isDraft=False,
        name="LocalOCR v0.5 candidate",
        assets=assets,
    )
    assert module.verify(metadata, tmp_path, "v0.5", "sha", "sha") == name
    assert module.verify(metadata, tmp_path, "v0.5", "sha", "sha") == name
    with pytest.raises(ValueError, match="SHA"):
        module.verify(metadata, tmp_path, "v0.5", "sha", "other")
    assets[0]["digest"] = "sha256:wrong"
    with pytest.raises(ValueError, match="digest"):
        module.verify(metadata, tmp_path, "v0.5", "sha", "sha")


def test_built_and_installed_metadata(tmp_path):
    import email
    import shutil

    root = tmp_path / "repository"
    root.mkdir()
    shutil.copy("pyproject.toml", root)
    shutil.copytree(
        "src",
        root / "src",
        ignore=shutil.ignore_patterns("__pycache__", "_build_version.py", "_package_version.py"),
    )

    def run(*args):
        return subprocess.check_output(args, cwd=root, text=True, stderr=subprocess.STDOUT)

    run("git", "init")
    run("git", "config", "user.email", "test@example.invalid")
    run("git", "config", "user.name", "Test")
    run("git", "add", ".")
    run("git", "commit", "-m", "fixture")
    run("git", "tag", "v0.5")
    run("uv", "build", "--out-dir", str(tmp_path / "tagged"))
    wheels = list((tmp_path / "tagged").glob("*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        metadata = email.message_from_bytes(archive.read("localocr-0.5.dist-info/METADATA"))
        assert metadata["Version"] == "0.5"
    environment = tmp_path / "installed"
    run("uv", "venv", str(environment), "--python", "3.14")
    python = environment / ("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
    run("uv", "pip", "install", "--python", str(python), "--no-deps", str(wheels[0]))
    output = run(
        str(python),
        "-c",
        "import localocr; from importlib.metadata import version; "
        'print(localocr.__version__); print(version("localocr"))',
    )
    assert output.splitlines() == ["0.5", "0.5"]
    run("git", "commit", "--allow-empty", "-m", "untagged")
    run("uv", "build", "--out-dir", str(tmp_path / "untagged"))
    wheel = next((tmp_path / "untagged").glob("*.whl"))
    assert wheel.name != wheels[0].name and "+g" in wheel.name


@pytest.mark.parametrize(
    "case", ["missing", "size", "draft", "prerelease", "tag", "checksum", "checksum_digest", "zip"]
)
def test_release_rejections(tmp_path, case):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "verify_release", Path("scripts/verify_release.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    name = "LocalOCR-v0.5-windows-x64.zip"
    with zipfile.ZipFile(tmp_path / name, "w") as archive:
        archive.writestr("LocalOCR/LocalOCR.exe", b"synthetic")
        if case != "zip":
            archive.writestr("LocalOCR/LocalOCR-CLI/LocalOCR-CLI.exe", b"synthetic")
    digest = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
    checksum = digest + "  " + name
    if case == "checksum":
        checksum = "malformed"
    elif case == "checksum_digest":
        checksum = "0" * 64 + "  " + name
    (tmp_path / (name + ".sha256")).write_text(checksum)
    assets = [
        dict(
            name=p.name,
            size=p.stat().st_size,
            digest="sha256:" + hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in tmp_path.iterdir()
    ]
    metadata = dict(
        tagName="v0.5",
        isPrerelease=True,
        isDraft=False,
        name="LocalOCR v0.5 candidate",
        assets=assets,
    )
    if case == "missing":
        metadata["assets"] = assets[:1]
    if case == "size":
        assets[0]["size"] = int(assets[0]["size"]) + 1
    if case == "draft":
        metadata["isDraft"] = True
    if case == "prerelease":
        metadata["isPrerelease"] = False
    if case == "tag":
        metadata["tagName"] = "v0.4"
    with pytest.raises(ValueError):
        module.verify(metadata, tmp_path, "v0.5", "sha", "sha")


def test_frozen_identity_never_invokes_git(monkeypatch):
    import sys
    import types

    import localocr

    def prohibited(*args, **kwargs):
        raise AssertionError("Frozen runtime invoked Git")

    monkeypatch.setattr(subprocess, "run", prohibited)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    module = types.ModuleType("localocr._build_version")
    setattr(module, "BUILD_VERSION", "0.5")
    setattr(module, "BUILD_COMMIT", "sha")
    monkeypatch.setitem(sys.modules, "localocr._build_version", module)
    assert localocr.runtime_version() == "0.5"
    assert localocr.build_commit() == "sha"


def test_technical_success_with_wrong_ocr(server, tmp_path):
    from PIL import Image, ImageDraw

    from localocr.ollama import Settings
    from localocr.quality import export
    from localocr.service import convert

    image = Image.new("RGB", (220, 220), "white")
    draw = ImageDraw.Draw(image)
    for offset in (10, 110, 210):
        draw.line((10, offset, 210, offset), fill="black", width=2)
        draw.line((offset, 10, offset, 210), fill="black", width=2)
    path = tmp_path / "synthetic.png"
    image.save(path)
    result = convert(path, Settings(url=server[0]))[0]
    assert result.status == "SUCCESS"
    assert result.output is not None
    actual = export(Path(result.output))
    gold = template(2, 2)
    gold["human_verified"] = True
    for cell in gold["tables"][0]["cells"]:
        cell.update(text="independent synthetic gold", spans=[1, 1], type="s")
    summary = compare(actual, gold)
    assert summary["counts"]["text_mismatches"] == 4
    assert summary["counts"]["unflagged_mismatches"] == 4


@pytest.mark.parametrize("network_error", [False, True])
def test_release_unicode_absence_vs_network(tmp_path, monkeypatch, network_error):
    import importlib.util
    import json
    import sys

    spec = importlib.util.spec_from_file_location(
        "verify_release", Path("scripts/verify_release.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = json.dumps(
        [[dict(tag_name="v0.4", body="Синтетическая проверка")]], ensure_ascii=False
    ).encode("utf-8")

    def api(command, **kwargs):
        assert kwargs.get("encoding") == "utf-8"
        if network_error:
            raise subprocess.CalledProcessError(1, command)
        # Reproduce Windows cp1252 when encoding is omitted, independently of host locale.
        return payload.decode(kwargs.get("encoding", "cp1252"))

    monkeypatch.setattr(subprocess, "check_output", api)
    monkeypatch.setattr(sys, "argv", ["verify_release", "--tag", "v0.7", "--sha", "sha"])
    if network_error:
        with pytest.raises(subprocess.CalledProcessError):
            module.main()
    else:
        with pytest.raises(SystemExit) as result:
            module.main()
        assert result.value.code == 3


def test_release_missing_rerun_fails(monkeypatch):
    import runpy
    import sys

    module = runpy.run_path("scripts/verify_release.py")

    def absent(command, **kwargs):
        assert kwargs["encoding"] == "utf-8"
        return "[[]]"

    monkeypatch.setattr(subprocess, "check_output", absent)
    monkeypatch.setattr(
        sys, "argv", ["verify_release", "--tag", "v0.8", "--sha", "sha", "--require-existing"]
    )
    with pytest.raises(ValueError, match="missing on rerun"):
        module["main"]()
