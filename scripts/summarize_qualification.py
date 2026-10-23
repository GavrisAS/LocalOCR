"""Allowlist aggregate evidence; never export image names, OCR, paths or source hashes."""

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize(root):
    records = read(root / "private-results.json")
    cases = []
    for record in records:
        sidecar = root / record["case"] / "observations.json"
        observations = read(sidecar) if sidecar.exists() else {"tables": []}
        cells = [c for t in observations["tables"] for c in t["cells"]]
        nonempty = [c for c in cells if c["text"].strip()]
        supported = sum(
            any(e["kind"] == "four-boundaries" for e in c.get("provenance", {}).get("evidence", []))
            for c in nonempty
        )
        unplaced = sum(
            any(e["kind"] == "ocr-region" for e in c.get("provenance", {}).get("evidence", []))
            for c in nonempty
        )
        trace_file = root / record["case"] / "run.json"
        trace = read(trace_file) if trace_file.exists() else {}
        codes = sorted(
            {i["code"] for table in observations["tables"] for i in table.get("issues", [])}
            | {i["code"] for i in observations.get("issues", [])}
        )
        calls = record["requests"]
        cases.append(
            {
                "case": record["case"],
                "status": record["status"],
                "recognized_anchors": record["anchors"],
                "geometry_supported_anchors": supported
                if all("provenance" in c for c in nonempty)
                else None,
                "unplaced_anchors": unplaced if all("provenance" in c for c in nonempty) else None,
                "verified_anchors": record.get("verified_anchors", 0),
                "unresolved_anchors_in_hypothesis": sum(
                    c.get("provenance", {}).get("state") == "unresolved" for c in cells
                ),
                "source_unresolved_anchor_count": None,  # no human source gold
                "unresolved_region_items": record.get("unresolved_regions"),
                "unverified_content": record.get("unverified_content", record["anchors"]),
                "reason_codes": codes,
                "calls": len(calls),
                "seconds": record["seconds"],
                "done_reasons": dict(Counter(c.get("done_reason", "UNKNOWN") for c in calls)),
                "reported_eval_tokens": sum(c.get("eval_count") or 0 for c in calls),
                "usage_missing_calls": sum(c.get("eval_count") is None for c in calls),
                "stage_seconds": trace.get("stage_seconds", record.get("stage_seconds", {})),
            }
        )
    times = sorted(r["seconds"] for r in records)
    return {
        "cases": cases,
        "outcomes": dict(Counter(r["status"] for r in records)),
        "calls": sum(len(r["requests"]) for r in records),
        "seconds": round(sum(times), 3),
        "median_seconds": statistics.median(times),
        "p95_seconds": times[math.ceil(len(times) * 0.95) - 1],
        "p95_method": "nearest rank",
        "distinct_source_hashes": len({r["source_hash"] for r in records}),
        "source_unchanged": all(r["source_unchanged"] for r in records),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "after", "benchmark", "holdout", "gold", "replay", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    before, after = summarize(args.baseline), summarize(args.after)
    before_private = read(args.baseline / "private-results.json")
    after_private = read(args.after / "private-results.json")
    same_inputs = [(r["case"], r["source_hash"]) for r in before_private] == [
        (r["case"], r["source_hash"]) for r in after_private
    ]
    manifest = read(args.after / "environment.json")
    digest = manifest["model"]["digest"]
    same_digest = all(r["digest_after"] == digest for r in before_private + after_private)
    write(
        args.output / "qualification.json",
        {
            "human_gold": False,
            "identical_input_hashes": same_inputs,
            "all_digest_checks_equal": same_digest,
            "digest": digest,
            "before": before,
            "after": after,
        },
    )
    write(
        args.output / "model-manifest.json",
        {
            "qualification_backend": "Ollama Direct",
            "server": manifest["version"],
            "model": manifest["model"],
            "settings": manifest["settings"],
            "generation": {
                "temperature": 0,
                "seed": 0,
                "num_ctx": 32768,
                "num_predict": 16000,
                "single_table_stop": ["</table>"],
                "encoding": "RGB/PNG; no default resize",
            },
            "show": {
                k: manifest["show"].get(k)
                for k in (
                    "template",
                    "parameters",
                    "details",
                    "model_info",
                    "capabilities",
                    "projector_info",
                )
            },
            "old_digest": "6effedd0dc8aec66ad86c94b8099395376e212f22c87a9d7147c422f7e447be4",
            "old_new_ab": "PENDING_MODEL: old tag/manifest unavailable; historical server version differs",
        },
    )
    benchmark = read(args.benchmark / "metrics.json")
    fields = (
        "input",
        "endpoint",
        "task",
        "encoding",
        "scale",
        "generation",
        "digest",
        "seconds",
        "parseable",
        "text_coverage",
        "synthetic_matched_slots",
        "synthetic_expected_slots",
        "eval_count",
        "prompt_eval_count",
        "done_reason",
        "thinking_output",
        "nonempty_text_observation",
        "geometry_shape_agreement",
    )
    write(
        args.output / "benchmark.json",
        {
            "calls": len(benchmark),
            "variants": [{k: r.get(k) for k in fields} for r in benchmark],
            "decision": "retain generate, 32768/16000, stop and full RGB/PNG; 65536 not justified",
        },
    )
    holdout = summarize(args.holdout)
    gold = read(args.gold)
    matches = []
    for index, expected in enumerate(gold):
        record = read(args.holdout / "private-results.json")[index]
        observed = read(args.holdout / record["case"] / "observations.json")["tables"]
        truth = expected["gold"]
        actual = (
            {(c["row"], c["column"]): c for c in observed[0]["cells"]}
            if len(observed) == 1
            and (observed[0]["rows"], observed[0]["columns"]) == (truth["rows"], truth["columns"])
            else {}
        )
        matched = sum(
            (c["row"], c["column"]) in actual
            and all(
                actual[c["row"], c["column"]][key] == c[key]
                for key in ("text", "rowspan", "colspan")
            )
            for c in truth["cells"]
        )
        matches.append(
            {
                "case": record["case"],
                "seed": expected["seed"],
                "style": expected["style"],
                "rotation": expected["rotation"],
                "gold_anchors": len(truth["cells"]),
                "matching_anchors": matched,
                "full_exact_match": matched == len(truth["cells"]),
                "all_nonempty_gold_anchors_matched": all(
                    (c["row"], c["column"]) in actual
                    and actual[c["row"], c["column"]]["text"] == c["text"]
                    for c in truth["cells"]
                    if c["text"]
                ),
            }
        )
    holdout.update(synthetic_gold=matches, resume=read(args.holdout / "summary.json").get("resume"))
    write(args.output / "holdout.json", holdout)
    write(args.output / "replay.json", read(args.replay / "summary.json"))
    if not same_inputs or not same_digest:
        raise SystemExit("A/B inputs or digest changed")
    print("Sanitized aggregate evidence written; no OCR content exported")


if __name__ == "__main__":
    main()
