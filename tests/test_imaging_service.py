import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from localocr.cli import app
from localocr.domain import Cell, StructureError, Table
from localocr.imaging import Layout, detect_layout, load_image, row_fragments
from localocr.ollama import Settings
from localocr.service import assemble_fragments, convert, output_names


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
    with pytest.raises(StructureError):
        assemble_fragments([(0, 3, part(0, 3)), (2, 4, conflict)], layout)
    with pytest.raises(StructureError):
        assemble_fragments([(0, 4, part(0, 3))], layout)


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
    assert runner.invoke(app, ["--version"]).output.strip() == "0.1"
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["doctor", "--ollama-url", url]).exit_code == 0
    assert (
        runner.invoke(app, ["convert", str(folder), "--ollama-url", "http://127.0.0.1:1"]).exit_code
        == 3
    )
    assert runner.invoke(app, ["convert", str(tmp_path / "missing")]).exit_code == 2
    assert runner.invoke(app, ["convert", str(folder), "--ollama-url", "ftp://bad"]).exit_code == 2


def test_recursive_and_no_grid_review(server, tmp_path):
    url, _ = server
    folder = tmp_path / "sub"
    folder.mkdir()
    Image.new("RGB", (100, 100), "white").save(folder / "x.webp")
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

    def recognize(self, encoded):
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
