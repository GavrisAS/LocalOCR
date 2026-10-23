"""Score baseline hypothesis polygons, excluding explicitly unplaced HTML cells."""

import argparse
import json
from pathlib import Path

from PIL import Image

from research.score_paddle import iou, rotate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.resolve().relative_to(Path("data").resolve())
    gold = json.loads(args.gold.read_text())
    modern = isinstance(gold, dict)
    truth = gold["cases"] if modern else gold
    records = json.loads((args.run / "private-results.json").read_text())
    metrics = []
    for index, record in enumerate(records):
        file = args.run / record["case"] / "observations.json"
        tables = json.loads(file.read_text())["tables"] if file.exists() else []
        detected = []
        seen = set()
        for table in tables:
            for c in table["cells"]:
                provenance = c.get("provenance", {})
                polygon = provenance.get("source_polygon")
                unplaced = any(e["kind"] == "ocr-region" for e in provenance.get("evidence", []))
                if polygon and not unplaced:
                    key = tuple(tuple(point) for point in polygon)
                    if key not in seen:
                        detected.append(polygon)
                        seen.add(key)
        expected = truth[index] if modern else truth[index]["gold"]
        expected_polygons = []
        if modern:
            expected_polygons = [c["polygon"] for c in expected["cells"]]
        else:
            with Image.open(record["source"]) as image:
                size = image.size
            base = (
                max(c["source_region"][2] for c in expected["cells"]) + 20,
                max(c["source_region"][3] for c in expected["cells"]) + 20,
            )
            for c in expected["cells"]:
                x, y, r, b = c["source_region"]
                expected_polygons.append(
                    rotate([(x, y), (r, y), (r, b), (x, b)], truth[index]["rotation"], base, size)
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
        scores = []
        for score, i, j in edges:
            if score >= 0.5 and i not in used_a and j not in used_b:
                used_a.add(i)
                used_b.add(j)
                scores.append(score)
        metrics.append(
            {
                "case": record["case"],
                "geometry_scope": "canonical hypothesis boxes; not verified source grid",
                "cell_boxes": len(detected),
                "gold_boxes": len(expected_polygons),
                "box_matches_iou50": len(scores),
                "box_precision": len(scores) / len(detected) if detected else 0,
                "box_recall": len(scores) / len(expected_polygons),
                "matched_mean_iou": sum(scores) / len(scores) if scores else None,
                "unmatched_predicted_boxes": len(detected) - len(scores),
            }
        )
    args.output.write_text(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
