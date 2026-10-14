"""Verify immutable candidate assets; network operations only in CI tooling."""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path


def file_digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(metadata, folder: Path, tag: str, sha: str, resolved_sha: str):
    name = f"LocalOCR-{tag}-windows-x64.zip"
    if resolved_sha != sha or metadata["tagName"] != tag:
        raise ValueError("Tag/SHA mismatch")
    if not metadata["isPrerelease"] or metadata["isDraft"]:
        raise ValueError("Expected published prerelease")
    if metadata["name"] != f"LocalOCR {tag} candidate":
        raise ValueError("Release title mismatch")
    assets = {asset["name"]: asset for asset in metadata["assets"]}
    if "release-manifest.json" in assets:
        descriptor = json.loads((folder / "release-manifest.json").read_text(encoding="utf-8"))
        if descriptor.get("tag") != tag or descriptor.get("sha") != sha:
            raise ValueError("Manifest tag/SHA mismatch")
        expected = descriptor.get("assets", {})
        if not isinstance(expected, dict) or set(assets) != set(expected) | {
            "release-manifest.json"
        }:
            raise ValueError("Manifest asset set mismatch")
        if len(metadata["assets"]) != len(assets):
            raise ValueError("Duplicate assets")
        for filename, item in expected.items():
            if Path(filename).name != filename or "\\" in filename:
                raise ValueError("Unsafe asset path")
            path = folder / filename
            if (
                path.stat().st_size != item["size"]
                or file_digest(path) != item["sha256"]
                or path.stat().st_size >= 2 * 1024**3
            ):
                raise ValueError("Manifest asset size/digest mismatch")
        if name not in expected or name + ".sha256" not in expected:
            raise ValueError("Lite assets missing")
    elif len(metadata["assets"]) != 2 or set(assets) != {name, name + ".sha256"}:
        raise ValueError("Missing/unexpected/duplicate assets")
    for filename, asset in assets.items():
        path = folder / filename
        if not path.stat().st_size or asset["size"] != path.stat().st_size:
            raise ValueError("Asset size mismatch")
        digest = "sha256:" + file_digest(path)
        if asset.get("digest") != digest:
            raise ValueError("GitHub asset digest mismatch or absent")
    checksum = (folder / (name + ".sha256")).read_text("ascii").strip()
    match = re.fullmatch(r"([0-9a-f]{64})  " + re.escape(name), checksum)
    if not match or match[1] != file_digest(folder / name):
        raise ValueError("Malformed checksum or ZIP digest mismatch")
    with zipfile.ZipFile(folder / name) as archive:
        if archive.testzip() is not None:
            raise ValueError("Corrupt ZIP")
        for entry in archive.infolist():
            if ".." in Path(entry.filename).parts or Path(entry.filename).is_absolute():
                raise ValueError("Unsafe ZIP path")
        required = {"LocalOCR/LocalOCR.exe", "LocalOCR/LocalOCR-CLI/LocalOCR-CLI.exe"}
        if not required.issubset(archive.namelist()):
            raise ValueError("Frozen binaries missing")
    return name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--require-existing", action="store_true")
    args = parser.parse_args()
    # Distinguish an absent release from authentication/network errors.
    releases = json.loads(
        subprocess.check_output(
            ["gh", "api", "--paginate", "--slurp", "repos/{owner}/{repo}/releases"],
            text=True,
            encoding="utf-8",
        )
    )
    found = [release for page in releases for release in page if release["tag_name"] == args.tag]
    if not found:
        if args.require_existing:
            raise ValueError("Release missing on rerun; historical release must not be recreated")
        raise SystemExit(3)  # caller may create only an absent release
    metadata = json.loads(
        subprocess.check_output(
            [
                "gh",
                "release",
                "view",
                args.tag,
                "--json",
                "tagName,isPrerelease,isDraft,name,assets",
            ],
            text=True,
            encoding="utf-8",
        )
    )
    remote = json.loads(
        subprocess.check_output(
            ["gh", "api", "repos/{owner}/{repo}/git/ref/tags/" + args.tag],
            text=True,
            encoding="utf-8",
        )
    )["object"]
    while remote["type"] == "tag":
        remote = json.loads(
            subprocess.check_output(
                ["gh", "api", "repos/{owner}/{repo}/git/tags/" + remote["sha"]],
                text=True,
                encoding="utf-8",
            )
        )["object"]
    if remote["type"] != "commit" or remote["sha"] != args.sha:
        raise ValueError("Remote tag SHA mismatch")
    sha = subprocess.check_output(
        ["git", "rev-list", "-n", "1", args.tag], text=True, encoding="utf-8"
    ).strip()
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        subprocess.run(["gh", "release", "download", args.tag, "--dir", str(folder)], check=True)
        name = verify(metadata, folder, args.tag, args.sha, sha)
        with zipfile.ZipFile(folder / name) as archive:
            archive.extractall(folder / "extracted")
        exe = folder / "extracted/LocalOCR/LocalOCR-CLI/LocalOCR-CLI.exe"
        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "scripts/frozen_smoke.py",
                "--exe",
                str(exe),
                "--version",
                args.tag[1:],
                "--commit",
                args.sha,
            ],
            check=True,
        )
        subprocess.run(
            [
                str(folder / "extracted/LocalOCR/LocalOCR.exe"),
                "--smoke-test",
                "--expected-version",
                args.tag[1:],
                "--expected-commit",
                args.sha,
            ],
            check=True,
            timeout=30,
        )
        if (folder / "portable-manifest.json").is_file():
            descriptor = json.loads((folder / "portable-manifest.json").read_text())
            if descriptor.get("tag") != args.tag or descriptor.get("sha") != args.sha:
                raise ValueError("Portable identity mismatch")
            destination = folder / "assembled"
            subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    str(folder / "assemble_portable.ps1"),
                    "-Destination",
                    str(destination),
                ],
                check=True,
            )
            subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-File",
                    "scripts/qualify_windows.ps1",
                    "-Root",
                    str(destination / "LocalOCR"),
                    "-Output",
                    str(folder / "published-qualification.json"),
                    "-Sha",
                    args.sha,
                ],
                check=True,
            )
    print("Immutable existing release verified: PASS")


if __name__ == "__main__":
    main()
