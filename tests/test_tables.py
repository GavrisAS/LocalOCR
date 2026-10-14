import pytest

from localocr.domain import Cell, StructureError, Table
from localocr.tables import parse_response


@pytest.mark.parametrize(
    "text", ["Кириллица Ω &amp; &lt;", "0012", "=HYPERLINK(1)", "", "a<br>b", "0О1IІСC"]
)
def test_text(text):
    table = parse_response(f"<table><tr><td>{text}</td></tr></table>").tables[0]
    assert table.rows == table.columns == 1
    assert table.cells[0].text == text.replace("&amp;", "&").replace("&lt;", "<").replace(
        "<br>", "\n"
    )


def test_combined_spans_headers_empty():
    doc = parse_response("""<table><thead><tr><th rowspan="2">А</th><th colspan="2">Б</th></tr>
    <tr><th>В</th><th></th></tr></thead><tbody><tr><td colspan="3">Г</td></tr></tbody></table>""")
    table = doc.tables[0]
    assert (table.rows, table.columns) == (3, 3)
    assert table.grid()[1, 0].text == "А"
    assert table.grid()[1, 2].text == ""
    assert table.cells[-1].colspan == 3


@pytest.mark.parametrize(
    "text",
    [
        "<table><tr><td>x",
        "<table><tr><td>x</td></tr>",
        '<table><tr><td rowspan="0">x</td></tr></table>',
        '<table><tr><td colspan="-1">x</td></tr></table>',
        '<table><tr><td rowspan="two">x</td></tr></table>',
        '<table><tr><td rowspan="2">x</td></tr></table>',
        "<table><tr><td>x</td><td>y</td></tr><tr><td>z</td></tr></table>",
        "<table><td>x</td></table>",
        "<table><tr><td>x</th></tr></table>",
        "<table><tr><td><script>alert(1)</script></td></tr></table>",
        "<script>x</script><table><tr><td>a</td></tr></table>",
        "<table><tr><td><table></table></td></tr></table>",
        '<table><tr><td colspan="100001">x</td></tr></table>',
        "ordinary prose",
        "| a | b |\n|---|---|\n|x|",
    ],
)
def test_reject_unsafe_or_incomplete(text):
    with pytest.raises(StructureError):
        parse_response(text)


def test_multiple_and_markdown():
    assert len(parse_response("<table><tr><td>1</td></tr></table>" * 2).tables) == 2
    table = parse_response("| А | Б |\n| --- | :---: |\n| 1 | |").tables[0]
    assert (table.rows, table.columns) == (2, 2)
    assert table.cells[-1].text == ""


@pytest.mark.parametrize(
    "cells,rows,columns",
    [
        ([Cell(0, 0, "a"), Cell(0, 0, "b")], 1, 1),
        ([Cell(-1, 0, "a")], 1, 1),
        ([Cell(0, 0, "a", 2)], 1, 1),
        ([Cell(0, 0, "a")], 2, 2),
        ([Cell(0, 0, "a")], 10001, 1),
    ],
)
def test_canonical_validation(cells, rows, columns):
    with pytest.raises(StructureError):
        Table(cells, rows, columns).grid()


def test_span_allocation_limit():
    with pytest.raises(StructureError, match="100000"):
        parse_response('<table><tr><td rowspan="10000" colspan="1000">x</td></tr></table>')
