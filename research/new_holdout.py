"""Freeze new private synthetic inputs with Cyrillic and original-image polygons."""

import argparse
import hashlib
import json
import math
import random
import secrets
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def generate(root, seed):
    rng = random.Random(seed)
    font_path = Path("/usr/share/fonts/TTF/DejaVuSans.ttf")
    font = ImageFont.truetype(str(font_path), 23)
    records = []
    for index in range(8):
        rows, columns = rng.randint(4, 7), rng.randint(3, 5)
        w, h = columns * 170 + 40, rows * 65 + 40
        image = Image.new("RGB", (w, h), "white")
        draw = ImageDraw.Draw(image)
        cells: list[dict[str, Any]] = []
        style = ["grid", "broken", "borderless", "open"][index % 4]
        for row in range(rows):
            for column in range(columns):
                if row == 0 and column == 1:
                    continue
                span = 2 if row == 0 and column == 0 else 1
                x, y = 20 + 170 * column, 20 + 65 * row
                right, bottom = x + 170 * span, y + 65
                text = (
                    ""
                    if rng.random() < 0.17
                    else rng.choice(["Итог", "Сумма", "Объём", "12,05", "-31", "0", "2026"])
                )
                if style != "borderless":
                    draw.rectangle((x, y, right, bottom), outline="black", width=2)
                    if style == "broken":
                        draw.line((x, y + 22, x, y + 35), fill="white", width=4)
                    if style == "open" and column + span == columns:
                        draw.line((right, y, right, bottom), fill="white", width=4)
                draw.text((x + 8, y + 15), text, font=font, fill="black")
                cells.append(
                    {
                        "row": row,
                        "column": column,
                        "rowspan": 1,
                        "colspan": span,
                        "header": row == 0,
                        "text": text,
                        "polygon": [(x, y), (right, y), (right, bottom), (x, bottom)],
                    }
                )
        angle = [0, 90, 180, 270][index % 4] + (2 if index >= 4 else 0)
        rotated = image.rotate(
            angle, expand=True, fillcolor="white", resample=Image.Resampling.BICUBIC
        )
        cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        for cell in cells:
            cell["polygon"] = [
                [
                    round(cos * (x - w / 2) + sin * (y - h / 2) + rotated.width / 2, 4),
                    round(-sin * (x - w / 2) + cos * (y - h / 2) + rotated.height / 2, 4),
                ]
                for x, y in cell["polygon"]
            ]
        name = f"new-{index + 1:02d}.png"
        rotated.save(root / name)
        records.append(
            {
                "file": name,
                "seed": seed,
                "style": style,
                "rotation": angle,
                "original_size": rotated.size,
                "rows": rows,
                "columns": columns,
                "cells": cells,
                "source_sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
            }
        )
    (root / "gold.json").write_text(
        json.dumps(
            {
                "kind": "synthetic-only",
                "seed": seed,
                "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(),
                "cases": records,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    args.output.resolve().relative_to(Path("data").resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    generate(args.output, args.seed if args.seed is not None else secrets.randbits(48))


if __name__ == "__main__":
    main()
