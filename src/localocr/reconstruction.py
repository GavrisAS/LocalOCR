"""Bounded, evidence-based reconstruction; HTML and line geometry are hypotheses."""

import time
from dataclasses import asdict, replace
from pathlib import Path

from localocr.domain import (
    PIPELINE_VERSION,
    Cell,
    CellProvenance,
    Evidence,
    StructureError,
    Table,
    TableDocument,
    TextObservation,
    ValidationIssue,
)
from localocr.imaging import (
    content_mask,
    detect_layout,
    encode,
    grid_hypothesis,
    has_visible_text,
    region_has_ink,
    row_fragments,
    source_polygon,
)
from localocr.journal import atomic_json
from localocr.ollama import OCRServerError
from localocr.tables import observe_rows, parse_response


def recognize_document(image, client, diagnostics: Path | None, source_name=None):
    started = time.monotonic()
    initial_http_calls = getattr(client, "http_ocr_calls", 0)
    settings = getattr(client, "settings", None)
    max_calls = getattr(settings, "max_calls", 24)
    client.image_deadline = started + getattr(settings, "max_image_seconds", 180)
    client.request_budget_remaining = max_calls
    max_seconds = getattr(settings, "max_image_seconds", 180)
    requests = []
    observations: list[TextObservation] = []
    events = []
    tables = []
    document_issues = []
    layout_started = time.monotonic()
    layouts = detect_layout(image)
    hypotheses = [grid_hypothesis(image, layout) for layout in layouts]
    ink = content_mask(image)
    layout_seconds = time.monotonic() - layout_started
    trace: dict = {
        "schema_version": 2,
        "pipeline": PIPELINE_VERSION,
        "image": {"width": image.width, "height": image.height},
        "coordinate_space": "normalized-image",
        "normalization": image.info.get("localocr_normalization"),
        "source": source_name,
        "model_identity": getattr(client, "model_identity", {"digest": None}),
        "layouts": [asdict(layout) for layout in layouts],
        "hypotheses": [asdict(h) for h in hypotheses],
        "requests": requests,
        "events": events,
        "budget": {"calls": max_calls, "seconds": max_seconds},
        "stage_seconds": {"layout_and_ink": round(layout_seconds, 4)},
    }

    def available():
        client.check_cancel()
        return (
            len(requests) < max_calls
            and getattr(client, "request_budget_remaining", 1) > 0
            and time.monotonic() - started < max_seconds
        )

    def read(box, single_table=True, route="whole-table"):
        if not available():
            raise StructureError("IMAGE_BUDGET_EXHAUSTED")
        crop = image.crop(box)
        record = {
            "request": len(requests) + 1,
            "region": box,
            "route": route,
            "image_size": crop.size,
            "encoding": "RGB/PNG",
            "retry": route not in {"whole-table", "whole-page"},
        }
        before = time.monotonic()
        try:
            encoding_started = time.monotonic()
            encoded = encode(crop)
            record["encode_seconds"] = round(time.monotonic() - encoding_started, 6)
            provider_started = time.monotonic()
            try:
                text = client.recognize(encoded, single_table=single_table)
            finally:
                record["provider_seconds"] = round(time.monotonic() - provider_started, 6)
            record.update(getattr(client, "last_diagnostic", {}))
            observations.append(TextObservation(box, record["request"], "Table Recognition:", text))
            if diagnostics is not None:
                diagnostics.mkdir(parents=True, exist_ok=True)
                (diagnostics / f"response-{record['request']}.txt").write_text(
                    text, encoding="utf-8"
                )
            parse_started = time.monotonic()
            try:
                parsed = parse_response(text)
            finally:
                record["parse_seconds"] = round(time.monotonic() - parse_started, 6)
            record["status"] = "PARSED"
            record["shapes"] = [(t.rows, t.columns) for t in parsed.tables]
            return parsed
        except (StructureError, OCRServerError) as error:
            if isinstance(error, OCRServerError) and any(
                code in str(error)
                for code in (
                    "CONNECT_",
                    "DNS_ERROR",
                    "TLS_",
                    "PROXY_ERROR",
                    "NETWORK_ERROR",
                    "HTTP 401",
                    "HTTP 403",
                    "HTTP 404",
                    "HTTP_REDIRECT",
                )
            ):
                # Cropping cannot repair an unavailable/unauthorized backend.
                # Retain accepted data and let the next image start a fresh budget.
                client.request_budget_remaining = 0
            record.update(
                status="REJECTED",
                error=str(error)[:300],
                error_type=type(error).__name__,
                provider=getattr(error, "diagnostics", {}),
            )
            raise
        finally:
            record["seconds"] = round(time.monotonic() - before, 4)
            requests.append(record)

    def annotate_unplaced(table, region, partial=False):
        for cell in table.cells:
            cell.source_region = region
            cell.provenance = CellProvenance("unverified", [Evidence("ocr-region", region)])
        table.issues.append(
            ValidationIssue(
                "UNPLACED_OBSERVATION",
                "OCR-таблица: координаты строк/столбцов и полнота не подтверждены; "
                "source region относится ко всему наблюдению",
                source_region=region,
            )
        )
        if partial:
            table.issues.append(
                ValidationIssue(
                    "INCOMPLETE_COVERAGE", "Извлечена часть изображения", source_region=region
                )
            )
        return table

    def closed_runs(observation):
        """Retain contiguous closed rectangular row observations without assigning
        them source-grid coordinates. A malformed merge never crosses into a run.
        """
        try:
            rows = observe_rows(observation.text)
        except StructureError:
            return []
        runs = []
        run = []
        width = 0
        blocked_until = 0

        def flush():
            if len(run) >= 2 and width >= 2:
                cells = []
                for row_index, row in enumerate(run):
                    column = 0
                    for cell in row:
                        cells.append(replace(cell, row=row_index, column=column))
                        column += cell.colspan
                table = Table(cells, len(run), width)
                table.grid()
                runs.append(annotate_unplaced(table, observation.region, partial=True))

        for index, row in enumerate(rows):
            if any(c.rowspan > 1 for c in row):
                blocked_until = max(blocked_until, max(index + c.rowspan for c in row))
            current_width = sum(c.colspan for c in row)
            if index < blocked_until or current_width < 2:
                flush()
                run, width = [], 0
                continue
            if run and current_width != width:
                flush()
                run = []
            width = current_width
            run.append(row)
        flush()
        return runs

    def reconstruct(layout, hypothesis):
        rows, columns = len(layout.ys) - 1, len(layout.xs) - 1
        accepted = {}
        occupied = set()
        alternatives = []
        failed = []

        def accept(table, start, end, request_number):
            if table.rows != end - start or table.columns != columns:
                raise StructureError("GRID_SHAPE_DISAGREEMENT")
            table.grid()
            # Exact crop shape is necessary but never sufficient evidence.
            for cell in table.cells:
                row, column = start + cell.row, cell.column
                region = (
                    layout.xs[column],
                    layout.ys[row],
                    layout.xs[column + cell.colspan],
                    layout.ys[row + cell.rowspan],
                )
                if not hypothesis.supports_span(row, column, cell.rowspan, cell.colspan):
                    failed.append((row, column, region, "BOUNDARY_OR_SPAN_UNCONFIRMED"))
                    continue
                if not cell.text.strip() and region_has_ink(ink, region):
                    failed.append((row, column, region, "VISIBLE_INK_WITHOUT_TEXT"))
                    continue
                key = row, column
                if key in accepted:
                    previous = accepted[key]
                    if (previous.text, previous.rowspan, previous.colspan) != (
                        cell.text,
                        cell.rowspan,
                        cell.colspan,
                    ):
                        previous.warnings.append(
                            "OCR_CONFLICT: наблюдения расходятся; требуется проверка"
                        )
                        previous.provenance.state = "unverified"
                    continue
                slots = {
                    (r, c)
                    for r in range(row, row + cell.rowspan)
                    for c in range(column, column + cell.colspan)
                }
                if slots & occupied:
                    failed.append((row, column, region, "SPAN_CONFLICT"))
                    continue
                copied = replace(cell, row=row, source_region=region, warnings=list(cell.warnings))
                copied.provenance = CellProvenance(
                    "unverified" if cell.text.strip() else "observed-empty",
                    [
                        Evidence("ocr-table", region, request_number),
                        Evidence("four-boundaries", region),
                        Evidence(
                            "scale-agreement" if hypothesis.scale_stable else "scale-disagreement",
                            region,
                        ),
                    ],
                )
                accepted[key] = copied
                occupied.update(slots)

        def read_range(start, end, depth=0):
            if not available():
                return
            box = (
                max(0, layout.region[0] - 3),
                max(0, layout.ys[start] - 3),
                min(image.width, layout.region[2] + 3),
                min(image.height, layout.ys[end] + 4),
            )
            try:
                parsed = read(box, route="whole-table" if depth == 0 else "row-fragment")
                if len(parsed.tables) != 1:
                    raise StructureError("TABLE_COUNT_DISAGREEMENT")
                table = parsed.tables[0]
                if table.rows != end - start or table.columns != columns:
                    alternatives.append((table, box))
                before = len(occupied)
                accept(table, start, end, len(requests))
                if len(occupied) - before == (end - start) * columns:
                    return
                # Known good anchors are retained. Re-OCR only failed row groups.
                unresolved_rows = [
                    r
                    for r in range(start, end)
                    if any((r, c) not in occupied for c in range(columns))
                ]
                if not unresolved_rows:
                    return
            except (StructureError, OCRServerError) as error:
                events.append(
                    {"region": box, "code": type(error).__name__, "reason": str(error)[:200]}
                )
            # An invalid merge/ragged row cannot erase independently applicable
            # rows. Placement is allowed only when *all* source row positions in
            # the crop are present, and the particular row is unambiguous.
            if observations and observations[-1].region == box:
                try:
                    raw_rows = observe_rows(observations[-1].text)
                    if len(raw_rows) == end - start:
                        blocked = set()
                        for offset, cells in enumerate(raw_rows):
                            if any(c.rowspan > 1 for c in cells):
                                blocked.update(
                                    range(offset, max(offset + c.rowspan for c in cells))
                                )
                            if offset in blocked or any(c.rowspan != 1 for c in cells):
                                continue
                            if sum(c.colspan for c in cells) != columns:
                                continue
                            column = 0
                            mapped = []
                            for cell in cells:
                                mapped.append(replace(cell, row=0, column=column))
                                column += cell.colspan
                            accept(
                                Table(mapped, 1, columns),
                                start + offset,
                                start + offset + 1,
                                len(requests),
                            )
                except StructureError:
                    pass
            if depth >= 6:
                return
            boundaries = [b for b in (layout.safe_rows or []) if start < b < end]
            if not boundaries:
                return
            middle = min(boundaries, key=lambda b: abs(b - (start + end) / 2))
            for first, last in ((start, middle), (middle, end)):
                if any((r, c) not in occupied for r in range(first, last) for c in range(columns)):
                    read_range(first, last, depth + 1)

        # Non-overlapping ranges eliminate text-based deduplication. Every cut is
        # supported across all columns; an unknown rowspan stays in one group.
        ranges = row_fragments(layout, max_height=1800, max_rows=32, overlap_rows=0)
        for start, end in ranges:
            read_range(start, end)
        # A small exceptional ROI budget, not one LLM call per cell. Raw text is
        # placeable only inside a four-sided single-cell region. No HTML parsing
        # or splitting words into hypothetical columns.
        text_reader = getattr(client, "recognize_text", None)
        if getattr(client, "supports_text_recognition", False) and callable(text_reader):
            recovered = 0
            for row in range(rows):
                for column in range(columns):
                    if recovered >= 3 or not available():
                        break
                    region = (
                        layout.xs[column],
                        layout.ys[row],
                        layout.xs[column + 1],
                        layout.ys[row + 1],
                    )
                    if (
                        (row, column) in occupied
                        or not hypothesis.encloses(row, column)
                        or not region_has_ink(ink, region)
                    ):
                        continue
                    before = time.monotonic()
                    record = {
                        "request": len(requests) + 1,
                        "region": region,
                        "route": "isolated-text-roi",
                        "retry": True,
                    }
                    recovered += 1
                    try:
                        text = text_reader(encode(image.crop(region))).strip()
                        record.update(getattr(client, "last_diagnostic", {}))
                        # A table or thinking output is not an isolated text observation.
                        if not text or "<" in text or "```" in text:
                            raise StructureError("TEXT_ROI_FORMAT")
                        observations.append(
                            TextObservation(region, record["request"], "Text Recognition:", text)
                        )
                        cell = Cell(row, column, text, source_region=region)
                        cell.provenance = CellProvenance(
                            "unverified",
                            [
                                Evidence("text-roi", region, record["request"]),
                                Evidence("four-boundaries", region),
                            ],
                        )
                        accepted[row, column] = cell
                        occupied.add((row, column))
                        record["status"] = "OBSERVED"
                    except (StructureError, OCRServerError) as error:
                        record.update(status="REJECTED", error_type=type(error).__name__)
                    finally:
                        record["seconds"] = round(time.monotonic() - before, 4)
                        requests.append(record)
        if not any(cell.text.strip() for cell in accepted.values()):
            if alternatives:
                # Keep a single original observation, with no claimed grid mapping.
                # Other overlapping observations stay in opt-in diagnostics.
                table, box = alternatives[0]
                if any(c.text.strip() for c in table.cells):
                    document_issues.append(
                        ValidationIssue(
                            "UNRESOLVED_GRID",
                            "Геометрия и OCR расходятся",
                            source_region=layout.region,
                        )
                    )
                    return annotate_unplaced(table, box, partial=True)
            for observation in observations:
                if (
                    observation.region[0] <= layout.region[0] + 4
                    and observation.region[1] <= layout.region[1] + 4
                    and observation.region[2] >= layout.region[2] - 4
                    and observation.region[3] >= layout.region[3] - 4
                ):
                    runs = closed_runs(observation)
                    if runs:
                        document_issues.append(
                            ValidationIssue(
                                "UNRESOLVED_GRID",
                                "Сохранены отдельные OCR-наблюдения; привязка к исходной сетке неизвестна",
                                source_region=layout.region,
                            )
                        )
                        return runs
            document_issues.append(
                ValidationIssue(
                    "UNRESOLVED_TABLE", "Не получены применимые ячейки", source_region=layout.region
                )
            )
            return None
        cells = list(accepted.values())
        for row in range(rows):
            for column in range(columns):
                if (row, column) in occupied:
                    continue
                region = (
                    layout.xs[column],
                    layout.ys[row],
                    layout.xs[column + 1],
                    layout.ys[row + 1],
                )
                reason = (
                    "VISIBLE_INK_UNRESOLVED"
                    if region_has_ink(ink, region)
                    else "STRUCTURE_OR_CONTENT_UNRESOLVED"
                )
                cells.append(
                    Cell(
                        row,
                        column,
                        "",
                        source_region=region,
                        warnings=[reason],
                        provenance=CellProvenance("unresolved", [Evidence(reason, region)]),
                    )
                )
        table = Table(cells, rows, columns)
        table.issues.append(
            ValidationIssue(
                "CONTENT_UNVERIFIED",
                "OCR-текст требует сверки с источником; HTML и stop не доказывают точность",
                source_region=layout.region,
            )
        )
        if layout.confidence != "strong" or not hypothesis.scale_stable:
            table.issues.append(
                ValidationIssue(
                    "GRID_HYPOTHESIS",
                    "Границы являются частичной или неустойчивой геометрической гипотезой",
                    source_region=layout.region,
                )
            )
        table.grid()
        return table

    def save(document=None, error=None):
        if diagnostics is None:
            return
        diagnostics.mkdir(parents=True, exist_ok=True)
        trace.update(document.outcome() if document else {"status": "FAILED"})
        trace["request_count"] = len(requests)
        trace["http_attempts"] = getattr(client, "http_ocr_calls", 0) - initial_http_calls
        trace["retry_count"] = sum(bool(r["retry"]) for r in requests)
        trace["duration_seconds"] = round(time.monotonic() - started, 4)
        trace["stage_seconds"]["ocr_requests"] = round(sum(r["seconds"] for r in requests), 4)
        for stage in ("encode", "provider", "parse"):
            trace["stage_seconds"][stage] = round(
                sum(r.get(stage + "_seconds", 0) for r in requests), 6
            )
        trace["stage_seconds"]["reconstruction_overhead"] = round(
            max(
                0, time.monotonic() - started - layout_seconds - sum(r["seconds"] for r in requests)
            ),
            6,
        )
        if error:
            trace["failure"] = {"type": type(error).__name__, "message": str(error)[:300]}
        atomic_json(diagnostics / "run.json", trace)
        if document:
            atomic_json(
                diagnostics / "observations.json",
                {
                    "schema_version": 1,
                    "tables": [asdict(t) for t in document.tables],
                    "issues": [asdict(i) for i in document.issues],
                    "text_observations": [asdict(o) for o in observations],
                },
            )

    try:
        if not has_visible_text(image):
            raise StructureError("Недостаточно видимого текста для подтверждения таблицы")
        if layouts:
            for layout, hypothesis in zip(layouts, hypotheses):
                table = reconstruct(layout, hypothesis)
                if isinstance(table, list):
                    tables.extend(table)
                elif table is not None:
                    tables.append(table)
            # Text beyond detected regions is never silently declared covered.
            outside = ink.copy()
            for layout in layouts:
                left, top, right, bottom = layout.region
                outside[max(0, top - 4) : bottom + 4, max(0, left - 4) : right + 4] = 0
            if region_has_ink(outside, (0, 0, image.width, image.height)):
                document_issues.append(
                    ValidationIssue(
                        "OUTSIDE_LAYOUT_INK",
                        "Вне обнаруженных таблиц есть необработанные отметки/текст",
                        source_region=(0, 0, image.width, image.height),
                    )
                )
        else:
            full = (0, 0, image.width, image.height)
            try:
                parsed = read(full, single_table=False, route="whole-page")
                for table in parsed.tables:
                    if table.rows >= 2 and table.columns >= 2:
                        tables.append(annotate_unplaced(table, full))
            except StructureError, OCRServerError:
                # Preserve separate region observations. Do not infer row identity
                # from repeated text or remove rows in page overlaps.
                height = max(300, min(1200, image.height // 2))
                for top in range(0, image.height, height):
                    box = (0, top, image.width, min(image.height, top + height))
                    if not available():
                        document_issues.append(
                            ValidationIssue(
                                "IMAGE_BUDGET_EXHAUSTED", "Регион не обработан", source_region=box
                            )
                        )
                        continue
                    try:
                        parsed = read(box, single_table=False, route="page-region")
                        for table in parsed.tables:
                            if table.columns >= 2 and table.rows >= 2:
                                tables.append(annotate_unplaced(table, box, partial=True))
                    except StructureError, OCRServerError:
                        document_issues.append(
                            ValidationIssue(
                                "UNRESOLVED_REGION", "OCR региона неприменим", source_region=box
                            )
                        )
                if not tables and observations:
                    tables.extend(closed_runs(observations[0]))
                if tables:
                    document_issues.append(
                        ValidationIssue(
                            "UNKNOWN_PAGE_CUTS",
                            "Разрезы страницы без сетки могут пересекать строки/объединения; листы являются отдельными наблюдениями",
                            source_region=full,
                        )
                    )
        for table in tables:
            for cell in table.cells:
                if cell.source_region:
                    cell.provenance.source_polygon = source_polygon(image, cell.source_region)
        document = TableDocument(
            tables, document_issues, image.info.get("localocr_normalization", {})
        )
        document.validate()
        if document.outcome()["status"] == "FAILED":
            raise StructureError("Нет непустых извлечённых anchors; пустая книга не публикуется")
        client.check_cancel()
        # Small sanitized metrics are available without enabling OCR sidecars.
        client.last_run_metrics = {
            **document.outcome(),
            "calls": len(requests),
            "http_attempts": getattr(client, "http_ocr_calls", 0) - initial_http_calls,
            "seconds": time.monotonic() - started,
            "stage_seconds": {
                "layout_and_ink": round(layout_seconds, 6),
                **{
                    stage: round(sum(r.get(stage + "_seconds", 0) for r in requests), 6)
                    for stage in ("encode", "provider", "parse")
                },
            },
        }
        save(document)
        return document
    except BaseException as error:
        save(error=error)
        raise
