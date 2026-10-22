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
from localocr.imaging import (
    EXTENSIONS,
    Layout,
    detect_layout,
    encode,
    has_visible_text,
    load_image,
    row_fragments,
)
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
        raise StructureError(
            f"OCR-сетка {table.rows}×{table.columns} не совпадает с геометрией "
            f"{len(layout.ys) - 1}×{len(layout.xs) - 1}"
        )
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
                    if (previous.rowspan, previous.colspan) != (cell.rowspan, cell.colspan):
                        raise StructureError(
                            "Конфликт объединений в геометрическом перекрытии "
                            f"(строка {key[0] + 1}, столбец {key[1] + 1})"
                        )
                    alternatives = sorted({previous.text, cell.text})
                    previous.warnings.append(
                        "REVIEW: OCR-фрагменты расходятся; сохранено первое наблюдение; "
                        "альтернативы: " + " | ".join(alternatives)
                    )
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


def _table_row_signatures(table: Table) -> list[tuple]:
    grid = table.grid()
    return [
        tuple(
            (
                grid[row, column].text,
                grid[row, column].row == row,
                grid[row, column].rowspan,
                grid[row, column].colspan,
            )
            for column in range(table.columns)
        )
        for row in range(table.rows)
    ]


def stitch_unstructured(parts: list[tuple[int, int, Table]]) -> Table:
    if not parts:
        raise StructureError("Не получены пригодные OCR-фрагменты страницы")
    first = parts[0][2]
    cells = [replace(cell) for cell in first.cells]
    rows = first.rows
    columns = first.columns
    for _, _, part in parts[1:]:
        if part.columns != columns:
            raise StructureError("Число столбцов различается в перекрывающихся фрагментах")
        existing = Table(cells, rows, columns)
        previous_signatures = _table_row_signatures(existing)
        next_signatures = _table_row_signatures(part)
        overlaps = [
            count
            for count in range(1, min(len(previous_signatures), len(next_signatures)) + 1)
            if previous_signatures[-count:] == next_signatures[:count]
        ]
        if not overlaps:
            raise StructureError("Не удалось однозначно сопоставить строки перекрытия фрагментов")
        overlap = max(overlaps)
        offset = rows - overlap
        existing_grid = existing.grid()
        for cell in part.cells:
            mapped = replace(cell, row=cell.row + offset)
            if mapped.row < rows:
                previous = existing_grid.get((mapped.row, mapped.column))
                if previous is None or (
                    previous.row,
                    previous.column,
                    previous.text,
                    previous.rowspan,
                    previous.colspan,
                    previous.is_header,
                ) != (
                    mapped.row,
                    mapped.column,
                    mapped.text,
                    mapped.rowspan,
                    mapped.colspan,
                    mapped.is_header,
                ):
                    raise StructureError("Конфликт OCR в перекрытии фрагментов страницы")
            else:
                cells.append(mapped)
        rows += part.rows - overlap
    result = Table(cells, rows, columns)
    result.grid()
    result.issues.append(
        ValidationIssue(
            "GEOMETRY_UNKNOWN",
            "Строки объединены по совпадающему OCR-перекрытию; положение столбцов требует проверки",
        )
    )
    return result


def recognize_document(
    image, client: OCRProvider, diagnostics: Path | None, source_name: str | None = None
):
    layouts = detect_layout(image)
    sequence = 0
    active_stage = "layout"
    started = time.monotonic()
    settings = getattr(client, "settings", None)
    embedded = getattr(client, "embedded", None)
    requests: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    trace: dict[str, object] = {
        "schema_version": 1,
        "source": source_name,
        "image": {"width": image.width, "height": image.height},
        "provider": {
            "server": getattr(client, "server_name", type(client).__name__),
            "model": (
                f"Embedded {embedded.precision.upper()}"
                if embedded is not None
                else getattr(settings, "model", None)
            ),
            "generation": {
                "num_predict": getattr(settings, "num_predict", None),
                "context_size": getattr(embedded, "ctx_size", 32768),
                "temperature": 0,
                "seed": 0,
            },
        },
        "layouts": [
            {
                "region": layout.region,
                "xs": layout.xs,
                "ys": layout.ys,
                "confidence": layout.confidence,
            }
            for layout in layouts
        ],
        "requests": requests,
        "events": events,
    }

    def save_diagnostics(status, error=None, document=None):
        if diagnostics is None:
            return
        diagnostics.mkdir(parents=True, exist_ok=True)
        trace["status"] = status
        trace["request_count"] = len(requests)
        trace["retry_count"] = max(0, trace["request_count"] - 1)
        trace["duration_seconds"] = round(time.monotonic() - started, 3)
        if error is not None:
            trace["failure"] = {
                "stage": active_stage,
                "type": type(error).__name__,
                "message": str(error)[:500],
                "provider": getattr(error, "diagnostics", {}),
            }
        if document is not None:
            trace["table_results"] = [
                {
                    "shape": [table.rows, table.columns],
                    "issue_codes": [issue.code for issue in table.issues],
                    "cell_warning_count": sum(bool(cell.warnings) for cell in table.cells),
                }
                for table in document.tables
            ]
        (diagnostics / "run.json").write_text(
            json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if document is not None:
            (diagnostics / "observations.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tables": [
                            {
                                "rows": table.rows,
                                "columns": table.columns,
                                "cells": [
                                    {
                                        "row": cell.row,
                                        "column": cell.column,
                                        "rowspan": cell.rowspan,
                                        "colspan": cell.colspan,
                                        "text": cell.text,
                                    }
                                    for cell in table.cells
                                ],
                            }
                            for table in document.tables
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    def recognize(crop, single_table=True, region=None, route="whole-table"):
        nonlocal sequence
        client.check_cancel()
        sequence += 1
        started = time.monotonic()
        record: dict[str, object] = {
            "request": sequence,
            "route": route,
            "region": region,
            "single_table": single_table,
            "started": time.time(),
        }
        try:
            text = client.recognize(encode(crop), single_table=single_table)
            record.update(getattr(client, "last_diagnostic", {}))
            record["response_length"] = record.get("response_length", len(text))
            record["status"] = "RESPONSE"
            if diagnostics is not None:
                diagnostics.mkdir(parents=True, exist_ok=True)
                (diagnostics / f"response-{sequence}.txt").write_text(text, encoding="utf-8")
            try:
                document = parse_response(text)
            except StructureError as error:
                record.update({"status": "PARSER_OR_VALIDATION_ERROR", "error": str(error)[:500]})
                raise
            record["tables"] = len(document.tables)
            record["shapes"] = [[table.rows, table.columns] for table in document.tables]
            return document
        except Exception as error:
            record.update(
                {
                    "status": record.get("status", "PROVIDER_ERROR"),
                    "error_type": type(error).__name__,
                    "error": str(error)[:500],
                    "provider": getattr(error, "diagnostics", {})
                    or getattr(client, "last_diagnostic", {}),
                }
            )
            raise
        finally:
            record["seconds"] = round(time.monotonic() - started, 3)
            requests.append(record)

    try:
        if not layouts:
            active_stage = "whole-page OCR"
            if not has_visible_text(image):
                raise StructureError("Недостаточно видимого текста для подтверждения таблицы")
            max_height = max(600, min(1800, 10_000_000 // max(1, image.width)))
            overlap = max(80, min(240, max_height // 8))

            def read_page(top, bottom, depth=0, budget=None, force_split=False):
                if budget is None:
                    budget = [48]
                if budget[0] <= 0:
                    raise StructureError("Исчерпан лимит повторного OCR страницы (48 запросов)")

                def split_page(error):
                    if depth >= 6 or bottom - top <= max(240, overlap * 2):
                        raise error
                    middle = (top + bottom) // 2
                    context = max(40, min(overlap, (bottom - top) // 8))
                    left_end = min(bottom, middle + context)
                    right_start = max(top, middle - context)
                    if left_end >= bottom or right_start <= top:
                        raise error
                    return read_page(top, left_end, depth + 1, budget) + read_page(
                        right_start, bottom, depth + 1, budget
                    )

                if force_split and bottom - top > max(240, overlap * 2):
                    return split_page(StructureError("Сбой OCR страницы требует меньших регионов"))
                budget[0] -= 1
                try:
                    document = recognize(
                        image.crop((0, top, image.width, bottom)),
                        single_table=False,
                        region=(0, top, image.width, bottom),
                        route="adaptive-page-fragment",
                    )
                    if len(document.tables) != 1:
                        raise StructureError("Внутри фрагмента найдено несколько таблиц")
                    if document.tables[0].columns < 2:
                        raise StructureError(
                            "Без сетки нельзя подтвердить положение единственного столбца"
                        )
                    return [(top, bottom, document.tables[0])]
                except (StructureError, OCRServerError) as error:
                    events.append(
                        {
                            "stage": "adaptive page fragmentation",
                            "region": (0, top, image.width, bottom),
                            "type": type(error).__name__,
                            "message": str(error)[:500],
                        }
                    )
                    return split_page(error)

            force_page_split = False
            if image.height <= max_height:
                try:
                    document = recognize(
                        image,
                        single_table=False,
                        region=(0, 0, image.width, image.height),
                        route="whole-page",
                    )
                    if any(table.rows < 2 or table.columns < 2 for table in document.tables):
                        raise StructureError(
                            "Без сетки недостаточно повторяющейся структуры строк и столбцов"
                        )
                    for table in document.tables:
                        table.issues.append(
                            ValidationIssue(
                                "GEOMETRY_UNKNOWN",
                                "Нет надёжных линий: полнота и положение ячеек требуют визуальной проверки",
                            )
                        )
                    save_diagnostics("REVIEW", document=document)
                    return document
                except (StructureError, OCRServerError) as error:
                    active_stage = "adaptive page fragmentation"
                    force_page_split = True
                    events.append(
                        {
                            "stage": "whole-page OCR",
                            "region": (0, 0, image.width, image.height),
                            "type": type(error).__name__,
                            "message": str(error)[:500],
                        }
                    )
            else:
                active_stage = "adaptive page fragmentation"
            parts = []
            top = 0
            budget = [48]
            while top < image.height:
                bottom = min(image.height, top + max_height)
                parts.extend(read_page(top, bottom, budget=budget, force_split=force_page_split))
                if bottom == image.height:
                    break
                top = max(top + 1, bottom - overlap)
            table = stitch_unstructured(parts)
            if table.rows < 2 or table.columns < 2:
                raise StructureError(
                    "Без сетки недостаточно повторяющейся структуры строк и столбцов"
                )
            document = TableDocument([table])
            save_diagnostics("REVIEW", document=document)
            return document

        tables = []
        for layout in layouts:
            x, y, right, bottom = layout.region
            table_region = (
                max(0, x - 3),
                max(0, y - 3),
                min(image.width, right + 3),
                min(image.height, bottom + 3),
            )
            try:
                max_height = max(600, min(1800, 10_000_000 // max(1, right - x)))
                if bottom - y > max_height:
                    raise StructureError("Размер таблицы требует масштабной фрагментации")
                active_stage = "whole-table OCR"
                document = recognize(
                    image.crop(table_region),
                    region=table_region,
                    route="whole-table",
                )
                if len(document.tables) != 1:
                    raise StructureError("Число таблиц не соответствует геометрии")
                active_stage = "geometry validation"
                table = document.tables[0]
                apply_geometry(table, layout)
            except (StructureError, OCRServerError) as error:
                events.append(
                    {
                        "stage": active_stage,
                        "region": table_region,
                        "type": type(error).__name__,
                        "message": str(error)[:500],
                    }
                )
                active_stage = "row-fragment OCR"
                parts: list[tuple[int, int, Table]] = []
                budget = [48]

                def read_range(start, end, depth=0):
                    box = (
                        max(0, x - 3),
                        max(0, layout.ys[start] - 2),
                        min(image.width, right + 3),
                        min(image.height, layout.ys[end] + 3),
                    )
                    if budget[0] <= 0:
                        raise StructureError("Исчерпан лимит повторного OCR таблицы (48 запросов)")
                    budget[0] -= 1
                    try:
                        doc = recognize(
                            image.crop(box),
                            region=box,
                            route="row-fragment",
                        )
                        if len(doc.tables) != 1:
                            raise StructureError("Неоднозначный OCR-фрагмент")
                        part = doc.tables[0]
                        if part.rows != end - start or part.columns != len(layout.xs) - 1:
                            raise StructureError(
                                f"OCR-фрагмент {part.rows}×{part.columns} не совпадает "
                                f"с ожидаемой геометрией {end - start}×{len(layout.xs) - 1}"
                            )
                        return [(start, end, part)]
                    except (StructureError, OCRServerError) as error:
                        events.append(
                            {
                                "stage": "row-fragment validation",
                                "region": box,
                                "type": type(error).__name__,
                                "message": str(error)[:500],
                            }
                        )
                        if end - start <= 3 or depth >= 6:
                            raise error
                        middle = (start + end) // 2
                        half = (end - start) // 2
                        context = min(2, max(1, half - 1))
                        left_end = min(end, middle + context)
                        right_start = max(start, middle - context)
                        if left_end >= end or right_start <= start:
                            raise error
                        return read_range(start, left_end, depth + 1) + read_range(
                            right_start, end, depth + 1
                        )

                max_height = max(600, min(1800, 10_000_000 // max(1, right - x)))
                for start, end in row_fragments(layout, max_height=max_height):
                    parts.extend(read_range(start, end))
                observations = {}
                for start, end, part in parts:
                    for cell in part.cells:
                        observations.setdefault((start + cell.row, cell.column), []).append(cell)
                for (row, column), observed in observations.items():
                    signatures = {(cell.text, cell.rowspan, cell.colspan) for cell in observed}
                    if len(signatures) < 2:
                        continue
                    spans = {(cell.rowspan, cell.colspan) for cell in observed}
                    if len(spans) != 1:
                        raise StructureError("Конфликт объединений в перекрытии фрагментов")
                    rowspan, _ = next(iter(spans))
                    first = read_range(row, row + rowspan)
                    second = read_range(row, row + rowspan)
                    if len(first) != 1 or len(second) != 1:
                        raise StructureError("Неоднозначная локальная повторная проверка")
                    candidates = []
                    for checked in (first[0][2], second[0][2]):
                        candidates.append(
                            next(
                                (
                                    cell
                                    for cell in checked.cells
                                    if cell.row == 0 and cell.column == column
                                ),
                                None,
                            )
                        )
                    if any(candidate is None for candidate in candidates):
                        raise StructureError("Не найдено положение конфликтующей ячейки")
                    first_cell, second_cell = candidates
                    assert first_cell is not None and second_cell is not None
                    candidate_signature = (
                        first_cell.text,
                        first_cell.rowspan,
                        first_cell.colspan,
                    )
                    confirmed = (
                        candidate_signature
                        == (second_cell.text, second_cell.rowspan, second_cell.colspan)
                        and candidate_signature in signatures
                    )
                    selected = first_cell.text if confirmed else observed[0].text
                    alternatives = sorted(
                        {cell.text for cell in observed} | {first_cell.text, second_cell.text}
                    )
                    message = (
                        "REVIEW: подтверждено двумя локальными проверками"
                        if confirmed
                        else "REVIEW: текст неоднозначен; сохранено первое OCR-наблюдение"
                    )
                    message += "; альтернативы: " + " | ".join(alternatives)
                    for cell in observed:
                        cell.text = selected
                        cell.warnings.append(message)
                active_stage = "fragment assembly"
                table = assemble_fragments(parts, layout)
            if layout.confidence == "partial":
                table.issues.append(
                    ValidationIssue(
                        "PARTIAL_GRID",
                        "Часть линий таблицы подтверждена; положение ячеек требует проверки",
                    )
                )
            tables.append(table)
        document = TableDocument(tables)
        status = (
            "REVIEW"
            if any(table.issues or any(cell.warnings for cell in table.cells) for table in tables)
            else "SUCCESS"
        )
        save_diagnostics(status, document=document)
        return document
    except BaseException as error:
        save_diagnostics("FAILED", error=error)
        raise


def convert(
    source: Path,
    settings: Settings | OpenWebUISettings | EmbeddedSettings,
    output_dir: Path | None = None,
    recursive=False,
    overwrite=False,
    diagnostics: bool | Path = False,
    cancel: Event | None = None,
    progress: Progress | None = None,
    on_network_event=None,
    on_runtime_status=None,
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
    if on_runtime_status:
        client.on_runtime_status = on_runtime_status
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
                    from localocr.runtime import portable_root

                    if isinstance(diagnostics, Path):
                        diag = diagnostics / target.stem
                    else:
                        diag = (
                            portable_root() / "diagnostics" / target.stem if diagnostics else None
                        )
                    image = load_image(path)
                    document = recognize_document(image, client, diag, source_name=path.name)
                    warnings = sum(
                        len(table.issues) + sum(len(c.warnings) for c in table.cells)
                        for table in document.tables
                    )
                    write_workbook(document, target, overwrite, cancel)
                    review_codes = list(
                        dict.fromkeys(
                            [issue.code for table in document.tables for issue in table.issues]
                            + [
                                "OCR_OVERLAP_CONFLICT"
                                for table in document.tables
                                if any(cell.warnings for cell in table.cells)
                            ]
                        )
                    )
                    result = JobResult(
                        path.name,
                        "REVIEW" if warnings else "SUCCESS",
                        str(target),
                        message=("Требуется проверка: " + ", ".join(review_codes))
                        if warnings
                        else "",
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
