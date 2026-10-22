import json

import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from localocr.cli import app
from localocr.domain import Cell, StructureError, Table
from localocr.imaging import Layout, detect_layout, load_image, row_fragments
from localocr.ollama import OCRServerError, Settings
from localocr.service import (
    assemble_fragments,
    convert,
    output_names,
    recognize_document,
    stitch_unstructured,
)


def synthetic(rows, columns, scale=40):
    image = Image.new("RGB", (columns * scale + 21, rows * scale + 21), "white")
    draw = ImageDraw.Draw(image)
    for x in range(columns + 1):
        draw.line((10 + x * scale, 10, 10 + x * scale, 10 + rows * scale), fill="black", width=2)
    for y in range(rows + 1):
        draw.line((10, 10 + y * scale, 10 + columns * scale, 10 + y * scale), fill="black", width=2)
    return image


@pytest.mark.parametrize("rows,columns", [(2, 2), (3, 5), (9, 32), (12, 50), (50, 12)])
@pytest.mark.parametrize("scale", [30, 60])
def test_geometry(rows, columns, scale):
    layouts = detect_layout(synthetic(rows, columns, scale))
    assert len(layouts) == 1
    assert (len(layouts[0].ys) - 1, len(layouts[0].xs) - 1) == (rows, columns)
    parts = row_fragments(layouts[0], max_height=500)
    assert parts[0][0] == 0 and parts[-1][1] == rows


def test_exif_and_deskew(tmp_path):
    image = synthetic(3, 5, 60)
    exif = Image.Exif()
    exif[274] = 6
    path = tmp_path / "exif.jpg"
    image.save(path, exif=exif)
    normalized = load_image(path)
    assert normalized.size == (image.height, image.width)
    path = tmp_path / "skew.png"
    image.rotate(3, expand=True, fillcolor="white").save(path)
    corrected = load_image(path)
    assert detect_layout(corrected)


def test_fragment_geometry_not_text():
    layout = Layout((0, 0, 20, 40), [0, 10, 20], [0, 10, 20, 30, 40])

    def part(start, end):
        return Table(
            [Cell(r, c, "same repeated text") for r in range(end - start) for c in range(2)],
            end - start,
            2,
        )

    table = assemble_fragments([(0, 3, part(0, 3)), (2, 4, part(2, 4))], layout)
    assert table.rows == 4 and len(table.cells) == 8
    conflict = part(2, 4)
    conflict.cells[0].text = "conflict"
    reviewed = assemble_fragments([(0, 3, part(0, 3)), (2, 4, conflict)], layout)
    assert any(cell.warnings for cell in reviewed.cells)
    with pytest.raises(StructureError):
        assemble_fragments([(0, 4, part(0, 3))], layout)


def test_unstructured_overlap_stitch_is_conservative():
    first = Table([Cell(row, 0, text) for row, text in enumerate(["A", "B", "C"])], 3, 1)
    second = Table([Cell(row, 0, text) for row, text in enumerate(["B", "C", "D"])], 3, 1)
    result = stitch_unstructured([(0, 500, first), (400, 900, second)])
    assert [result.grid()[row, 0].text for row in range(4)] == ["A", "B", "C", "D"]
    assert result.issues[0].code == "GEOMETRY_UNKNOWN"

    conflict = Table([Cell(row, 0, text) for row, text in enumerate(["B", "X", "D"])], 3, 1)
    with pytest.raises(StructureError, match="однозначно сопоставить"):
        stitch_unstructured([(0, 500, first), (400, 900, conflict)])


def test_no_grid_truncation_retries_smaller_and_records_private_diagnostics(tmp_path):
    class Client:
        server_name = "synthetic"
        settings = type("SettingsView", (), {"model": "synthetic", "num_predict": 1000})()
        on_network_event = None
        on_runtime_status = None

        def __init__(self):
            self.calls = 0
            self.last_diagnostic = {}

        def check_cancel(self):
            return None

        def doctor(self):
            return "ready"

        def close(self):
            return None

        def recognize(self, image, *, single_table=False):
            self.calls += 1
            if self.calls == 1:
                self.last_diagnostic = {
                    "endpoint": "http://127.0.0.1:11434/api/generate",
                    "done": True,
                    "done_reason": "length",
                    "response_length": 14,
                }
                raise OCRServerError("truncated", self.last_diagnostic)
            rows = (
                [("A", "1"), ("B", "2"), ("C", "3")]
                if self.calls == 2
                else [("B", "2"), ("C", "3"), ("D", "4")]
            )
            self.last_diagnostic = {
                "endpoint": "http://127.0.0.1:11434/api/generate",
                "done": True,
                "done_reason": "stop",
            }
            return (
                "<table>"
                + "".join(f"<tr><td>{left}</td><td>{right}</td></tr>" for left, right in rows)
                + "</table>"
            )

    client = Client()
    image = Image.new("RGB", (800, 900), "white")
    ImageDraw.Draw(image).text((10, 10), "table rows", fill="black")
    document = recognize_document(image, client, tmp_path)
    assert client.calls == 3
    assert document.tables[0].rows == 4
    assert document.tables[0].issues[0].code == "GEOMETRY_UNKNOWN"
    report = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert report["status"] == "REVIEW"
    assert report["requests"][0]["provider"]["done_reason"] == "length"
    assert report["requests"][1]["route"] == "adaptive-page-fragment"
    sidecar = json.loads((tmp_path / "observations.json").read_text(encoding="utf-8"))
    assert sidecar["tables"][0]["cells"][-2]["text"] == "D"

    blank_client = Client()
    with pytest.raises(StructureError, match="видимого текста"):
        recognize_document(Image.new("RGB", (800, 900), "white"), blank_client, None)
    assert blank_client.calls == 0


def test_multiple_tables():
    image = Image.new("RGB", (300, 300), "white")
    image.paste(synthetic(2, 2), (0, 0))
    image.paste(synthetic(2, 3), (0, 160))
    assert len(detect_layout(image)) == 2


def test_cli_batch_unicode_collisions_errors(server, tmp_path, monkeypatch):
    url, state = server
    folder = tmp_path / "Русская папка"
    folder.mkdir()
    synthetic(2, 2).save(folder / "таблица.png")
    synthetic(2, 2).save(folder / "таблица.bmp")
    (folder / "bad.jpg").write_bytes(b"broken")
    (folder / "document.pdf").write_bytes(b"not supported")
    runner = CliRunner()
    result = runner.invoke(app, ["convert", str(folder), "--ollama-url", url])
    assert result.exit_code == 1, result.output
    paths = list((folder / "results").glob("*.xlsx"))
    assert len(paths) == 2 and len({p.name for p in paths}) == 2
    assert "Ошибок: 1" in result.output
    result = runner.invoke(app, ["convert", str(folder), "--ollama-url", url])
    assert "Пропущено: 2" in result.output
    result = runner.invoke(
        app,
        [
            "convert",
            str(folder / "таблица.png"),
            "--ollama-url",
            url,
            "--output-dir",
            str(tmp_path / "single"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "single" / "таблица.xlsx").exists()
    assert runner.invoke(app, ["--version"]).output.strip() == __import__("localocr").__version__
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["doctor", "--ollama-url", url]).exit_code == 0
    assert (
        runner.invoke(app, ["convert", str(folder), "--ollama-url", "http://127.0.0.1:1"]).exit_code
        == 3
    )
    assert runner.invoke(app, ["convert", str(tmp_path / "missing")]).exit_code == 2
    assert runner.invoke(app, ["convert", str(folder), "--ollama-url", "ftp://bad"]).exit_code == 2


def test_recursive_and_no_grid_review(server, tmp_path, visible_text):
    url, _ = server
    folder = tmp_path / "sub"
    folder.mkdir()
    visible_text(Image.new("RGB", (100, 100), "white")).save(folder / "x.webp")
    results = convert(tmp_path, Settings(url=url), recursive=True)
    assert results[0].status == "REVIEW"
    assert results[0].warnings == 1
    names = output_names([folder / "a.jpg", folder / "a.png", tmp_path / "a.jpg"])
    assert len(set(names)) == 3


def test_long_table_recovery(server, tmp_path):
    url, state = server
    image = synthetic(50, 2, 40)
    path = tmp_path / "long.png"
    image.save(path)
    # Server payload decodes crop dimensions: realistic independent mock for each fragment.
    from localocr.imaging import detect_layout
    from localocr.ollama import OllamaClient

    original = OllamaClient.recognize

    def recognize(self, encoded, *, single_table=False):
        import io

        crop = Image.open(io.BytesIO(encoded))
        layout = detect_layout(crop)[0]
        rows = len(layout.ys) - 1
        return (
            "<table>" + "".join("<tr><td>x</td><td>y</td></tr>" for _ in range(rows)) + "</table>"
        )

    from unittest.mock import patch

    with patch.object(OllamaClient, "recognize", recognize):
        results = convert(path, Settings(url=url))
    assert results[0].status == "SUCCESS"
    assert results[0].shapes == [(50, 2)]
    assert original is not None


def test_partial_line_multilevel_header():
    # Internal header separator spans only two of ten columns.
    image = synthetic(5, 10, 50)
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 58, 512, 63), fill="white")
    for x in range(10, 511, 50):
        draw.line((x, 10, x, 260), fill="black", width=2)
    draw.line((410, 60, 510, 60), fill="black", width=2)
    layout = detect_layout(image)[0]
    assert len(layout.ys) - 1 == 5


@pytest.mark.parametrize("mode", ["incomplete", "conflict", "unresolved"])
def test_adaptive_local_recovery(server, tmp_path, monkeypatch, mode):
    import io

    from localocr.ollama import OllamaClient

    path = tmp_path / "long.png"
    synthetic(50, 2, 40).save(path)
    calls = []

    def recognize(self, encoded, *, single_table=False):
        crop = Image.open(io.BytesIO(encoded))
        rows = len(detect_layout(crop)[0].ys) - 1
        calls.append(rows)
        count = rows - 1 if mode == "incomplete" and rows > 10 else rows
        values = [("x", "y") for _ in range(count)]
        if mode in {"conflict", "unresolved"} and len(calls) == 2:
            values[0] = ("conflicting", "y")
        if mode == "unresolved" and rows == 1:
            values[0] = ("third value", "y")
        return (
            "<table>"
            + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in values)
            + "</table>"
        )

    monkeypatch.setattr(OllamaClient, "recognize", recognize)
    result = convert(path, Settings(url=server[0]))[0]
    expected = {"incomplete": "SUCCESS", "conflict": "REVIEW", "unresolved": "REVIEW"}[mode]
    assert result.status == expected
    assert len(calls) <= 96
    if mode == "incomplete":
        assert min(calls) <= 10 and result.shapes == [(50, 2)]
    else:
        assert calls.count(1) == 2
