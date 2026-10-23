"""Development-only PP-DocLayoutV3 regions + existing local Ollama transport.

Table-region boxes never become cell boxes. Parsed HTML is explicitly unplaced.
"""

import argparse
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from localocr.imaging import encode
from localocr.ollama import OllamaClient, Settings
from localocr.tables import parse_response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.resolve().relative_to(Path("data").resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    client = OllamaClient(Settings(timeout=15, retries=0, max_calls=2, max_image_seconds=30))
    env = {
        "version": client.request("GET", "/api/version"),
        "models": client.request("GET", "/api/tags"),
        "runner": client.request("GET", "/api/ps"),
        "settings": asdict(client.settings),
    }
    (args.output / "environment.json").write_text(json.dumps(env, indent=2))
    records = []
    layouts = json.loads((args.layout / "results.json").read_text())
    for index, entry in enumerate(layouts["records"], 1):
        path = Path(entry["input"])
        case = f"CASE-{index:02d}"
        output = args.output / case
        output.mkdir()
        started = time.monotonic()
        record = {
            "case": case,
            "source": str(path),
            "source_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
            "requests": [],
            "status": "REVIEW",
            "human_verified": False,
        }
        predictions = list((args.layout / path.stem).glob("*.json"))
        tables = []
        reasons = []
        raw_layout = json.loads(predictions[0].read_text()) if predictions else {}
        regions = sorted(
            [b for b in raw_layout.get("boxes", []) if b["label"] == "table"],
            key=lambda b: (b["coordinate"][1], b["coordinate"][0]),
        )
        with Image.open(path) as original:
            image = original.convert("RGB")
        for region in regions[:2]:
            if time.monotonic() - started + entry["seconds"] >= 15:
                reasons.append("DEADLINE_NO_NEXT_REQUEST")
                break
            x1, y1, x2, y2 = region["coordinate"]
            box = (
                max(0, int(x1)),
                max(0, int(y1)),
                min(image.width, int(x2)),
                min(image.height, int(y2)),
            )
            before = time.monotonic()
            try:
                raw = client.recognize(encode(image.crop(box)), single_table=True)
                (output / f"response-{len(record['requests']) + 1}.txt").write_text(raw)
                document = parse_response(raw)
                for table in document.tables:
                    item = asdict(table)
                    for cell in item["cells"]:
                        cell["provenance"] = {
                            "state": "unverified",
                            "evidence": [{"kind": "ocr-region", "region": box}],
                            "source_polygon": None,
                        }
                    item["issues"] = [{"code": "UNPLACED_OBSERVATION"}]
                    tables.append(item)
            except Exception as error:
                reasons.append(type(error).__name__)
            record["requests"].append(
                {**client.last_diagnostic, "seconds": time.monotonic() - before}
            )
        if len(regions) > 2:
            reasons.append("REGIONS_EXCEED_CALL_BUDGET")
        if not regions:
            reasons.append("NO_TABLE_REGION")
        record.update(
            seconds=round(time.monotonic() - started + entry["seconds"], 3),
            layout_seconds=entry["seconds"],
            anchors=sum(bool(c["text"].strip()) for t in tables for c in t["cells"]),
            reason_codes=reasons + ["CELL_GEOMETRY_UNCONFIRMED"],
            table_regions=len(regions),
        )
        (output / "observations.json").write_text(
            json.dumps(
                {"tables": tables, "ambiguity": record["reason_codes"]},
                ensure_ascii=False,
                indent=2,
            )
        )
        records.append(record)
        (args.output / "private-results.json").write_text(json.dumps(records, indent=2))
        print(case, record["anchors"], record["seconds"], flush=True)


if __name__ == "__main__":
    main()
