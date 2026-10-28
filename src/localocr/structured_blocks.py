"""Bounded independent table islands, without inferred cells or repairs."""

import re

from localocr.domain import StructureError
from localocr.tables import parse_response

MAX_BLOCKS = 64
MAX_TAGS = 200_000
MAX_DEPTH = 128
TAG = re.compile(r"<(/?)([a-zA-Z][\w:-]*)\b[^<>]{0,4096}>")
SEPARATOR = re.compile(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?")


def check_block(raw):
    depth, tags, area = 0, 0, 0
    for match in TAG.finditer(raw):
        tags += 1
        end, name = match[1], match[2].lower()
        if end:
            depth = max(0, depth - 1)
        elif name not in {"br", "hr", "img", "input", "meta", "link"} and not match[0].endswith(
            "/>"
        ):
            depth += 1
        if depth > MAX_DEPTH or tags > MAX_TAGS:
            raise ValueError("RESPONSE_STRUCTURE_LIMIT")
        if not end and name in {"td", "th"}:
            sizes = []
            for attr in ("rowspan", "colspan"):
                value = re.search(attr + r"\s*=\s*['\"]?(\d+)", match[0], re.I)
                sizes.append(
                    int(value[1]) if value and len(value[1]) < 7 else 100_001 if value else 1
                )
            area += sizes[0] * sizes[1]
            if area > 100_000:
                raise ValueError("RESPONSE_STRUCTURE_LIMIT")


def html_blocks(raw):
    """Yield outermost table ranges; nested tables are one unresolved island."""
    start, depth, count = None, 0, 0
    for match in re.finditer(r"</?table\b[^<>]{0,4096}>", raw, re.I):
        if not match[0].startswith("</"):
            if depth == 0:
                start = match.start()
                count += 1
                if count > MAX_BLOCKS:
                    raise ValueError("RESPONSE_STRUCTURE_LIMIT")
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                yield start, match.end(), True
                start = None
    if start is not None:
        yield start, len(raw), False


def closed_prefix(raw):
    """Only contiguous explicitly closed rows before the first broken row.

    No source rows/cells are invented. Crossing spans or ragged prefixes fail
    canonical validation. At most one additional parse, never a row search loop.
    """
    if len(re.findall(r"<table\b", raw, re.I)) != 1:
        return None
    first = re.search(r"<tr\b", raw, re.I)
    if first is None:
        return None
    end, row_start = first.start(), None
    for token in re.finditer(r"</?tr\b[^<>]{0,4096}>", raw[first.start() :], re.I):
        start = first.start() + token.start()
        if not token[0].startswith("</"):
            if row_start is not None or raw[end:start].strip():
                break
            row_start = start
        else:
            if row_start is None:
                break
            end = first.start() + token.end()
            row_start = None
    if end == first.start():
        return None
    prefix = raw[:end] + "</table>"
    try:
        check_block(prefix)
        return parse_response(prefix), end
    except StructureError, ValueError:
        return None


def extract_islands(raw, result, plain_lines, *, preserve_rows=False):
    formats = set()

    def markdown(chunk):
        lines = chunk.splitlines(keepends=True)
        rest, index = [], 0
        while index < len(lines):
            end = index + 2
            if end <= len(lines) and SEPARATOR.fullmatch(lines[index + 1].strip()):
                while end < len(lines) and "|" in lines[end] and lines[end].strip():
                    end += 1
                try:
                    if len(result.document.tables) >= MAX_BLOCKS:
                        raise ValueError("RESPONSE_STRUCTURE_LIMIT")
                    doc = parse_response("".join(lines[index:end]))
                    result.document.tables.extend(doc.tables)
                    formats.add("markdown")
                    index = end
                    continue
                except StructureError, ValueError:
                    result.codes.append("PARSER_FAILURE")
            rest.append(lines[index])
            index += 1
        text = "".join(rest)
        result.lines.extend(plain_lines(text, result.codes))
        if text.strip() and ("|" in text or "\t" in text):
            result.codes.append("UNRESOLVED")

    try:
        blocks = list(html_blocks(raw))
    except ValueError:
        result.codes.append("RESPONSE_STRUCTURE_LIMIT")
        result.lines = plain_lines(raw, result.codes)
        return
    cursor = 0
    for start, end, complete in blocks:
        markdown(raw[cursor:start])
        block = raw[start:end]
        try:
            check_block(block)
            if not complete:
                raise StructureError("Unclosed table")
            doc = parse_response(block)
        except (StructureError, ValueError) as error:
            result.codes.append(
                "RESPONSE_STRUCTURE_LIMIT"
                if str(error) == "RESPONSE_STRUCTURE_LIMIT"
                else "PARSER_FAILURE"
            )
            prefix = (
                closed_prefix(block)
                if preserve_rows and str(error) != "RESPONSE_STRUCTURE_LIMIT"
                else None
            )
            if prefix:
                doc, offset = prefix
                result.document.tables.extend(doc.tables)
                formats.add("html")
                result.codes.append("PARTIAL_STRUCTURED")
                first_row = re.search(r"<tr\b", block, re.I)
                assert first_row is not None
                result.lines.extend(plain_lines(block[: first_row.start()], result.codes))
                result.lines.extend(plain_lines(block[offset:], result.codes))
            else:
                result.lines.extend(plain_lines(block, result.codes))
            if str(error) != "RESPONSE_STRUCTURE_LIMIT":
                result.codes.append("UNRESOLVED")
        else:
            result.document.tables.extend(doc.tables)
            formats.add("html")
            # Keep captions/observations outside explicitly consumed cells.
            result.lines.extend(
                plain_lines(
                    re.sub(r"<(td|th)\b[^>]*>.*?</\1\s*>", "\n", block, flags=re.I | re.S),
                    result.codes,
                )
            )
        cursor = end
    markdown(raw[cursor:])
    result.source_format = "+".join(sorted(formats)) if formats else "html" if blocks else "plain"
    result.discarded_markup = len(TAG.findall(raw))
