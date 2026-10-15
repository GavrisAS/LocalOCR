"""Real synthetic vision → canonical → XLSX qualification, never a health-only PASS."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

from frozen_smoke import isolated_environment
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont


def synthetic(path: Path, rows: int):
    scale_x, scale_y = 220, 76
    image = Image.new("RGB", (3 * scale_x + 41, rows * scale_y + 41), "white")
    draw = ImageDraw.Draw(image)
    font_path = (
        "C:/Windows/Fonts/arial.ttf"
        if os.name == "nt"
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    font = ImageFont.truetype(font_path, 26)
    expected = []
    for row in range(rows):
        values = [f"R{row + 1:02}", str(row + 10), f"{row + 1}.25"]
        expected.append(values)
        for column, text in enumerate(values):
            draw.text((35 + column * scale_x, 42 + row * scale_y), text, font=font, fill="black")
    for column in range(4):
        draw.line(
            (20 + column * scale_x, 20, 20 + column * scale_x, 20 + rows * scale_y),
            fill="black",
            width=2,
        )
    for row in range(rows + 1):
        draw.line(
            (20, 20 + row * scale_y, 20 + 3 * scale_x, 20 + row * scale_y), fill="black", width=2
        )
    image.save(path)
    return expected


def qualify(root: Path, output: Path, sha: str, isolated: bool, relocated=False):
    evidence = {
        "status": "FAIL",
        "platform": sys.platform,
        "precision": "f16",
        "build_commit": sha,
        "network_isolated": isolated,
        "cases": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = root / "embedded/manifest.json"
    evidence["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    evidence["upstream"] = json.loads(manifest.read_text())["upstream"]
    try:
        # Full relocation, including DLLs and models; original installation is not used.
        context = (
            nullcontext(root.parent)
            if relocated
            else tempfile.TemporaryDirectory(
                prefix="localocr-relocated-", ignore_cleanup_errors=True
            )
        )
        with context as directory:
            moved = root if relocated else Path(directory) / "LocalOCR"
            if not relocated:
                shutil.copytree(root, moved)
            exe = moved / "LocalOCR-CLI/LocalOCR-CLI.exe"
            evidence["device_checks"] = []
            for mode in ("cpu", "auto", "gpu"):
                check = subprocess.run(
                    [str(exe), "doctor", "--provider", "embedded", "--device", mode],
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    timeout=600,
                    env=isolated_environment(),
                )
                evidence["device_checks"].append(
                    {
                        "mode": mode,
                        "exit_code": check.returncode,
                        "stdout": check.stdout,
                        "stderr": check.stderr,
                    }
                )
                if check.returncode != (3 if mode == "gpu" else 0):
                    raise ValueError(
                        f"CPU/no-GPU runner device policy failed: {mode}: {check.stdout} {check.stderr}"
                    )
            for rows in [3, 30]:
                image = Path(directory) / f"synthetic-{rows}.png"
                expected = synthetic(image, rows)
                started = time.monotonic()
                result = subprocess.run(
                    [
                        str(exe),
                        "convert",
                        str(image),
                        "--provider",
                        "embedded",
                        "--precision",
                        "f16",
                        "--timeout",
                        "600",
                        "--device",
                        "cpu",
                        "--debug-http",
                    ],
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    timeout=1800,
                    env=isolated_environment(),
                )
                pipeline_seconds = time.monotonic() - started
                xlsx = image.parent / "results" / (image.stem + ".xlsx")
                if result.returncode not in {0, 1} or not xlsx.is_file():
                    raise ValueError(
                        f"Frozen vision pipeline failed ({rows} rows): {result.stdout} {result.stderr}"
                    )
                book = load_workbook(xlsx)
                sheet = book["Таблица 1"]
                observed = [
                    [
                        sheet.cell(r + 1, c + 1).comment.text
                        if sheet.cell(r + 1, c + 1).comment
                        else None
                        for c in range(3)
                    ]
                    for r in range(rows)
                ]
                shape = [sheet.max_row, sheet.max_column]
                values = [[sheet.cell(r + 1, c + 1).value for c in range(3)] for r in range(rows)]
                types = [
                    [sheet.cell(r + 1, c + 1).data_type for c in range(3)] for r in range(rows)
                ]
                expected_values = [[row[0], int(row[1]), float(row[2])] for row in expected]
                book.close()
                mismatches = sum(
                    a != b for er, ar in zip(expected, observed) for a, b in zip(er, ar)
                )
                evidence["cases"].append(
                    {
                        "rows": rows,
                        "requested_mode": "cpu",
                        "actual_backend": re.findall(
                            r"Embedded F16 · (CPU|CUDA|VULKAN) ·", result.stdout
                        ),
                        "pipeline_seconds": pipeline_seconds,
                        "startup_seconds": [
                            float(value)
                            for value in re.findall(r"model load=([0-9.]+)s", result.stdout)
                        ],
                        "ocr_request_seconds": [
                            float(value)
                            for value in re.findall(
                                r"Embedded recognize latency=([0-9.]+)s", result.stdout
                            )
                        ],
                        "technical_trace": result.stdout[-20000:],
                        "shape": shape,
                        "text_mismatches": mismatches,
                        "values_match": values == expected_values,
                        "cell_types": types,
                        "xlsx_sha256": hashlib.sha256(xlsx.read_bytes()).hexdigest(),
                        "exit_code": result.returncode,
                    }
                )
                if (
                    shape != [rows, 3]
                    or mismatches
                    or values != expected_values
                    or any(t != ["s", "n", "n"] for t in types)
                ):
                    raise ValueError("Synthetic OCR cells/shape differ from known source")
            evidence["status"] = "PASS" if sys.platform == "win32" and isolated else "PARTIAL"
    except Exception as error:
        evidence["error"] = str(error)
        raise
    finally:
        output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    if evidence["status"] != "PASS":
        raise ValueError("Windows/network isolation qualification remains PENDING")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--network-isolated", action="store_true")
    parser.add_argument("--relocated", action="store_true")
    args = parser.parse_args()
    qualify(args.root.resolve(), args.output, args.sha, args.network_isolated, args.relocated)
