"""Validated tables to atomic OOXML; OCR strings never become formulas."""

import math
import os
import re
import tempfile
from pathlib import Path
from threading import Event

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from localocr.domain import TableDocument
from localocr.ollama import Cancelled


def value(text: str):
    if re.fullmatch(r"-?(?:0|[1-9]\d{0,14})", text):
        return int(text)
    if re.fullmatch(r"-?(?:0|[1-9]\d{0,12})[,.]\d{1,8}", text):
        number = float(text.replace(",", "."))
        if math.isfinite(number):
            return number
    return text


def write_workbook(
    document: TableDocument, path: Path, overwrite=False, cancel: Event | None = None
):
    document.validate()
    book = Workbook()
    book.remove(book.active)
    review = []
    border = Border(*([Side(style="thin", color="808080")] * 4))
    for index, table in enumerate(document.tables, 1):
        sheet = book.create_sheet(f"Таблица {index}")
        for cell in table.cells:
            target = sheet.cell(cell.row + 1, cell.column + 1)
            if ILLEGAL_CHARACTERS_RE.search(cell.text) or len(cell.text) > 32767:
                raise ValueError(
                    "Текст ячейки не помещается в Excel или содержит control characters"
                )
            target.value = value(cell.text)
            if isinstance(target.value, str):
                target.data_type = "s"
            target.font = Font(bold=cell.is_header)
            target.alignment = Alignment(vertical="center", wrap_text=True)
            target.border = border
            if cell.warnings:
                target.fill = PatternFill("solid", fgColor="FFF2CC")
                review.append((index, cell.row + 1, cell.column + 1, "; ".join(cell.warnings)))
            if cell.rowspan > 1 or cell.colspan > 1:
                sheet.merge_cells(
                    start_row=cell.row + 1,
                    start_column=cell.column + 1,
                    end_row=cell.row + cell.rowspan,
                    end_column=cell.column + cell.colspan,
                )
        for row in sheet:
            for target in row:
                target.border = border
        for column in range(table.columns):
            width = table.column_widths[column] if table.column_widths else 18
            sheet.column_dimensions[get_column_letter(column + 1)].width = max(5, min(80, width))
        for row in range(table.rows):
            height = table.row_heights[row] if table.row_heights else 28
            sheet.row_dimensions[row + 1].height = max(15, min(180, height))
        grid = table.grid()
        headers = 0
        for row in range(table.rows):
            if all(grid[row, column].is_header for column in range(table.columns)):
                headers += 1
            else:
                break
        if 0 < headers < table.rows and all(
            c.row + c.rowspan <= headers for c in table.cells if c.row < headers
        ):
            sheet.freeze_panes = f"A{headers + 1}"
        review.extend((index, issue.row, issue.column, issue.message) for issue in table.issues)
    if review:
        sheet = book.create_sheet("Проверка")
        sheet.append(["Таблица", "Строка", "Столбец", "REVIEW"])
        for row in review:
            sheet.append(list(row))
            for target in sheet[sheet.max_row]:
                if isinstance(target.value, str):
                    target.data_type = "s"
        sheet.column_dimensions["D"].width = 90
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".localocr-", suffix=".xlsx", dir=path.parent)
    os.close(descriptor)
    try:
        book.save(temporary)
        check = load_workbook(temporary)
        check.close()
        if cancel is not None and cancel.is_set():
            raise Cancelled("Обработка отменена")
        if overwrite:
            os.replace(temporary, path)
        else:
            # Atomic exclusive publication on NTFS/POSIX, including competing jobs.
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
