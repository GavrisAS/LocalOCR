"""Image normalization and geometry, independent of OCR text."""

import io
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
Image.MAX_IMAGE_PIXELS = 40_000_000


@dataclass
class Layout:
    region: tuple[int, int, int, int]
    xs: list[int]
    ys: list[int]
    confidence: str = "strong"


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as source:
        if source.width * source.height > 40_000_000:
            raise ValueError("Изображение превышает 40 миллионов пикселей")
        if getattr(source, "n_frames", 1) != 1:
            raise ValueError("Многостраничные изображения пока не поддерживаются")
        image = ImageOps.exif_transpose(source).convert("RGB")
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    lines = cv2.HoughLinesP(
        binary,
        1,
        np.pi / 1800,
        max(50, image.width // 5),
        minLineLength=max(40, image.width // 4),
        maxLineGap=10,
    )
    if lines is not None:
        angles = [
            np.degrees(np.arctan2(y2 - y1, x2 - x1))
            for x1, y1, x2, y2 in lines.reshape(-1, 4)
            if abs(y2 - y1) < abs(x2 - x1) * 0.2
        ]
        if angles:
            angle = float(np.median(angles))
            if 0.2 < abs(angle) < 8:
                image = image.rotate(
                    angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white"
                )
    return image


def centers(values: np.ndarray, merge_gap: int = 3) -> list[int]:
    indices = np.flatnonzero(values)
    if not len(indices):
        return []
    groups = np.split(indices, np.where(np.diff(indices) > 1)[0] + 1)
    merged = []
    for group in groups:
        center = int(np.mean(group))
        if merged and center - merged[-1][1] <= merge_gap:
            merged[-1][0] = int((merged[-1][0] + center) / 2)
            merged[-1][1] = center
        else:
            merged.append([center, center])
    return [center for center, _ in merged]


def detect_layout(image: Image.Image) -> list[Layout]:
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    height, width = gray.shape
    horizontal_kernel = max(15, width // 40)
    vertical_kernel = max(15, height // 45)
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_kernel, 1)),
    )
    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_kernel)),
    )
    network = cv2.bitwise_or(horizontal, vertical)
    contours, _ = cv2.findContours(network, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    layouts = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < max(40, width * 0.06) or h < max(30, height * 0.025):
            continue
        vertical_counts = np.count_nonzero(vertical[y : y + h, x : x + w], axis=0)
        horizontal_counts = np.count_nonzero(horizontal[y : y + h, x : x + w], axis=1)
        xs = centers(vertical_counts >= max(3, h * 0.25), max(3, round(w * 0.0015)))
        ys = centers(horizontal_counts >= max(3, w * 0.12), max(3, round(h * 0.0015)))
        if len(xs) >= 2 and len(ys) >= 2:
            x_support = sum(vertical_counts[value] >= h * 0.6 for value in xs) / len(xs)
            y_support = sum(horizontal_counts[value] >= w * 0.6 for value in ys) / len(ys)
            confidence = "strong" if min(x_support, y_support) >= 0.6 else "partial"
            layouts.append(
                Layout(
                    (x, y, x + w, y + h),
                    [x + value for value in xs],
                    [y + value for value in ys],
                    confidence,
                )
            )
    return sorted(layouts, key=lambda layout: (layout.region[1], layout.region[0]))


def has_visible_text(image: Image.Image) -> bool:
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    minimum_ink = max(12, int(image.width * image.height * 0.00005))
    return int(np.count_nonzero(binary)) >= minimum_ink


def encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def row_fragments(
    layout: Layout, max_height: int = 1800, max_rows: int = 40, overlap_rows: int = 2
) -> list[tuple[int, int]]:
    """Row ranges bounded by pixel scale and count, with context overlap."""
    ranges = []
    start = 0
    rows = len(layout.ys) - 1
    while start < rows:
        end = start + 1
        while (
            end < rows
            and end - start < max_rows
            and layout.ys[end + 1] - layout.ys[start] <= max_height
        ):
            end += 1
        ranges.append((start, end))
        if end == rows:
            break
        start = max(start + 1, end - overlap_rows)
    return ranges
