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


def test_review_text_cannot_be_formula(tmp_path):
    doc = TableDocument(
        [
            Table(
                [Cell(0, 0, "=1+1", warnings=["=2+2"])],
                1,
                1,
                issues=[ValidationIssue("x", '=HYPERLINK("bad")')],
            )
        ]
    )
    path = tmp_path / "safe.xlsx"
    write_workbook(doc, path)
    book = load_workbook(path)
    assert all(cell.data_type != "f" for sheet in book for row in sheet for cell in row)
    assert book["Проверка"]["D2"].value == "=2+2"
    book.close()


@pytest.mark.parametrize(
    "text",
    ["5,50", "5,70", "9,60", "7,00", "24,00", "0,5", "0012", "2590-254", "1e4", "01.02", "=1+1"],
)
def test_printed_fidelity(tmp_path, text):
    path = tmp_path / "fidelity.xlsx"
    write_workbook(TableDocument([Table([Cell(0, 0, text)], 1, 1)]), path)
    book = load_workbook(path)
    cell = book.active["A1"]
    assert cell.comment.text == text
    if "," in text:
        places = len(text.split(",")[1])
        assert cell.data_type == "n"
        assert cell.number_format == "0." + "0" * places
        assert f"{cell.value:.{places}f}".replace(".", ",") == text
    else:
        assert cell.value == text and cell.data_type == "s"
    book.close()


def test_hardlink_failure_and_race(tmp_path, monkeypatch):
    import os

    doc = TableDocument([Table([Cell(0, 0, "x")], 1, 1)])
    path = tmp_path / "result.xlsx"

    def unsupported(*args):
        raise OSError("unsupported")

    monkeypatch.setattr(os, "link", unsupported)
    with pytest.raises(OSError, match="hardlinks unsupported"):
        write_workbook(doc, path)
    assert not path.exists() and not list(tmp_path.glob(".localocr-*"))

    def race(*args):
        path.write_bytes(b"competitor")
        raise FileExistsError()

    monkeypatch.setattr(os, "link", race)
    with pytest.raises(FileExistsError):
        write_workbook(doc, path)
    assert path.read_bytes() == b"competitor"
    assert not list(tmp_path.glob(".localocr-*"))


def test_overwrite_cancel_and_replace_failure(tmp_path, monkeypatch):
    import os

    path = tmp_path / "existing.xlsx"
    path.write_bytes(b"original")
    doc = TableDocument([Table([Cell(0, 0, "x")], 1, 1)])
    cancel = Event()
    cancel.set()
    with pytest.raises(Cancelled):
        write_workbook(doc, path, overwrite=True, cancel=cancel)
    assert path.read_bytes() == b"original"

    def denied(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "replace", denied)
    with pytest.raises(PermissionError):
        write_workbook(doc, path, overwrite=True)
    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob(".localocr-*"))
