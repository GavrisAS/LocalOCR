"""Allowlisted portable evidence; excludes all sensitive local OCR artifacts."""

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile


def hybrid(output: Path):
    root = Path.cwd()
    if any(output.iterdir()):
        raise ValueError("Choose a new empty handoff output directory")
    if subprocess.check_output(["git", "status", "--porcelain"]).strip():
        raise ValueError("Commit the reviewed source/docs first; handoff must identify exact HEAD")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    source = output / "source.zip"
    subprocess.run(["git", "archive", "--format=zip", "-o", str(source), "HEAD"], check=True)
    with ZipFile(source) as archive:
        forbidden = {
            ".png",
            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
            ".bmp",
            ".webp",
            ".xlsx",
            ".gguf",
            ".log",
            ".zip",
            ".gz",
        }
        for name in archive.namelist():
            path = Path(name)
            if (
                path.suffix.lower() in forbidden
                or path.parts[0] in {"data", "results", "diagnostics", "embedded", ".evidence"}
                or name == "config.json"
            ):
                raise ValueError("Sensitive/non-source path in source archive")
        if archive.testzip() is not None:
            raise ValueError("Source archive CRC failure")
    names = (
        "regression.xml",
        "checks.txt",
        "qualification.json",
        "benchmark.json",
        "holdout.json",
        "model-manifest.json",
        "software.json",
        "published-ci.json",
        "replay.json",
    )
    for name in names:
        shutil.copyfile(root / ".evidence/hybrid/public" / name, output / name)
    shutil.copyfile(root / "REPORT.md", output / "REPORT.md")
    members = sorted(p for p in output.iterdir() if p.is_file())
    manifest = {
        "source_sha": revision,
        "contains_private_ocr": False,
        "files": [
            {
                "name": p.name,
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in members
        ],
    }
    import json

    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    members.append(output / "manifest.json")
    target = output / "LocalOCR-handoff.zip"
    from zipfile import ZIP_DEFLATED

    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for path in members:
            archive.write(path, path.name)
    with ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError("Handoff archive CRC failure")
        for item in manifest["files"]:
            if hashlib.sha256(archive.read(str(item["name"]))).hexdigest() != item["sha256"]:
                raise ValueError("Handoff member SHA256 failure")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (output / "LocalOCR-handoff.zip.sha256").write_text(f"{digest}  {target.name}\n")
    if target.stat().st_size > 100_000_000:
        with target.open("rb") as stream:
            part = 1
            while block := stream.read(100_000_000):
                (output / f"{target.name}.part{part:03d}").write_bytes(block)
                part += 1
        (output / "JOIN.txt").write_text(
            "cat LocalOCR-handoff.zip.part* > restored.zip\nsha256sum restored.zip\nCompare with LocalOCR-handoff.zip.sha256\n"
        )
    files = sorted(p for p in output.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text(
        "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in files)
    )
    print(
        json.dumps(
            {
                "source_sha": revision,
                "archive": str(target),
                "sha256": digest,
                "bytes": target.stat().st_size,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--providers", action="store_true")
    parser.add_argument("--hybrid", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.hybrid:
        hybrid(args.output.resolve())
        return
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(args.output / "source.zip"), "HEAD"],
        check=True,
    )
    if args.providers:
        for name in (
            "CORRECTIVE_AUDIT.md",
            "PROVIDER_PLAN.md",
            "EMBEDDED_OPENWEBUI.md",
            "PROVIDER_AUDIT.md",
        ):
            source = Path("docs") / name
            if source.exists():
                shutil.copyfile(source, args.output / name)
        shutil.copyfile(".evidence/regression.xml", args.output / "local-junit.xml")
        for name in (
            "ci.json",
            "release-run.json",
            "release.json",
            "repository.json",
            "FINAL_REPORT.md",
            "linux-inference.json",
            "f16-qualification.json",
            "rerun.json",
            "checks.txt",
        ):
            source = Path(".evidence/providers") / name
            if source.exists():
                shutil.copyfile(source, args.output / name)
    else:
        for name in ("CORRECTIVE_AUDIT.md", "ARCHITECTURE.md", "TESTING.md"):
            shutil.copyfile(Path("docs") / name, args.output / name)
        shutil.copyfile(".evidence/correction-tests.xml", args.output / "local-junit.xml")
        shutil.copyfile(
            ".evidence/quality-corrected/summary.json", args.output / "quality-summary.json"
        )
        for name in (
            "ci.json",
            "release-run.json",
            "release.json",
            "repository.json",
            "version-check.txt",
            "linux-frozen.txt",
            "FINAL_REPORT.md",
        ):
            source = Path(".evidence/correction") / name
            if source.exists():
                shutil.copyfile(source, args.output / name)
    files = sorted(p for p in args.output.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (args.output / "SHA256SUMS").write_text(
        "".join(
            hashlib.sha256(p.read_bytes()).hexdigest()
            + "  "
            + str(p.relative_to(args.output))
            + "\n"
            for p in files
        )
    )


if __name__ == "__main__":
    main()
