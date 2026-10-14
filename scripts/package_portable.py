"""Build split ZIP and release manifest; Portable needs real Windows qualification."""

import argparse
import json
import shutil
import zipfile
from pathlib import Path

from prepare_embedded import digest

LIMIT = 1900 * 1024 * 1024  # strictly below GitHub's 2 GiB per asset


def split(source: Path, output: Path, limit=LIMIT):
    parts = []
    with source.open("rb") as stream:
        index = 1
        while True:
            first = stream.read(min(1024 * 1024, limit))
            if not first:
                break
            path = output / f"{source.name}.part{index:03}"
            with path.open("wb") as out:
                out.write(first)
                remaining = limit - len(first)
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            parts.append({"name": path.name, "size": path.stat().st_size, "sha256": digest(path)})
            index += 1
    return parts


def package(root: Path, output: Path, tag: str, sha: str, evidence: Path):
    qualification = json.loads(evidence.read_text(encoding="utf-8"))
    manifest = json.loads((root / "embedded/manifest.json").read_text())
    if (
        qualification.get("status") != "PASS"
        or qualification.get("platform") != "win32"
        or qualification.get("precision") != "f16"
        or qualification.get("build_commit") != sha
        or qualification.get("manifest_sha256") != digest(root / "embedded/manifest.json")
    ):
        raise ValueError("Windows F16 qualification required for this exact bundle/SHA")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"LocalOCR-{tag}-portable-f16.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
        for file in sorted(root.rglob("*")):
            if file.is_file():
                bundle.write(file, Path("LocalOCR") / file.relative_to(root))
    parts = split(archive, output)
    descriptor = {
        "schema": 1,
        "tag": tag,
        "sha": sha,
        "precision": "f16",
        "archive_sha256": digest(archive),
        "archive_size": archive.stat().st_size,
        "parts": parts,
        "files": manifest["files"],
        "upstream": manifest["upstream"],
        "qualification": qualification,
    }
    (output / "portable-manifest.json").write_text(
        json.dumps(descriptor, indent=2), encoding="utf-8"
    )
    shutil.copyfile(
        Path(__file__).with_name("assemble_portable.ps1"), output / "assemble_portable.ps1"
    )
    archive.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    package(args.root, args.output, args.tag, args.sha, args.evidence)
