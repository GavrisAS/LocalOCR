"""Aggregate private pilot evidence without exporting OCR or source filenames."""

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        following = [i]
        for j, right in enumerate(b, 1):
            following.append(min(following[-1] + 1, row[j] + 1, row[j - 1] + (left != right)))
        row = following
    return row[-1]


def summarize(run, gold=None):
    records = json.loads((run / "private-results.json").read_text())
    truth = json.loads(gold.read_text()) if gold else None
    cases: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        item = {
            "case": record["case"],
            "status": record["status"],
            "seconds": record["seconds"],
            "calls": len(record["requests"]),
            "human_verified": False,
        }
        observations = run / record["case"] / "observations.json"
        tables = json.loads(observations.read_text())["tables"] if observations.exists() else []
        item["unplaced_observations"] = sum(
            any(e["kind"] == "ocr-region" for e in c.get("provenance", {}).get("evidence", []))
            for table in tables
            for c in table["cells"]
            if c["text"].strip()
        )
        item["metric_scope"] = "canonical/HTML indices; not original-image cell geometry"
        cells = [c for table in tables for c in table["cells"]]
        item["unresolved_positions_in_hypothesis"] = sum(
            c.get("provenance", {}).get("state") == "unresolved" for c in cells
        )
        item["observed_nonempty"] = sum(bool(c["text"].strip()) for c in cells)
        if truth:
            expected = truth[index]["gold"]
            same_shape = len(tables) == 1 and (tables[0]["rows"], tables[0]["columns"]) == (
                expected["rows"],
                expected["columns"],
            )
            actual = {(c["row"], c["column"]): c for c in tables[0]["cells"]} if same_shape else {}
            exact = spans = chars = words = char_errors = word_errors = 0
            headers = 0
            for c in expected["cells"]:
                observed = actual.get((c["row"], c["column"]))
                if observed and observed.get("provenance", {}).get("state") == "unresolved":
                    observed = None
                text = observed["text"] if observed else ""
                span = observed is not None and (observed["rowspan"], observed["colspan"]) == (
                    c["rowspan"],
                    c["colspan"],
                )
                spans += span
                exact += span and text == c["text"]
                headers += observed is not None and observed.get("header", False) == c.get(
                    "header", False
                )
                chars += len(c["text"])
                words += len(c["text"].split())
                char_errors += distance(c["text"], text)
                word_errors += distance(c["text"].split(), text.split())
            item.update(
                style=truth[index]["style"],
                rotation=truth[index]["rotation"],
                shape_match=same_shape,
                expected_anchors=len(expected["cells"]),
                exact_text_position_span=exact,
                span_match=spans,
                header_flag_match=headers,
                reference_characters=chars,
                character_edits=char_errors,
                reference_words=words,
                word_edits=word_errors,
                unsupported_text_occurrences=sum(
                    (
                        Counter(c["text"] for c in cells if c["text"])
                        - Counter(c["text"] for c in expected["cells"] if c["text"])
                    ).values()
                ),
                full_table_match=same_shape
                and exact == len(expected["cells"])
                and len(actual) == len(expected["cells"]),
                cer_position_conditioned=char_errors / chars if chars else None,
                wer_position_conditioned=word_errors / words if words else None,
            )
            # Coordinate IoU is deliberately unavailable: legacy rotated gold boxes
            # are pre-rotation. HTML position is not an original-image polygon.
            item["cell_box_iou"] = None
        else:
            item.update(
                structure_accuracy=None,
                exact_cell_accuracy=None,
                cer=None,
                wer=None,
                hallucinations=None,
            )
        cases.append(item)
    times = sorted(c["seconds"] for c in cases)
    return {
        "mode": "LIVE_OCR",
        "human_gold_gate": "PENDING",
        "calls": sum(c["calls"] for c in cases),
        "seconds": sum(times),
        "p50": statistics.median(times),
        "p95": times[math.ceil(0.95 * len(times)) - 1],
        "outcomes": dict(Counter(c["status"] for c in cases)),
        "cases": cases,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(summarize(args.run, args.gold), indent=2))


if __name__ == "__main__":
    main()
