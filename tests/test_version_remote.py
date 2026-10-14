"""Actual git remote reservations, rerun and collision evidence."""

import os
import subprocess
from pathlib import Path


def test_remote_reservation_and_rerun(tmp_path):
    root = Path(__file__).resolve().parents[1]
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"

    def git(*args, cwd=None):
        return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()

    git("init", "--bare", str(remote))
    git("init", "-b", "main", str(work))
    git("config", "user.email", "tests@example.invalid", cwd=work)
    git("config", "user.name", "Synthetic tests", cwd=work)
    git("remote", "add", "origin", str(remote), cwd=work)
    (work / "file").write_text("one")
    git("add", "file", cwd=work)
    git("commit", "-m", "one", cwd=work)
    sha1 = git("rev-parse", "HEAD", cwd=work)
    script = root / "scripts" / "next_version.py"
    import sys

    env = dict(os.environ)
    env.pop("GITHUB_OUTPUT", None)

    def reserve(sha, before):
        return subprocess.check_output(
            [sys.executable, str(script), "--sha", sha, "--before", before],
            cwd=work,
            env=env,
            text=True,
        ).strip()

    assert reserve(sha1, "0" * 40) == "v0.1"
    assert reserve(sha1, "0" * 40) == "v0.1"
    (work / "file").write_text("two")
    git("add", "file", cwd=work)
    git("commit", "-m", "two", cwd=work)
    sha2 = git("rev-parse", "HEAD", cwd=work)
    assert reserve(sha2, sha1) == "v0.2"
    assert reserve(sha2, sha1) == "v0.2"
    assert git("ls-remote", "--tags", "origin", cwd=work).splitlines() == [
        f"{sha1}\trefs/tags/v0.1",
        f"{sha2}\trefs/tags/v0.2",
    ]
