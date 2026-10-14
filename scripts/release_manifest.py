"""Build exact multi-asset descriptor; no runtime networking."""

import argparse
import hashlib
import json
from pathlib import Path


def write(folder: Path, tag: str, sha: str):
    assets = {}
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.name != "release-manifest.json":
            if path.stat().st_size >= 2 * 1024**3:
                raise ValueError("Release asset exceeds GitHub limit")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            assets[path.name] = {"size": path.stat().st_size, "sha256": digest}
    (folder / "release-manifest.json").write_text(
        json.dumps({"schema": 1, "tag": tag, "sha": sha, "assets": assets}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    write(args.folder, args.tag, args.sha)
