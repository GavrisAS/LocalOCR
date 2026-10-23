"""Score independent cell polygons and HTML separately against synthetic gold."""

import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from localocr.tables import parse_response


def rotate(points, angle, size, output_size):
    cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    w, h = size
    nw, nh = output_size
    return [
        [
            cos * (x - w / 2) + sin * (y - h / 2) + nw / 2,
            -sin * (x - w / 2) + cos * (y - h / 2) + nh / 2,
        ]
        for x, y in points
    ]


def iou(left, right):
    a, b = np.array(left, dtype=np.float32), np.array(right, dtype=np.float32)
    overlap = cv2.intersectConvexConvex(a, b)[0]
    union = abs(cv2.contourArea(a)) + abs(cv2.contourArea(b)) - overlap
    return overlap / union if union > 0 else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.resolve().relative_to(Path("data").resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    gold = json.loads(args.gold.read_text()) if args.gold else None
    modern = isinstance(gold, dict)
    truth = gold["cases"] if modern else gold
    records = json.loads((args.run / "results.json").read_text())["records"]
    converted = []
    metrics = []
    for index, record in enumerate(records):
        case = f"CASE-{index + 1:02d}"
        folder = args.output / case
        folder.mkdir()
        path = Path(record["input"])
        files = list((args.run / path.stem).glob("*.json"))
        raw = json.loads(files[0].read_text()) if files else {}
        tables = []
        reasons = ["CELL_BOX_TO_HTML_ALIGNMENT_UNQUALIFIED"]
        for table in raw.get("table_res_list", []):
            try:
                tables.extend(asdict(t) for t in parse_response(table["pred_html"]).tables)
            except ValueError:
                reasons.append("INVALID_HTML")
        (folder / "observations.json").write_text(
            json.dumps({"tables": tables, "ambiguity": reasons}, ensure_ascii=False, indent=2)
        )
        converted.append(
            {
                "case": case,
                "requests": [],
                "status": "REVIEW",
                "seconds": record["seconds"],
                "anchors": sum(bool(c["text"].strip()) for t in tables for c in t["cells"]),
            }
        )
        metric = {
            "case": case,
            "table_count": len(tables),
            "status": record["status"],
            "text_to_cell_alignment_qualified": False,
            "cell_boxes": sum(
                len(t.get("cell_box_list", [])) for t in raw.get("table_res_list", [])
            ),
        }
        if truth:
            expected = truth[index] if modern else truth[index]["gold"]
            size = Image.open(path).size
            expected_polygons = []
            if modern:
                expected_polygons = [c["polygon"] for c in expected["cells"]]
            else:
                base_size = (
                    max(c["source_region"][2] for c in expected["cells"]) + 20,
                    max(c["source_region"][3] for c in expected["cells"]) + 20,
                )
                for c in expected["cells"]:
                    x, y, r, b = c["source_region"]
                    expected_polygons.append(
                        rotate(
                            [(x, y), (r, y), (r, b), (x, b)],
                            truth[index]["rotation"],
                            base_size,
                            size,
                        )
                    )
            angle = raw.get("doc_preprocessor_res", {}).get("angle", 0)
            angle = angle if angle >= 0 else 0
            cos, sin = abs(math.cos(math.radians(angle))), abs(math.sin(math.radians(angle)))
            processed = (int(size[1] * sin + size[0] * cos), int(size[1] * cos + size[0] * sin))
            detected = []
            for t in raw.get("table_res_list", []):
                for x, y, r, b in t.get("cell_box_list", []):
                    detected.append(
                        rotate([(x, y), (r, y), (r, b), (x, b)], -angle, processed, size)
                    )
            edges = sorted(
                [
                    (iou(a, b), i, j)
                    for i, a in enumerate(detected)
                    for j, b in enumerate(expected_polygons)
                ],
                reverse=True,
            )
            used_a = set()
            used_b = set()
            overlaps = []
            for score, i, j in edges:
                if score >= 0.5 and i not in used_a and j not in used_b:
                    used_a.add(i)
                    used_b.add(j)
                    overlaps.append(score)
            metric.update(
                gold_boxes=len(expected_polygons),
                box_matches_iou50=len(overlaps),
                box_precision=len(overlaps) / len(detected) if detected else 0,
                box_recall=len(overlaps) / len(expected_polygons),
                matched_mean_iou=sum(overlaps) / len(overlaps) if overlaps else None,
                orientation_applied=angle,
                unmatched_predicted_boxes=len(detected) - len(overlaps),
            )
        metrics.append(metric)
    (args.output / "private-results.json").write_text(json.dumps(converted, indent=2))
    (args.output / "geometry-summary.json").write_text(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
