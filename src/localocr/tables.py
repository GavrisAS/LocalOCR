"""Inert, strict HTML table parser; no execution or speculative repairs."""

import re
from html.parser import HTMLParser

from localocr.domain import Cell, StructureError, Table, TableDocument


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        self.rows: list[list[Cell]] | None = None
        self.row: list[Cell] | None = None
        self.cell: Cell | None = None
        self.parts: list[str] = []
        self.cell_tag = ""

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object"}:
            raise StructureError("Активный HTML в ответе OCR")
        if tag == "table":
            if self.rows is not None:
                raise StructureError("Вложенные таблицы не поддерживаются")
            self.rows = []
        elif self.rows is not None:
            if tag == "tr":
                if self.row is not None:
                    raise StructureError("Незакрытая строка")
                self.row = []
            elif tag in {"td", "th"}:
                if self.row is None or self.cell is not None:
                    raise StructureError("Некорректное расположение ячейки")
                attributes = dict(attrs)
                try:
                    rs = int(attributes.get("rowspan", "1"))
                    cs = int(attributes.get("colspan", "1"))
                except (ValueError, TypeError) as error:
                    raise StructureError("Некорректный span") from error
                if not 1 <= rs <= 10000 or not 1 <= cs <= 1000:
                    raise StructureError("Некорректный span")
                self.cell = Cell(len(self.rows), 0, "", rs, cs, tag == "th")
                self.cell_tag = tag
                self.parts = []
            elif tag == "br" and self.cell is not None:
                self.parts.append("\n")
            elif tag not in {"thead", "tbody", "tfoot", "b", "strong", "i", "em", "span"}:
                raise StructureError(f"Неподдерживаемый HTML tag: {tag}")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != "br":
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.cell is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"}:
            if self.cell is None or tag != self.cell_tag or self.row is None:
                raise StructureError("Некорректное закрытие ячейки")
            self.cell.text = "".join(self.parts).strip()
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr":
            if self.row is None or self.cell is not None or self.rows is None:
                raise StructureError("Незакрытая ячейка или строка")
            self.rows.append(self.row)
            self.row = None
        elif tag == "table":
            if self.rows is None or self.row is not None or self.cell is not None:
                raise StructureError("Незакрытая таблица")
            self.tables.append(place_rows(self.rows))
            self.rows = None


def place_rows(rows: list[list[Cell]]) -> Table:
    occupied: set[tuple[int, int]] = set()
    cells: list[Cell] = []
    width = 0
    for r, row in enumerate(rows):
        column = 0
        for cell in row:
            while (r, column) in occupied:
                column += 1
            cell.row, cell.column = r, column
            for y in range(r, r + cell.rowspan):
                for x in range(column, column + cell.colspan):
                    if (y, x) in occupied:
                        raise StructureError("Перекрытие объединений")
                    occupied.add((y, x))
            cells.append(cell)
            column += cell.colspan
            width = max(width, column)
    table = Table(cells, len(rows), width)
    table.grid()
    return table


def parse_response(text: str) -> TableDocument:
    if len(text) > 4_000_000:
        raise StructureError("Ответ OCR превышает ограничение")
    if re.search(r"<\s*(script|iframe|object|style)\b", text, re.I):
        raise StructureError("Активный HTML в ответе OCR")
    if re.search(r"<table\b", text, re.I):
        parser = TableParser()
        parser.feed(text)
        parser.close()
        if parser.rows is not None or parser.cell is not None or parser.row is not None:
            raise StructureError("Усечённая HTML-таблица")
        document = TableDocument(parser.tables)
    else:
        lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
        if lines and lines[0].startswith("```"):
            lines = lines[1:-1] if lines[-1] == "```" else []
        if len(lines) < 2 or not re.fullmatch(
            r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", lines[1]
        ):
            raise StructureError("Ответ не содержит однозначную таблицу")
        rows = []
        for index, line in enumerate([lines[0], *lines[2:]]):
            if "|" not in line or "\\|" in line:
                raise StructureError("Неоднозначная Markdown-таблица")
            rows.append(
                [
                    Cell(index, 0, value.strip(), is_header=index == 0)
                    for value in line.strip("|").split("|")
                ]
            )
        document = TableDocument([place_rows(rows)])
    document.validate()
    return document
