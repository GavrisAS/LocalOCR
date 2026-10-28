"""Narrow DeepSeek layout grammar. Bboxes never imply table cells or geometry.

Recognize only an allowlisted label at a block boundary followed by [[x,y,x,y]],
four ordered integer normalized coordinates in [0,1000]. Spaces/CRLF are allowed.
Inline natural language and all uncertain forms stay literal, with a warning.
No syntax here has yet been qualified against the owner's Windows raw archive.
"""

import re
from dataclasses import dataclass, field

VERSION = "deepseek-layout/1"
MAX_MARKERS = 4096
MAX_METADATA = 256
LABEL = re.compile(r"(?<!\w)(table|text|sub_title)\s*\[\[")
BBOX = re.compile(r"\s*(\d{1,4})\s*,\s*(\d{1,4})\s*,\s*(\d{1,4})\s*,\s*(\d{1,4})\s*")


@dataclass
class LayoutResult:
    text: str
    metadata: list[dict] = field(default_factory=list)
    uncertain: int = 0
    metadata_characters: int = 0


def is_deepseek(model_id):
    return model_id.casefold().split(":", 1)[0].rsplit("/", 1)[-1] == "deepseek-ocr"


def adapt(raw):
    result = LayoutResult(raw)
    pieces, cursor, last_marker_end = [], 0, -1
    count = 0
    for match in LABEL.finditer(raw):
        count += 1
        if count > MAX_MARKERS:
            raise ValueError("LAYOUT_MARKER_LIMIT")
        # Only a line boundary (possibly immediately after a previous marker) is control syntax.
        line_start = raw.rfind("\n", 0, match.start()) + 1
        prefix = raw[max(line_start, last_marker_end) : match.start()]
        if prefix.strip():
            continue
        close = raw.find("]]", match.end(), match.end() + MAX_METADATA)
        bbox = BBOX.fullmatch(raw[match.end() : close]) if close >= 0 else None
        coords = tuple(map(int, bbox.groups())) if bbox else ()
        if not coords or not (
            0 <= coords[0] < coords[2] <= 1000 and 0 <= coords[1] < coords[3] <= 1000
        ):
            result.uncertain += 1
            continue
        end = close + 2
        # Extra brackets are not part of this proven grammar; preserve rather than guess.
        if end < len(raw) and raw[end] == "]":
            result.uncertain += 1
            continue
        pieces.extend([raw[cursor : match.start()], "\n"])
        result.metadata.append(
            {"kind": match[1], "bbox": coords, "start": match.start(), "end": end}
        )
        result.metadata_characters += end - match.start()
        cursor = last_marker_end = end
    pieces.append(raw[cursor:])
    result.text = "".join(pieces)
    return result
