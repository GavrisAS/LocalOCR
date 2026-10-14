"""Allowlisted portable evidence; excludes all sensitive local OCR artifacts."""

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--providers", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
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
