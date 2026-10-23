"""Explicit local qualification. Private evidence stays under the requested output root."""

import argparse
import hashlib
import json
import shutil
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="glm-ocr:latest")
    parser.add_argument("--calls", type=int, default=24)
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--through-service", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve() / "src"))
    from localocr import service
    from localocr.domain import StructureError
    from localocr.imaging import load_image
    from localocr.ollama import OllamaClient, Settings

    args.output.mkdir(parents=True, exist_ok=False)
    options: dict = dict(url=args.url, model=args.model, timeout=args.timeout, retries=0)
    if "max_calls" in Settings.__dataclass_fields__:
        options.update(max_calls=args.calls, max_image_seconds=args.seconds)
    settings = Settings(**options)
    if args.through_service:
        from localocr.providers import OllamaDirectProvider

        client = OllamaDirectProvider(settings)
        setattr(service, "create_provider", lambda *a, **kw: client)
    else:
        client = OllamaClient(settings)
    client.doctor()
    tags = client.request("GET", "/api/tags")
    model = next(m for m in tags["models"] if m["name"] == args.model)
    manifest = {
        "version": client.request("GET", "/api/version"),
        "model": model,
        "show": client.request("POST", "/api/show", {"model": args.model}),
        "settings": asdict(settings),
        "budget": {"calls": args.calls, "seconds": args.seconds},
    }
    (args.output / "environment.json").write_text(json.dumps(manifest, indent=2))
    results: list[dict] = []
    for index, path in enumerate(service.discover(args.source), 1):
        case = f"CASE-{index:02d}"
        started = time.monotonic()
        record: dict = {
            "case": case,
            "source": str(path),
            "source_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
            "requests": [],
        }
        original = client.recognize
        original_text = getattr(client, "recognize_text", None)

        def recognize(image, *, single_table=False):
            if len(record["requests"]) >= args.calls or time.monotonic() - started >= args.seconds:
                raise StructureError("QUALIFICATION_BUDGET")
            before = time.monotonic()
            try:
                return original(image, single_table=single_table)
            finally:
                record["requests"].append(
                    {**client.last_diagnostic, "seconds": time.monotonic() - before}
                )

        def recognize_text(image):
            before = time.monotonic()
            try:
                assert original_text is not None
                return original_text(image)
            finally:
                record["requests"].append(
                    {**client.last_diagnostic, "seconds": time.monotonic() - before}
                )

        setattr(client, "recognize", recognize)
        if original_text:
            setattr(client, "recognize_text", recognize_text)
        client.check_cancel()
        print(case, "START", flush=True)
        try:
            if args.through_service:
                job = service.convert(
                    path, settings, args.output / "results", diagnostics=args.output / "diagnostics"
                )[0]
                record.update(
                    {
                        key: value
                        for key, value in asdict(job).items()
                        if key not in {"source", "output", "seconds"}
                    }
                )
                record["anchors"] = job.recognized_anchors
                diagnostic = args.output / "diagnostics" / path.stem
                if diagnostic.exists():
                    shutil.copytree(diagnostic, args.output / case)
                if job.output:
                    shutil.copyfile(job.output, args.output / f"{case}.xlsx")
            else:
                document = service.recognize_document(load_image(path), client, args.output / case)
                from localocr.excel import write_workbook

                write_workbook(document, args.output / f"{case}.xlsx")
                if hasattr(document, "outcome"):
                    record.update(document.outcome())
                else:
                    record["status"] = (
                        "REVIEW"
                        if any(
                            t.issues or any(c.warnings for c in t.cells) for t in document.tables
                        )
                        else "SUCCESS"
                    )
                record["anchors"] = sum(
                    bool(c.text.strip()) for t in document.tables for c in t.cells
                )
                record["shapes"] = [(t.rows, t.columns) for t in document.tables]
        except Exception as error:
            record.update(
                status="FAILED", reason=type(error).__name__ + ": " + str(error), anchors=0
            )
        finally:
            setattr(client, "recognize", original)
            if original_text:
                setattr(client, "recognize_text", original_text)
        record["seconds"] = round(time.monotonic() - started, 3)
        record["source_unchanged"] = (
            record["source_hash"] == hashlib.sha256(path.read_bytes()).hexdigest()
        )
        record["runner"] = client.request("GET", "/api/ps")
        record["digest_after"] = next(
            m["digest"]
            for m in client.request("GET", "/api/tags")["models"]
            if m["name"] == args.model
        )
        results.append(record)
        (args.output / "private-results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2)
        )
        print(
            case,
            record["status"],
            "anchors",
            record["anchors"],
            "calls",
            len(record["requests"]),
            "seconds",
            record["seconds"],
            flush=True,
        )
    times = sorted(r["seconds"] for r in results)
    summary = {
        "model_digest": model["digest"],
        "human_gold": False,
        "median_seconds": statistics.median(times),
        "p95_seconds": times[max(0, __import__("math").ceil(len(times) * 0.95) - 1)],
        "cases": [
            {
                k: r.get(k)
                for k in (
                    "case",
                    "status",
                    "anchors",
                    "recognized_anchors",
                    "verified_anchors",
                    "unresolved_regions",
                    "unverified_content",
                    "seconds",
                    "shapes",
                )
            }
            | {"calls": len(r["requests"])}
            for r in results
        ],
    }
    if args.through_service:
        before_resume = getattr(client, "http_ocr_calls", 0)
        completed = [r for r in results if r["status"] in {"SUCCESS", "REVIEW", "PARTIAL"}]
        resumed = [
            service.convert(Path(r["source"]), settings, args.output / "results")[0]
            for r in completed
        ]
        summary["resume"] = {
            "checked": len(resumed),
            "resumed": sum(r.resumed for r in resumed),
            "additional_ocr_calls": getattr(client, "http_ocr_calls", 0) - before_resume,
            "quality_statuses_preserved": all(
                r.status == previous["status"] for r, previous in zip(resumed, completed)
            ),
        }
        if (
            not all(r.resumed for r in resumed)
            or summary["resume"]["additional_ocr_calls"]
            or not summary["resume"]["quality_statuses_preserved"]
        ):
            raise RuntimeError("Real service resume qualification failed")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
