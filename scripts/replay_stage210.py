"""Deterministic offline replay. Input manifest/raw/GOLD and detailed output stay private.

Use a versioned source root to compare the exact same saved bytes without inference.
Only aggregate counts are printed. No file names, raw content or private SHA in stdout.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score(ex, gold):
    expected = gold["cells"]
    tables = [asdict(t) for t in ex.document.tables]
    predicted = tables[0]["cells"] if tables else []
    positions = {(c["row"], c["column"]): c for c in predicted}

    def key(c):
        return c["row"], c["column"], c["rowspan"], c["colspan"]

    def text(s):
        return str(s).strip() if s is not None else ""

    nonempty = [c for c in expected if text(c["text"])]
    observed = Counter(text(v) for v in ex.values if text(v))
    wanted = Counter(text(c["text"]) for c in nonempty)
    anchored = joint = numeric = numeric_total = span = 0
    for c in expected:
        p = positions.get((c["row"], c["column"]))
        span += bool(p and key(p) == key(c))
        if not text(c["text"]):
            continue
        exact = bool(p and text(p["text"]) == text(c["text"]))
        anchored += exact
        joint += bool(exact and key(p) == key(c))
        if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?", text(c["text"])):
            numeric_total += 1
            numeric += exact
    expected_keys = {key(c) for c in expected}
    predicted_keys = {key(c) for c in predicted}
    return dict(
        scope="HUMAN_VERIFIED_CALIBRATION_ONLY",
        anchors=len(expected),
        nonempty=len(nonempty),
        nonempty_text_exact=anchored,
        nonempty_row_col_span_text_joint_exact=joint,
        row_col_span_exact=span,
        numeric_exact=numeric,
        numeric_total=numeric_total,
        missing_anchors=len(expected_keys - predicted_keys),
        extra_anchors=len(predicted_keys - expected_keys)
        + sum(len(t["cells"]) for t in tables[1:]),
        text_multiset_exact=sum((wanted & observed).values()),
        whole_table_exact=int(
            len(tables) == 1
            and not ex.lines
            and (tables[0]["rows"], tables[0]["columns"]) == (gold["rows"], gold["columns"])
            and {(*key(c), text(c["text"])) for c in predicted}
            == {(*key(c), text(c["text"])) for c in expected}
        ),
        matching="First table, fixed format-local row/column/span; no shifts. Text exact after outer strip only. Text multiset ignores placement; all observed values, multiplicity clipped.",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve() / "src"))
    from localocr.failsoft import extract, write_extraction

    manifest = json.loads(args.manifest.read_text("utf-8"))
    args.output.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    for item in manifest["cases"]:
        raw_path = Path(item["raw_path"])
        if sha(raw_path) != item["raw_sha256"]:
            raise ValueError("RAW_CHANGED")
        raw = raw_path.read_text(encoding="utf-8", errors="surrogatepass")
        if item["format"] == "ollama-chat-envelope":
            data = json.loads(raw)
            raw = data["message"]["content"]
        options = {
            "truncated": item.get("completion", {}).get("finish_state")
            == "GENERATION_LIMIT_CONFIRMED"
        }
        if not args.baseline:
            options.update(model_id=item["model"], completion=item.get("completion", {}))
        started = time.monotonic()
        ex = extract(raw, **options)
        state = (
            write_extraction(ex, args.output / (item["id"] + ".xlsx"))
            if ex.values
            else ex.outcome()
        )
        row = dict(
            id=item["id"],
            source_sha256=item["source_sha256"],
            model=item["model"],
            lane=item["lane"],
            raw_sha256=item["raw_sha256"],
            contentful=bool(ex.values),
            structured=bool(state["table_structured"]),
            text_only=bool(ex.values and not state["table_structured"]),
            no_content=not ex.values,
            failed=int(not ex.values),
            unplaced_markers=sum(
                len(re.findall(r"(?:table|text|sub_title)\s*\[\[", v)) for v in ex.values
            ),
            values=ex.values,
            cells=[asdict(t) for t in ex.document.tables],
            distinct_values=len(set(ex.values)),
            characters=sum(map(len, ex.values)),
            seconds=time.monotonic() - started,
            codes=state["error_codes"],
            http_attempts=0,
            calibration=score(ex, item["gold"]) if item.get("gold") else None,
        )
        rows.append(row)
    (args.output / "private-results.json").write_text(
        json.dumps(rows, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    aggregates = {}
    for lane in sorted({r["lane"] for r in rows}):
        lane_rows = [r for r in rows if r["lane"] == lane]
        aggregate = {
            k: sum(r[k] for r in lane_rows)
            for k in (
                "contentful",
                "structured",
                "text_only",
                "no_content",
                "failed",
                "unplaced_markers",
                "distinct_values",
                "characters",
                "http_attempts",
            )
        }
        aggregate.update(
            input_total=len(lane_rows),
            unique_inputs=len({r["source_sha256"] for r in lane_rows}),
            contentful_unique=len({r["source_sha256"] for r in lane_rows if r["contentful"]}),
            structured_unique=len({r["source_sha256"] for r in lane_rows if r["structured"]}),
            bucket="PAIRED_HISTORICAL_RAW_REPLAY",
            inference_seconds_p50=None,
            inference_seconds_p95=None,
            inference_calls=0,
        )
        calibration = [r["calibration"] for r in lane_rows if r["calibration"]]
        aggregate["calibration"] = (
            {
                k: sum(r[k] for r in calibration)
                for k in (
                    "anchors",
                    "nonempty",
                    "nonempty_text_exact",
                    "nonempty_row_col_span_text_joint_exact",
                    "row_col_span_exact",
                    "numeric_exact",
                    "numeric_total",
                    "missing_anchors",
                    "extra_anchors",
                    "text_multiset_exact",
                    "whole_table_exact",
                )
            }
            if calibration
            else "HUMAN_GOLD_NOT_RUN"
        )
        aggregates[lane] = aggregate
    (args.output / "aggregate.json").write_text(json.dumps(aggregates, indent=2), encoding="utf-8")
    print(json.dumps(aggregates))


if __name__ == "__main__":
    main()
