"""Reserve a remote tag before checks/build; reruns reuse the commit's tag."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from localocr.versioning import select_tag


def remote_tags():
    lines = subprocess.check_output(
        ["git", "ls-remote", "--tags", "origin"], text=True
    ).splitlines()
    tags = {}
    for line in lines:
        sha, ref = line.split()
        name = ref.removeprefix("refs/tags/")
        if not name.endswith("^{}"):
            tags[name] = sha
    for line in lines:
        sha, ref = line.split()
        if ref.endswith("^{}"):
            tags[ref.removeprefix("refs/tags/")[:-3]] = sha
    return tags


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--major", type=int, default=0)
    args = parser.parse_args()
    if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != args.sha:
        raise RuntimeError("Checkout SHA mismatch")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        tags = remote_tags()
        tag = select_tag(tags, args.sha, args.before, args.major)
        if tag is None:
            time.sleep(5)
            continue
        if tag in tags:
            if tags[tag] != args.sha:
                raise RuntimeError("Tag collision")
            break
        result = subprocess.run(["git", "push", "origin", f"{args.sha}:refs/tags/{tag}"])
        if result.returncode != 0:
            # Another concurrent writer may have won; reread remote, never force.
            time.sleep(2)
            continue
        if remote_tags().get(tag) != args.sha:
            raise RuntimeError("Reservation verification failed")
        break
    else:
        raise RuntimeError("Predecessor reservation unavailable or tag push rejected")
    print(tag)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"tag={tag}\nversion={tag[1:]}\n")


if __name__ == "__main__":
    main()
