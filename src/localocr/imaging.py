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
    safe_rows: list[int] | None = None


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as source:
        original_size = source.size
        orientation = source.getexif().get(274, 1)
        if source.width * source.height > 40_000_000:
            raise ValueError("Изображение превышает 40 миллионов пикселей")
        if getattr(source, "n_frames", 1) != 1:
            raise ValueError("Многостраничные изображения пока не поддерживаются")
        image = ImageOps.exif_transpose(source).convert("RGB")
    transposed_size = image.size
    deskew_angle = 0.0
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
                deskew_angle = angle
                image = image.rotate(
                    angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white"
                )
    w, h = original_size
    inverse_exif = {
        1: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        2: [[-1, 0, w], [0, 1, 0], [0, 0, 1]],
        3: [[-1, 0, w], [0, -1, h], [0, 0, 1]],
        4: [[1, 0, 0], [0, -1, h], [0, 0, 1]],
        5: [[0, 1, 0], [1, 0, 0], [0, 0, 1]],
        6: [[0, 1, 0], [-1, 0, h], [0, 0, 1]],
        7: [[0, -1, w], [-1, 0, h], [0, 0, 1]],
        8: [[0, -1, w], [1, 0, 0], [0, 0, 1]],
    }.get(orientation, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    angle = np.radians(deskew_angle)
    cos, sin = np.cos(angle), np.sin(angle)
    old_x, old_y = transposed_size[0] / 2, transposed_size[1] / 2
    new_x, new_y = image.width / 2, image.height / 2
    inverse_rotation = np.array(
        [
            [cos, -sin, old_x - cos * new_x + sin * new_y],
            [sin, cos, old_y - sin * new_x - cos * new_y],
            [0, 0, 1],
        ]
    )
    matrix = np.asarray(inverse_exif) @ inverse_rotation
    image.info["localocr_normalization"] = {
        "original_size": original_size,
        "exif_orientation": orientation,
        "deskew_degrees": deskew_angle,
        "normalized_to_original": matrix[:2].tolist(),
    }
    return image


def source_polygon(image, region):
    """Map normalized crop corners back to source edges (x,y), before EXIF/deskew."""
    matrix = image.info.get("localocr_normalization", {}).get(
        "normalized_to_original", [[1, 0, 0], [0, 1, 0]]
    )
    left, top, right, bottom = region
    return [
        tuple(round(sum(a * b for a, b in zip(row, (x, y, 1))), 3) for row in matrix)
        for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))
    ]


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


def supported_outer_boundaries(
    lines: np.ndarray, boundaries: list[int], perpendicular: list[int]
) -> tuple[list[int], bool]:
    length = lines.shape[1]
    band = max(2, min(15, round(lines.shape[0] * 0.003)))
    extents = []
    for position in perpendicular:
        pixels = np.flatnonzero(
            np.any(lines[max(0, position - band) : position + band + 1], axis=0)
        )
        if len(pixels) >= length * 0.6:
            extents.append((int(pixels[0]), int(pixels[-1])))
    if len(extents) < 3:
        return boundaries, False
    tolerance = max(3, round(length * 0.003))
    minimum_gap = max(8, float(np.median(np.diff(boundaries))) * 0.25)
    result = list(boundaries)
    for side in (0, 1):
        positions = [extent[side] for extent in extents]
        boundary = int(np.median(positions))
        support = sum(abs(position - boundary) <= tolerance for position in positions)
        if support / len(positions) < 0.75:
            continue
        gap = result[0] - boundary if side == 0 else boundary - result[-1]
        if gap >= minimum_gap:
            result.append(boundary)
            result.sort()
    return result, result != boundaries


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
            xs, open_vertical_edge = supported_outer_boundaries(
                horizontal[y : y + h, x : x + w], xs, ys
            )
            ys, open_horizontal_edge = supported_outer_boundaries(
                vertical[y : y + h, x : x + w].T, ys, xs
            )
            x_support = sum(vertical_counts[value] >= h * 0.6 for value in xs) / len(xs)
            y_support = sum(horizontal_counts[value] >= w * 0.6 for value in ys) / len(ys)
            confidence = (
                "strong"
                if min(x_support, y_support) >= 0.6
                and not open_vertical_edge
                and not open_horizontal_edge
                else "partial"
            )
            layouts.append(
                Layout(
                    (x, y, x + w, y + h),
                    [x + value for value in xs],
                    [y + value for value in ys],
                    confidence,
                    safe_row_boundaries(horizontal[y : y + h, x : x + w], xs, ys),
                )
            )
    return sorted(layouts, key=lambda layout: (layout.region[1], layout.region[0]))


def safe_row_boundaries(horizontal: np.ndarray, xs: list[int], ys: list[int]) -> list[int]:
    band = max(2, min(15, round(horizontal.shape[0] * 0.003)))
    safe = {0, len(ys) - 1}
    for index, position in enumerate(ys):
        line = np.any(horizontal[max(0, position - band) : position + band + 1], axis=0)
        supported = True
        for left, right in zip(xs, xs[1:]):
            margin = max(2, min(10, round((right - left) * 0.03)))
            segment = line[left + margin : max(left + margin + 1, right - margin)]
            if not len(segment) or np.count_nonzero(segment) / len(segment) < 0.7:
                supported = False
                break
        if supported:
            safe.add(index)
    return sorted(safe)


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
    boundaries = sorted(
        {0, rows, *(layout.safe_rows if layout.safe_rows is not None else range(rows + 1))}
    )
    while start < rows:
        remaining = [boundary for boundary in boundaries if boundary > start]
        fitting = [
            boundary
            for boundary in remaining
            if boundary - start <= max_rows and layout.ys[boundary] - layout.ys[start] <= max_height
        ]
        end = fitting[-1] if fitting else remaining[0]
        ranges.append((start, end))
        if end == rows:
            break
        context = [boundary for boundary in boundaries if start < boundary <= end - overlap_rows]
        start = context[-1] if context else end
    return ranges


def content_mask(image: Image.Image) -> np.ndarray:
    """Ink evidence after removing long rules, without interpreting glyphs as text."""
    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    rules = np.zeros_like(binary)
    for size in ((max(30, image.width // 20), 1), (1, max(30, image.height // 20))):
        rules = cv2.bitwise_or(
            rules,
            cv2.morphologyEx(
                binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, size)
            ),
        )
    # A one-pixel halo removes antialiased line edges. This is occupancy evidence,
    # never proof that an empty response is a correctly recognized empty cell.
    rules = cv2.dilate(rules, np.ones((3, 3), np.uint8))
    return cv2.bitwise_and(binary, cv2.bitwise_not(rules))


def region_has_ink(mask: np.ndarray, box: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = box
    margin = 3
    roi = mask[
        top + margin : max(top + margin, bottom - margin),
        left + margin : max(left + margin, right - margin),
    ]
    if not roi.size:
        return False
    count, _, stats, _ = cv2.connectedComponentsWithStats(roi, connectivity=8)
    return any(stats[i, cv2.CC_STAT_AREA] >= 4 for i in range(1, count))


def grid_hypothesis(image: Image.Image, layout: Layout):
    from localocr.domain import GridHypothesis

    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, image.width // 40), 1)),
    )
    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, image.height // 45))),
    )

    def support(mask, position, start, end, transpose=False):
        if transpose:
            mask = mask.T
        margin = max(2, min(10, (end - start) // 10))
        strip = mask[max(0, position - 3) : position + 4, start + margin : end - margin]
        return round(float(np.mean(np.any(strip, axis=0))), 3) if strip.size else 0.0

    hs = [
        [support(horizontal, y, a, b) for a, b in zip(layout.xs, layout.xs[1:])] for y in layout.ys
    ]
    vs = [
        [support(vertical, x, a, b, True) for x in layout.xs]
        for a, b in zip(layout.ys, layout.ys[1:])
    ]
    scaled = detect_layout(image.resize((max(1, image.width // 2), max(1, image.height // 2))))
    tolerance = max(5, round(max(image.size) * 0.005))
    stable = any(
        len(other.xs) == len(layout.xs)
        and len(other.ys) == len(layout.ys)
        and all(abs(a - b * 2) <= tolerance for a, b in zip(layout.xs, other.xs))
        and all(abs(a - b * 2) <= tolerance for a, b in zip(layout.ys, other.ys))
        for other in scaled
    )
    return GridHypothesis(layout.region, layout.xs, layout.ys, hs, vs, stable)
