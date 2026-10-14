from threading import Event

import pytest
from openpyxl import load_workbook

from localocr.domain import Cell, StructureError, Table, TableDocument, ValidationIssue
from localocr.excel import value, write_workbook
from localocr.ollama import Cancelled
from localocr.tables import parse_response


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0012", "0012"),
        ("5,50", 5.5),
        ("2590-254", "2590-254"),
        ("0", 0),
        ("-4", -4),
        ("=1+1", "=1+1"),
        ("1234567890123456", "1234567890123456"),
        ("1e4", "1e4"),
        ("+123", "+123"),
        ("1.20", 1.2),
        ("01.20", "01.20"),
        ("∞", "∞"),
    ],
)
def test_semantics(text, expected):
    assert value(text) == expected


def test_roundtrip(tmp_path):
    doc = parse_response(
        '<table><tr><th rowspan="2">Код</th><th colspan="2">Заголовок</th></tr><tr><th>А</th><th>Б</th></tr><tr><td>0012</td><td>=1+1</td><td></td></tr></table>'
    )
    doc.tables[0].issues.append(ValidationIssue("TEST", "Проверить"))
    path = tmp_path / "выход.xlsx"
    write_workbook(doc, path)
    book = load_workbook(path)
    sheet = book.worksheets[0]
    assert (sheet.max_row, sheet.max_column) == (3, 3)
    assert {str(r) for r in sheet.merged_cells.ranges} == {"A1:A2", "B1:C1"}
    assert sheet["A3"].value == "0012"
    assert sheet["B3"].value == "=1+1" and sheet["B3"].data_type == "s"
    assert sheet["C3"].value is None
    assert sheet["A1"].font.bold and sheet["A1"].alignment.wrap_text
    assert sheet["A3"].border.left.style == "thin"
    assert sheet.freeze_panes == "A3"
    assert "Проверка" in book.sheetnames
    book.close()
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_workbook(doc, path)
    assert path.read_bytes() == original
    event = Event()
    event.set()
    with pytest.raises(Cancelled):
        write_workbook(doc, tmp_path / "cancel.xlsx", cancel=event)
    assert not (tmp_path / "cancel.xlsx").exists()
    assert not list(tmp_path.glob(".localocr-*"))


@pytest.mark.parametrize("rows,columns", [(2, 2), (3, 5), (9, 32), (12, 50)])
def test_dimensions(tmp_path, rows, columns):
    doc = TableDocument(
        [
            Table(
                [Cell(r, c, f"{r}:{c}") for r in range(rows) for c in range(columns)], rows, columns
            )
        ]
    )
    path = tmp_path / "result.xlsx"
    write_workbook(doc, path)
    book = load_workbook(path)
    assert (book.active.max_row, book.active.max_column) == (rows, columns)
    assert book.active.cell(rows, columns).value == f"{rows - 1}:{columns - 1}"
    book.close()


def test_invalid_not_published(tmp_path):
    with pytest.raises(StructureError):
        write_workbook(TableDocument([Table([Cell(0, 0, "x")], 2, 2)]), tmp_path / "bad.xlsx")
    assert not list(tmp_path.iterdir())
