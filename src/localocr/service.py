"""Shared single/batch pipeline. No Qt, agent tools or cloud dependencies."""

import hashlib
import logging
import time
import traceback
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event

from localocr.domain import JobResult, StructureError, Table
from localocr.embedded import EmbeddedSettings
from localocr.excel import write_workbook
from localocr.imaging import (
    EXTENSIONS,
    Layout,
    load_image,
)
from localocr.journal import Journal, atomic_json, file_hash, settings_identity
from localocr.ollama import Cancelled, OCRServerError, Settings
from localocr.providers import OpenWebUISettings, create_provider
from localocr.reconstruction import recognize_document
from localocr.runtime import portable_root

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


def stitch_unstructured(parts: list[tuple[int, int, Table]]) -> Table:
    raise StructureError(
        "Не удалось однозначно сопоставить строки: нужны координаты; совпадение текста не доказывает положение"
    )


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
    fail_soft=False,
    ocr_prompt=None,
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
        output_dir.mkdir(parents=True, exist_ok=True)
        with Journal(output_dir) as journal:
            # Establish report/journal ownership before readiness; one batch failure,
            # zero fake per-image OCR jobs for an unavailable route/model.
            try:
                client.doctor()
            except Cancelled:
                from localocr.failsoft import write_batch_summary

                write_batch_summary(
                    [],
                    output_dir,
                    len(paths),
                    True,
                    unique_inputs=None,
                    batch={"status": "CANCELLED", "stage": "doctor", "not_started": len(paths)},
                )
                atomic_json(
                    output_dir / f"report-{time.time_ns()}.json",
                    {
                        "batch": {
                            "status": "CANCELLED",
                            "stage": "doctor",
                            "not_started": len(paths),
                        },
                        "results": [],
                    },
                )
                return []
            except Exception as error:
                from localocr.failsoft import failure_code, write_batch_summary

                code = failure_code(error, "doctor")
                batch = {
                    "status": "FAILED",
                    "stage": "doctor",
                    "code": code,
                    "blocked": len(paths),
                    "not_started": len(paths),
                    "recovery": "Проверьте выбранный endpoint, token, model ID или Embedded engine; выполните doctor --use-config и повторите convert. Настройки и существующие XLSX сохранены.",
                }
                result = JobResult(
                    "BATCH",
                    "FAILED",
                    message="doctor: " + code + ". " + batch["recovery"],
                    error_codes=[code],
                    batch_level=True,
                )
                write_batch_summary(
                    [result], output_dir, len(paths), False, unique_inputs=None, batch=batch
                )
                atomic_json(
                    output_dir / f"report-{time.time_ns()}.json",
                    {"batch": batch, "results": [asdict(result)]},
                )
                if progress:
                    progress(0, len(paths), result.message)
                return [result]
            results = []
            identity = settings_identity(settings, client)
            if fail_soft:
                from localocr.failsoft import VERSION, selected_prompt

                ocr_prompt = ocr_prompt or selected_prompt(settings)
                identity["pipeline"] += "/" + VERSION + "/literal-xlsx-1"
                identity["settings"] = {
                    **identity["settings"],
                    "fail_soft": True,
                    "ocr_prompt": ocr_prompt,
                }
            source_hashes = set()
            missing_identity = False
            for index, (path, name) in enumerate(zip(paths, output_names(paths))):
                if cancel.is_set():
                    break
                if progress:
                    progress(index, len(paths), path.name)
                target = output_dir / name
                start = time.monotonic()
                key = None
                published_hash = None
                fingerprint = {}
                attempts = 0
                client.last_completion_metadata = {}
                setattr(client, "last_http_metrics", {})
                stage = "fingerprint"
                before_http = getattr(client, "http_ocr_calls", 0)
                try:
                    key, fingerprint = journal.key(path, identity)
                    source_hashes.add(fingerprint["source_hash"])
                    # A changed model/settings fingerprint owns a different output;
                    # preserve the old workbook and any user-created target.
                    owned = any(
                        e.get("output") == str(target.resolve()) and e.get("key") != key
                        for e in journal.records.values()
                    )
                    if owned and not overwrite:
                        target = target.with_name(target.stem + "_" + key[:10] + target.suffix)
                    cached = (
                        journal.completed(key, target) if identity["model"].get("digest") else None
                    )
                    attempts = journal.records.get(key, {}).get("attempts", 0) + 1
                    if cached and not overwrite:
                        previous = cached.get("result", {})
                        evidence = {
                            key: previous.get(key, 0)
                            for key in (
                                "tables",
                                "warnings",
                                "recognized_anchors",
                                "verified_anchors",
                                "unresolved_anchors",
                                "unresolved_regions",
                                "unverified_content",
                                "xlsx_with_data",
                                "table_structured",
                                "partial_text_salvage",
                                "nonempty_data_cells",
                                "partial_structured",
                                "diagnostic_only",
                                "no_content",
                                "ocr_contentful",
                                "distinct_content_values",
                                "content_characters",
                                "numeric_text_tokens",
                                "unplaced_text",
                                "layout_markers_removed",
                                "layout_metadata_characters",
                                "layout_metadata_uncertain",
                                "layout_markers_remaining",
                            )
                        }
                        result = JobResult(
                            path.name,
                            cached["status"],
                            str(target),
                            "Возобновлено без OCR; сохранён статус "
                            + cached["status"]
                            + ". "
                            + previous.get("message", ""),
                            shapes=[tuple(shape) for shape in previous.get("shapes", [])],
                            error_codes=previous.get("error_codes", []),
                            request_metrics=previous.get("request_metrics", {}),
                            completion=previous.get("completion", {}),
                            content_kind=previous.get("content_kind", "UNKNOWN"),
                            metrics_version=previous.get("metrics_version", "legacy"),
                            resumed=True,
                            **evidence,
                        )
                    elif target.exists() and not overwrite:
                        result = JobResult(
                            path.name,
                            "SKIPPED",
                            str(target),
                            "Результат существует; fingerprint не подтверждён. Для обработки: --overwrite",
                        )
                    else:
                        journal.append(
                            {
                                "key": key,
                                **fingerprint,
                                "status": "RUNNING",
                                "attempts": attempts,
                                "output": str(target.resolve()),
                            }
                        )
                        if isinstance(diagnostics, Path):
                            diag = diagnostics / target.stem
                        else:
                            diag = (
                                portable_root() / "diagnostics" / target.stem
                                if diagnostics
                                else None
                            )
                        loaded = time.monotonic()
                        stage = "load"
                        image = load_image(path)
                        stage = "ocr"
                        load_seconds = time.monotonic() - loaded
                        if fail_soft:
                            from localocr.failsoft import recognize_failsoft

                            raw, truncated = recognize_failsoft(
                                image,
                                client,
                                diag,
                                source_name=path.name,
                                prompt=ocr_prompt,
                                raw_only=True,
                            )
                        else:
                            document = recognize_document(
                                image, client, diag, source_name=path.name
                            )
                        if fail_soft and isinstance(settings, EmbeddedSettings):
                            actual_backend = getattr(
                                getattr(client, "active_candidate", None), "backend", None
                            )
                            if actual_backend != identity["model"].get("active_backend"):
                                # Never publish/cache a response under another backend identity.
                                raise OCRServerError("BACKEND_CHANGED")
                        if file_hash(path) != fingerprint["source_hash"]:
                            raise ValueError(
                                "Источник изменился во время OCR; результат не опубликован"
                            )
                        expected_digest = identity["model"].get("digest")
                        if (
                            expected_digest
                            and isinstance(settings, (Settings, OpenWebUISettings))
                            and getattr(settings, "api", "proxy") != "chat"
                        ):
                            client.doctor()
                            if (
                                getattr(client, "model_identity", {}).get("digest")
                                != expected_digest
                            ):
                                raise ValueError(
                                    "Digest модели изменился во время OCR; результат не опубликован"
                                )
                        stage = "xlsx"
                        writing = time.monotonic()
                        if fail_soft:
                            from localocr.postprocess import convert_raw

                            def verify_source():
                                if file_hash(path) != fingerprint["source_hash"]:
                                    raise ValueError("SOURCE_CHANGED")

                            metadata = convert_raw(
                                raw,
                                target,
                                truncated=truncated,
                                completion=getattr(client, "last_completion_metadata", {}),
                                model_id=""
                                if isinstance(settings, EmbeddedSettings)
                                else settings.model,
                                diagnostics=diag,
                                normalization=image.info.get("localocr_normalization", {}),
                                overwrite=overwrite,
                                cancel=cancel,
                                before_publish=verify_source,
                            )
                        else:
                            write_workbook(document, target, overwrite, cancel)
                        published_hash = file_hash(target)
                        if fail_soft:
                            outcome = metadata["outcome"]
                            metrics = getattr(client, "last_run_metrics", {})
                            result = JobResult(
                                path.name,
                                outcome.pop("status"),
                                str(target),
                                tables=metadata["tables"],
                                shapes=[tuple(v) for v in metadata["shapes"]],
                                calls=metrics.get("calls", 0),
                                http_attempts=metrics.get("http_attempts", 0),
                                child_peak_rss_kib=metadata.get("child_peak_rss_kib"),
                                **outcome,
                                stage_seconds={
                                    **metadata["stage_seconds"],
                                    "load": load_seconds,
                                    "recognize": metrics.get("seconds", 0),
                                },
                            )
                        else:
                            warnings = len(document.issues) + sum(
                                len(table.issues) + sum(len(c.warnings) for c in table.cells)
                                for table in document.tables
                            )
                            review_codes = list(
                                dict.fromkeys(
                                    [issue.code for issue in document.issues]
                                    + [
                                        issue.code
                                        for table in document.tables
                                        for issue in table.issues
                                    ]
                                )
                            )
                            outcome = document.outcome()
                            metrics = getattr(client, "last_run_metrics", {})
                            result = JobResult(
                                path.name,
                                outcome.pop("status"),
                                str(target),
                                message="Требуется проверка: " + ", ".join(review_codes)
                                if warnings
                                else "",
                                tables=len(document.tables),
                                shapes=[(t.rows, t.columns) for t in document.tables],
                                warnings=warnings,
                                calls=metrics.get("calls", 0),
                                http_attempts=metrics.get("http_attempts", 0),
                                **outcome,
                                stage_seconds={
                                    **metrics.get("stage_seconds", {}),
                                    "load": round(load_seconds, 4),
                                    "recognize": round(metrics.get("seconds", 0), 4),
                                    "write": round(time.monotonic() - writing, 4),
                                },
                            )
                except Cancelled:
                    if key is not None:
                        journal.append(
                            {"key": key, **fingerprint, "status": "CANCELLED", "attempts": attempts}
                        )
                    if fail_soft:
                        results.append(
                            JobResult(
                                path.name,
                                "CANCELLED",
                                error_codes=["CANCELLED"],
                                calls=int(
                                    getattr(client, "http_ocr_calls", before_http) > before_http
                                ),
                                ocr_calls=int(
                                    getattr(client, "http_ocr_calls", before_http) > before_http
                                ),
                                http_attempts=getattr(client, "http_ocr_calls", before_http)
                                - before_http,
                                provider=type(settings).__name__,
                                model_id=getattr(settings, "model", "embedded-glm-ocr"),
                                model_digest=identity["model"].get("digest"),
                                backend=identity["backend"],
                                pipeline_version=identity["pipeline"],
                                seconds=round(time.monotonic() - start, 3),
                            )
                        )
                    break
                except Exception as error:
                    LOGGER.error(
                        "Image processing failed: %s (%s)\n%s",
                        path.name,
                        type(error).__name__,
                        "".join(traceback.format_tb(error.__traceback__)),
                    )
                    if fail_soft:
                        from localocr.failsoft import failure_code

                        if key is None:
                            missing_identity = True
                            # A vanished/unreadable input still needs a terminal record;
                            # no unavailable source identity can become a completed cache hit.
                            fingerprint = {
                                "source_path": str(path.resolve()),
                                "source_hash": None,
                                "identity": identity,
                                "source_unavailable": True,
                            }
                            key = hashlib.sha256(repr(fingerprint).encode()).hexdigest()
                        code = failure_code(error, stage)
                        process = getattr(client, "process", None)
                        crashed = code == "WORKER_CRASH" or (
                            process is not None and process.poll() is not None
                        )
                        codes = list(dict.fromkeys([code] + (["WORKER_CRASH"] if crashed else [])))
                        # No raw model/server exception strings in public job metadata.
                        result = JobResult(
                            path.name,
                            "FAILED",
                            message=code,
                            error_codes=codes,
                            no_content=code == "NO_CONTENT",
                            content_kind="NO_CONTENT" if code == "NO_CONTENT" else "UNKNOWN",
                            timeout=code in {"TIMEOUT", "PARSER_TIMEOUT", "WRITER_TIMEOUT"},
                            worker_crashed=crashed,
                            calls=int(getattr(client, "http_ocr_calls", before_http) > before_http),
                            http_attempts=getattr(client, "http_ocr_calls", before_http)
                            - before_http,
                        )
                        if isinstance(settings, EmbeddedSettings):
                            client.close()
                        try:
                            errors_dir = portable_root() / "diagnostics" / "failures"
                            errors_dir.mkdir(parents=True, exist_ok=True)
                            atomic_json(
                                errors_dir
                                / (
                                    (key or hashlib.sha256(str(path).encode()).hexdigest())
                                    + ".json"
                                ),
                                {
                                    "status": "FAILED",
                                    "error_codes": codes,
                                    "stage": stage,
                                    "error_type": type(error).__name__,
                                },
                            )
                        except OSError:
                            LOGGER.error("Diagnostic sidecar IO_FAILURE")
                    else:
                        result = JobResult(
                            path.name,
                            "FAILED",
                            message=str(error)
                            if isinstance(error, (ValueError, OCRServerError, OSError))
                            else "Ошибка обработки; см. локальный лог",
                        )
                if fail_soft:
                    if not result.resumed:
                        result.request_metrics = getattr(client, "last_http_metrics", {})
                        result.completion = getattr(client, "last_completion_metadata", {})
                    result.ocr_calls = result.calls
                    result.provider = type(settings).__name__
                    result.model_id = getattr(settings, "model", "embedded-glm-ocr")
                    result.model_digest = identity["model"].get("digest")
                    actual_backend = getattr(
                        getattr(client, "active_candidate", None), "backend", None
                    )
                    result.backend = identity["backend"] + (
                        "/" + actual_backend if actual_backend else ""
                    )
                    result.pipeline_version = identity["pipeline"]
                result.seconds = round(time.monotonic() - start, 3)
                results.append(result)
                if key is not None and result.status != "SKIPPED" and not result.resumed:
                    journal.append(
                        {
                            "key": key,
                            **fingerprint,
                            "status": result.status,
                            "attempts": attempts,
                            "latency": result.seconds,
                            "output": str(target.resolve()) if result.output else None,
                            "output_hash": published_hash if result.output else None,
                            "result": asdict(result),
                        }
                    )
                LOGGER.info(
                    "%s: %s tables=%s seconds=%s",
                    path.name,
                    result.status,
                    result.tables,
                    result.seconds,
                )
                if progress:
                    progress(index + 1, len(paths), f"{path.name}: {result.status}")
            report = {
                "cancelled": cancel.is_set(),
                "discovered": len(paths),
                "resumed": sum(result.resumed for result in results),
                "results": [asdict(result) for result in results],
            }
            atomic_json(output_dir / f"report-{time.time_ns()}.json", report)
            if fail_soft:
                from localocr.failsoft import write_batch_summary

                write_batch_summary(
                    results,
                    output_dir,
                    len(paths),
                    cancel.is_set(),
                    unique_inputs=len(source_hashes)
                    if not missing_identity and len(results) == len(paths)
                    else None,
                )
            return results
    finally:
        client.close()
