"""Shared single/batch pipeline. No Qt, agent tools or cloud dependencies."""

import hashlib
import json
import logging
import time
import traceback
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event

from localocr.domain import JobResult, StructureError, Table, TableDocument, ValidationIssue
from localocr.embedded import EmbeddedSettings
from localocr.excel import write_workbook
from localocr.imaging import EXTENSIONS, Layout, detect_layout, encode, load_image, row_fragments
from localocr.ollama import Cancelled, OCRServerError, Settings
from localocr.providers import OCRProvider, OpenWebUISettings, create_provider
from localocr.tables import parse_response

LOGGER = logging.getLogger(__name__)
Progress = Callable[[int, int, str], None]


def discover(source: Path, recursive=False) -> list[Path]:
    if source.is_file():
        if source.suffix.lower() not in EXTENSIONS:
            raise ValueError("Неподдерживаемый формат изображения")
        return [source]
    if not source.is_dir():
        raise ValueError("Исходный файл или каталог не существует")
    paths = source.rglob("*") if recursive else source.iterdir()
    return sorted(
        (path for path in paths if path.is_file() and path.suffix.lower() in EXTENSIONS),
        key=lambda path: str(path).casefold(),
    )


def output_names(paths: list[Path]) -> list[str]:
    counts = Counter(path.stem.casefold() for path in paths)
    names = []
    occupied = set()
    for path in paths:
        name = path.stem
        if counts[name.casefold()] > 1:
            digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:10]
            name += f"_{path.suffix[1:].lower()}_{digest}"
        candidate = name + ".xlsx"
        while candidate.casefold() in occupied:
            name += "_"
            candidate = name + ".xlsx"
        occupied.add(candidate.casefold())
        names.append(candidate)
    return names


def apply_geometry(table: Table, layout: Layout):
    if table.rows != len(layout.ys) - 1 or table.columns != len(layout.xs) - 1:
        raise StructureError("OCR-сетка не соответствует найденным границам строк/столбцов")
    table.row_heights = [(b - a) * 0.5 for a, b in zip(layout.ys, layout.ys[1:])]
    table.column_widths = [(b - a) / 8 for a, b in zip(layout.xs, layout.xs[1:])]
    for cell in table.cells:
        cell.source_region = (
            layout.xs[cell.column],
            layout.ys[cell.row],
            layout.xs[cell.column + cell.colspan],
            layout.ys[cell.row + cell.rowspan],
        )


def assemble_fragments(parts: list[tuple[int, int, Table]], layout: Layout) -> Table:
    """Merge by geometry, using all cells in overlap to detect disagreement."""
    cells = {}
    occupied = {}
    for start, end, part in parts:
        if part.rows != end - start or part.columns != len(layout.xs) - 1:
            raise StructureError("Неполный OCR-фрагмент")
        part.grid()
        for original in part.cells:
            cell = replace(original, row=original.row + start)
            key = (cell.row, cell.column)
            if key in cells:
                previous = cells[key]
                if (previous.text, previous.rowspan, previous.colspan) != (
                    cell.text,
                    cell.rowspan,
                    cell.colspan,
                ):
                    raise StructureError("Конфликт OCR в геометрическом перекрытии; нужна проверка")
                continue
            for row in range(cell.row, cell.row + cell.rowspan):
                for column in range(cell.column, cell.column + cell.colspan):
                    if (row, column) in occupied:
                        raise StructureError("Неоднозначное объединение на границе фрагментов")
                    occupied[row, column] = key
            cells[key] = cell
    table = Table(list(cells.values()), len(layout.ys) - 1, len(layout.xs) - 1)
    table.grid()
    apply_geometry(table, layout)
    return table


def recognize_document(image, client: OCRProvider, diagnostics: Path | None):
    layouts = detect_layout(image)
    sequence = 0

    def recognize(crop, single_table=True):
        nonlocal sequence
        client.check_cancel()
        sequence += 1
        text = client.recognize(encode(crop), single_table=single_table)
        if diagnostics:
            diagnostics.mkdir(parents=True, exist_ok=True)
            (diagnostics / f"response-{sequence}.txt").write_text(text, encoding="utf-8")
        return parse_response(text)

    if not layouts:
        document = recognize(image, single_table=False)
        for table in document.tables:
            table.issues.append(
                ValidationIssue(
                    "GEOMETRY_UNKNOWN",
                    "Нет надёжной сетки линий: полнота и ориентация требуют визуальной проверки",
                )
            )
        return document
    tables = []
    for layout in layouts:
        x, y, right, bottom = layout.region
        try:
            if bottom - y > 1800:
                raise StructureError("Длинная таблица")
            document = recognize(
                image.crop(
                    (
                        max(0, x - 3),
                        max(0, y - 3),
                        min(image.width, right + 3),
                        min(image.height, bottom + 3),
                    )
                )
            )
            if len(document.tables) != 1:
                raise StructureError("Число таблиц не соответствует геометрии")
            table = document.tables[0]
            apply_geometry(table, layout)
        except StructureError, OCRServerError:
            parts: list[tuple[int, int, Table]] = []
            budget = [96]

            def read_range(start, end, depth=0):
                box = (
                    max(0, x - 3),
                    max(0, layout.ys[start] - 2),
                    min(image.width, right + 3),
                    min(image.height, layout.ys[end] + 3),
                )
                last_error = None
                for _ in range(2):
                    if budget[0] <= 0:
                        raise StructureError(
                            "Исчерпан лимит повторного OCR (96 запросов на таблицу)"
                        )
                    budget[0] -= 1
                    try:
                        doc = recognize(image.crop(box))
                        if len(doc.tables) != 1:
                            raise StructureError("Неоднозначный OCR-фрагмент")
                        part = doc.tables[0]
                        if part.rows != end - start or part.columns != len(layout.xs) - 1:
                            raise StructureError("Неполный OCR-фрагмент")
                        return [(start, end, part)]
                    except (StructureError, OCRServerError) as error:
                        last_error = error
                if end - start > 3 and depth < 5:
                    middle = (start + end) // 2
                    return read_range(start, middle + 1, depth + 1) + read_range(
                        middle, end, depth + 1
                    )
                raise last_error or StructureError("Фрагмент не восстановлен")

            for start, end in row_fragments(layout, max_height=1000):
                parts.extend(read_range(start, end))
            # Resolve only geometrically coincident observations. Two matching local
            # rechecks must confirm one original value; otherwise fail without guessing.
            observations = {}
            for start, end, part in parts:
                for cell in part.cells:
                    observations.setdefault((start + cell.row, cell.column), []).append(cell)
            for (row, column), observed in observations.items():
                signatures = {(c.text, c.rowspan, c.colspan) for c in observed}
                if len(signatures) < 2:
                    continue
                spans = {(c.rowspan, c.colspan) for c in observed}
                if len(spans) != 1:
                    raise StructureError("Конфликт объединений в перекрытии фрагментов")
                rowspan, colspan = next(iter(spans))
                first = read_range(row, row + rowspan)
                second = read_range(row, row + rowspan)
                if len(first) != 1 or len(second) != 1:
                    raise StructureError("Неоднозначная локальная повторная проверка")
                candidates = []
                for checked in [first[0][2], second[0][2]]:
                    candidate = next(
                        (c for c in checked.cells if c.row == 0 and c.column == column), None
                    )
                    candidates.append(candidate)
                if any(c is None for c in candidates):
                    raise StructureError("Не найдено положение конфликтующей ячейки")
                a, b = candidates
                assert a is not None and b is not None
                signature = (a.text, a.rowspan, a.colspan)
                confirmed = signature == (b.text, b.rowspan, b.colspan) and signature in signatures
                # Preserve an actual source observation when text remains uncertain.
                # No inferred replacement: all alternatives are exposed in REVIEW.
                chosen = a.text if confirmed else observed[0].text
                alternatives = sorted({c.text for c in observed} | {a.text, b.text})
                warning = (
                    "REVIEW: подтверждено двумя локальными проверками"
                    if confirmed
                    else "REVIEW: текст неоднозначен; сохранено первое OCR-наблюдение"
                )
                warning += "; альтернативы: " + " | ".join(alternatives)
                for cell in observed:
                    cell.text = chosen
                    cell.warnings.append(warning)
            table = assemble_fragments(parts, layout)
        tables.append(table)
    return TableDocument(tables)


def convert(
    source: Path,
    settings: Settings | OpenWebUISettings | EmbeddedSettings,
    output_dir: Path | None = None,
    recursive=False,
    overwrite=False,
    diagnostics=False,
    cancel: Event | None = None,
    progress: Progress | None = None,
    on_network_event=None,
) -> list[JobResult]:
    paths = discover(source, recursive)
    output_dir = output_dir or ((source if source.is_dir() else source.parent) / "results")
    # Exclude results if recursive input traversal includes a previous output tree.
    paths = [path for path in paths if not path.resolve().is_relative_to(output_dir.resolve())]
    if not paths:
        raise ValueError("Поддерживаемые изображения не найдены")
    cancel = cancel or Event()
    client = (
        create_provider(settings, cancel, on_network_event=on_network_event)
        if on_network_event
        else create_provider(settings, cancel)
    )
    try:
        client.doctor()
        output_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for index, (path, name) in enumerate(zip(paths, output_names(paths))):
            if cancel.is_set():
                break
            if progress:
                progress(index, len(paths), path.name)
            target = output_dir / name
            start = time.monotonic()
            try:
                if target.exists() and not overwrite:
                    result = JobResult(
                        path.name, "SKIPPED", str(target), "Результат уже существует"
                    )
                else:
                    diag = output_dir / "diagnostics" / target.stem if diagnostics else None
                    image = load_image(path)
                    document = recognize_document(image, client, diag)
                    warnings = sum(
                        len(table.issues) + sum(len(c.warnings) for c in table.cells)
                        for table in document.tables
                    )
                    write_workbook(document, target, overwrite, cancel)
                    result = JobResult(
                        path.name,
                        "REVIEW" if warnings else "SUCCESS",
                        str(target),
                        tables=len(document.tables),
                        shapes=[(t.rows, t.columns) for t in document.tables],
                        warnings=warnings,
                    )
            except Cancelled:
                break
            except Exception as error:
                # Exception details never contain raw image/OCR content in routine logs.
                LOGGER.error(
                    "Image processing failed: %s (%s)\n%s",
                    path.name,
                    type(error).__name__,
                    "".join(traceback.format_tb(error.__traceback__)),
                )
                result = JobResult(
                    path.name,
                    "FAILED",
                    message=str(error)
                    if isinstance(error, (ValueError, OCRServerError, OSError))
                    else "Ошибка обработки; см. локальный лог",
                )
            result.seconds = round(time.monotonic() - start, 3)
            results.append(result)
            LOGGER.info(
                "%s: %s tables=%s shapes=%s warnings=%s seconds=%s",
                path.name,
                result.status,
                result.tables,
                result.shapes,
                result.warnings,
                result.seconds,
            )
            if progress:
                progress(index + 1, len(paths), f"{path.name}: {result.status}")
        report = {
            "cancelled": cancel.is_set(),
            "discovered": len(paths),
            "results": [asdict(result) for result in results],
        }
        report_path = output_dir / f"report-{time.time_ns()}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return results
    finally:
        client.close()
