"""Per-image research subprocess deadlines, including cold initialization."""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["table", "layout"])
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    args.output.resolve().relative_to(Path("data").resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    records = []
    inputs = [
        p
        for p in sorted(args.input.iterdir())
        if p.suffix.lower() in {".png", ".jpg", ".tif", ".jpeg"}
    ]
    for index, path in enumerate(inputs):
        out = args.output / f"process-{index + 1:02d}"
        started = time.monotonic()
        record = {
            "input": str(path.resolve()),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        with (args.output / f"process-{index + 1:02d}.log").open("w") as log:
            try:
                completed = subprocess.run(
                    [
                        str(args.python),
                        "research/layout_pilot.py",
                        args.task,
                        "--weights",
                        str(args.weights),
                        "--input",
                        str(args.input),
                        "--output",
                        str(out),
                        "--index",
                        str(index),
                    ],
                    stdout=log,
                    stderr=log,
                    timeout=args.seconds,
                    check=False,
                )
                record["status"] = (
                    "PROCESS_ERROR" if completed.returncode else "PROCESSED_UNVERIFIED"
                )
                result = out / "results.json"
                if result.exists():
                    saved = json.loads(result.read_text())
                    record.update(saved["records"][0])
                    record["init_seconds"] = saved["init_seconds"]
                    shutil.copytree(out / path.stem, args.output / path.stem)
            except subprocess.TimeoutExpired:
                record["status"] = "DEADLINE_EXCEEDED"
        record["process_seconds"] = time.monotonic() - started
        record["seconds"] = record["process_seconds"]
        records.append(record)
        (args.output / "results.json").write_text(
            json.dumps(
                {
                    "budget_seconds_per_image": args.seconds,
                    "timing": "cold per-image subprocess including initialization",
                    "records": records,
                },
                indent=2,
            )
        )
        print(index + 1, record["status"], round(record["seconds"], 3), flush=True)


if __name__ == "__main__":
    main()
