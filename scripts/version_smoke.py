"""Independent source/package identity check, called after reservation."""

import argparse
import email
import subprocess
import tempfile
import zipfile
from pathlib import Path

import localocr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tagged = subprocess.check_output(
        ["git", "rev-list", "-n", "1", "v" + args.version], text=True
    ).strip()
    if sha != tagged or localocr.__version__ != args.version:
        raise ValueError("Independent source version mismatch")
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(["uv", "build", "--out-dir", folder], check=True)
        wheel = next(Path(folder).glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            name = next(name for name in archive.namelist() if name.endswith("/METADATA"))
            metadata = email.message_from_bytes(archive.read(name))
            if metadata["Version"] != args.version:
                raise ValueError("Package version mismatch")
    print(f"Source/package version {args.version}, SHA {sha}: PASS")


if __name__ == "__main__":
    main()
