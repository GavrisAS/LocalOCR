"""Windows frozen portable paths: real EXEs, alternate CWD, profile traps."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    with tempfile.TemporaryDirectory(prefix="localocr-portable-smoke-") as name:
        cwd = Path(name)
        env = dict(os.environ)
        traps = []
        for key in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME"):
            trap = cwd / key
            trap.mkdir()
            env[key] = str(trap)
            traps.append(trap)
        for full in (False, True):
            subprocess.run(
                [
                    str(root / "LocalOCR.exe"),
                    *(["--full-gui"] if full else []),
                    "--smoke-test",
                    "--expected-version",
                    args.version,
                    "--expected-commit",
                    args.commit,
                ],
                cwd=cwd,
                env=env,
                timeout=30,
                check=True,
            )
            config = json.loads((root / "config.json").read_text(encoding="utf-8"))
            assert config["provider"] == "openwebui" and config["simple_mode"] == "server"
            assert config["ssl_verify"] is False and config["trust_env"] is False
            assert config["api_token"] == ""
            assert (root / "localocr.log").is_file()
        cli = root / "LocalOCR-CLI" / "LocalOCR-CLI.exe"
        result = subprocess.run(
            [str(cli), "doctor", "--use-config"], cwd=cwd, env=env, capture_output=True, timeout=30
        )
        assert result.returncode == 2, result.stderr
        assert not (cli.parent / "config.json").exists()
        assert not (cli.parent / "localocr.log").exists()
        assert all(not (trap / "LocalOCR").exists() for trap in traps)
        assert not (root / "_internal" / "config.json").exists()
    for file in (root / "config.json", *root.glob("localocr.log*")):
        file.unlink(missing_ok=True)
    print("Frozen simple/full GUI + nested CLI portable paths: PASS")


if __name__ == "__main__":
    main()
