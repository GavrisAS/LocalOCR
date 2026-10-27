"""Seeded, independent synthetic holdout; no runtime model/network dependency."""

import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from localocr.domain import Cell, Table


@dataclass
class SyntheticCase:
    image: Image.Image
    gold: Table
    seed: int
    style: str
    rotation: float


def generate(seed: int, *, simple=False) -> SyntheticCase:
    rng = random.Random(seed)
    rows, columns = (3, 3) if simple else (rng.randint(3, 10), rng.randint(2, 8))
    font_size = 24 if simple else rng.randint(13, 26)
    font = ImageFont.load_default(size=font_size)
    widths = [rng.randint(100, 170) for _ in range(columns)]
    heights = [rng.randint(48, 90) for _ in range(rows)]
    xs, ys = [20], [20]
    for width in widths:
        xs.append(xs[-1] + width)
    for height in heights:
        ys.append(ys[-1] + height)
    cells = []
    occupied = set()
    for row in range(rows):
        for column in range(columns):
            if (row, column) in occupied:
                continue
            rs, cs = 1, 1
            if not simple and rng.random() < 0.18:
                rs, cs = rng.choice([(2, 1), (1, 2)])
            if (
                row + rs > rows
                or column + cs > columns
                or any(
                    (r, c) in occupied
                    for r in range(row, row + rs)
                    for c in range(column, column + cs)
                )
            ):
                rs, cs = 1, 1
            occupied.update(
                (r, c) for r in range(row, row + rs) for c in range(column, column + cs)
            )
            text = (
                str((row + 1) * 10 + column)
                if simple
                else ("" if rng.random() < 0.15 else f"{rng.choice('ABCDE')}{rng.randint(10, 999)}")
            )
            cells.append(
                Cell(
                    row,
                    column,
                    text,
                    rs,
                    cs,
                    row == 0,
                    source_region=(xs[column], ys[row], xs[column + cs], ys[row + rs]),
                )
            )
    gold = Table(cells, rows, columns)
    gold.grid()
    image = Image.new("RGB", (xs[-1] + 20, ys[-1] + 20), "white")
    draw = ImageDraw.Draw(image)
    style = "grid" if simple else rng.choice(["grid", "open", "broken", "borderless"])
    for cell in cells:
        assert cell.source_region is not None
        left, top, right, bottom = cell.source_region
        if style != "borderless":
            draw.rectangle((left, top, right, bottom), outline="black", width=2)
        if not simple and rng.random() < 0.12 and cell.text:
            text_image = Image.new("RGB", (right - left - 8, bottom - top - 8), "white")
            ImageDraw.Draw(text_image).text((2, 2), cell.text, font=font, fill="black")
            rotated = text_image.rotate(90, expand=True)
            rotated.thumbnail((right - left - 8, bottom - top - 8))
            image.paste(rotated, (left + 4, top + 4))
        else:
            draw.text((left + 9, top + 10), cell.text, font=font, fill="black")
    if style == "open":
        draw.line((xs[-1], ys[0], xs[-1], ys[-1]), fill="white", width=4)
    if style == "broken":
        for _ in range(rows * columns // 2):
            x, y = rng.choice(xs), rng.randint(ys[0], ys[-1])
            draw.line((x, y, x, y + 7), fill="white", width=4)
    rotation = 0 if simple else rng.choice([0, 0, -2, 2, 90])
    if rotation:
        image = image.rotate(rotation, expand=True, fillcolor="white")
    return SyntheticCase(image, gold, seed, style, rotation)
