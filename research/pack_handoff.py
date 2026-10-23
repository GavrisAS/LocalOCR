"""Allowlisted sanitized Stage 1 evidence and exact committed source snapshot."""

import argparse
import hashlib
import io
import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

NAMES = [
    "baseline-final-hidden-summary.json",
    "paddle-final-hidden-summary.json",
    "regional-final-hidden-summary.json",
    "baseline-final-hidden-geometry.json",
    "paddle-final-hidden-geometry.json",
    "freeze-audit.json",
    "synthetic-summary.json",
    "regional-summary.json",
    "paddle-eight-summary.json",
    "baseline-new-summary.json",
    "paddle-new-summary.json",
    "regional-new-summary.json",
    "real-summary.json",
    "regional-real-summary.json",
    "paddle-real-summary.json",
    "baseline-new-geometry.json",
    "baseline-eight-geometry.json",
    "source-audit.json",
    "paddle-new-geometry.json",
    "paddle-eight-geometry.json",
    "model-manifest.json",
    "research-requirements.txt",
    "regression.xml",
    "resources.json",
    "glm-identity.json",
    "gates.json",
    "checks.json",
]


def digest(content):
    return hashlib.sha256(content).hexdigest()


def check_source(content):
    with ZipFile(io.BytesIO(content)) as source:
        assert source.testzip() is None, "Source CRC failure"
        for name in source.namelist():
            path = Path(name)
            if (
                path.parts[0]
                in {"data", ".evidence", "outputs", "results", "diagnostics", "embedded", ".venv"}
                or path.suffix.lower()
                in {
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".tif",
                    ".tiff",
                    ".webp",
                    ".bmp",
                    ".xlsx",
                    ".gguf",
                    ".zip",
                    ".log",
                    ".pdf",
                    ".docx",
                }
                or path.name == "config.json"
            ):
                raise ValueError("Forbidden source member")
        assert "uv.lock" in source.namelist()


def scan_json(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {
                "text",
                "response",
                "raw",
                "token",
                "api_key",
                "authorization",
                "input_path",
                "source_hash",
                "source_sha256",
                "private_image",
            }:
                raise ValueError("Private evidence field")
            scan_json(item)
    elif isinstance(value, list):
        for item in value:
            scan_json(item)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.resolve().relative_to(Path(".evidence").resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    if subprocess.check_output(["git", "status", "--porcelain"]).strip():
        raise ValueError("Commit reviewed source first")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    source = subprocess.check_output(["git", "archive", "--format=zip", "HEAD"])
    check_source(source)
    (args.output / "source.zip").write_bytes(source)
    (args.output / "REPORT.md").write_bytes(Path("REPORT.md").read_bytes())
    public = Path(".evidence/layout-pilot-20261023/public")
    for name in NAMES:
        content = (public / name).read_bytes()
        if name.endswith(".json"):
            scan_json(json.loads(content))
        (args.output / name).write_bytes(content)
    files = sorted(args.output.iterdir())
    manifest = {
        "source_sha": sha,
        "baseline_source_sha": "cbc71f1feb7679ab62faf6d935d8167c71648e9d",
        "verdict": "NO_GO",
        "contains_private_ocr": False,
        "files": [
            {"name": p.name, "bytes": p.stat().st_size, "sha256": digest(p.read_bytes())}
            for p in files
        ],
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    files.append(args.output / "manifest.json")
    archive = args.output / "LocalOCR-layout-pilot-handoff.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
        for p in files:
            output.write(p, p.name)
    with ZipFile(archive) as output:
        assert output.testzip() is None, "Handoff CRC failure"
        check_source(output.read("source.zip"))
        for item in manifest["files"]:
            assert digest(output.read(item["name"])) == item["sha256"], "Member hash mismatch"
    checksum = digest(archive.read_bytes())
    (args.output / (archive.name + ".sha256")).write_text(f"{checksum}  {archive.name}\n")
    if archive.stat().st_size > 100_000_000:
        with archive.open("rb") as stream:
            number = 1
            while block := stream.read(100_000_000):
                (args.output / f"{archive.name}.part{number:03d}").write_bytes(block)
                number += 1
        (args.output / "JOIN.txt").write_text(
            "cat LocalOCR-layout-pilot-handoff.zip.part* > restored.zip\nsha256sum restored.zip\nCompare against checksum file.\n"
        )
    (args.output / "SHA256SUMS").write_text(
        "".join(
            f"{digest(p.read_bytes())}  {p.name}\n"
            for p in sorted(args.output.iterdir())
            if p.name != "SHA256SUMS"
        )
    )
    print(
        json.dumps(
            {
                "source_sha": sha,
                "bytes": archive.stat().st_size,
                "sha256": checksum,
                "crc": "PASS",
                "members_sha256": "PASS",
            }
        )
    )


if __name__ == "__main__":
    main()
