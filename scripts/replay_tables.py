"""Offline regression replay of private recorded OCR, never a real-inference PASS."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from localocr.excel import write_workbook
from localocr.imaging import encode, load_image
from localocr.ollama import OCRServerError, Settings
from localocr.reconstruction import recognize_document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = json.loads((args.run / "private-results.json").read_text())
    summary = []
    outcomes = []
    for record in results:
        image = load_image(Path(record["source"]))
        case_root = args.run / record["case"]
        trace = json.loads((case_root / "run.json").read_text())
        sidecar = case_root / "observations.json"
        recorded = json.loads(sidecar.read_text()) if sidecar.exists() else {"tables": []}

        class Replay:
            supports_text_recognition = True
            settings = Settings(retries=0)

            def __init__(self):
                self.index = 0

            def check_cancel(self):
                pass

            def recognize(self, content, *, single_table=False):
                expected = trace["requests"][self.index]
                self.index += 1
                if self.index == len(trace["requests"]):
                    self.request_budget_remaining = 0
                if content != encode(image.crop(tuple(expected["region"]))):
                    raise ValueError("Replay input/crop changed")
                self.last_diagnostic = {
                    key: expected[key]
                    for key in (
                        "done",
                        "done_reason",
                        "generation",
                        "eval_count",
                        "prompt_eval_count",
                    )
                    if key in expected
                }
                raw = case_root / f"response-{expected['request']}.txt"
                if raw.exists():
                    return raw.read_text()
                if expected["route"] == "isolated-text-roi" and expected["status"] == "OBSERVED":
                    for table in recorded["tables"]:
                        for cell in table["cells"]:
                            if any(
                                e.get("observation") == expected["request"]
                                and e["kind"] == "text-roi"
                                for e in cell["provenance"]["evidence"]
                            ):
                                return cell["text"]
                raise OCRServerError("RECORDED_PROVIDER_ERROR")

            def recognize_text(self, content):
                return self.recognize(content)

        replay = Replay()
        try:
            document = recognize_document(image, replay, args.output / record["case"])
            # Compare actual canonical values, positions, spans and provenance,
            # without publishing those private values in the replay summary.
            actual = [asdict(t) for t in document.tables]
            matches = actual == recorded["tables"]
            write_workbook(document, args.output / f"{record['case']}.xlsx")
            outcome = document.outcome()
        except ValueError:
            matches = record["status"] == "FAILED"
            outcome = {"status": "FAILED"}
        outcomes.append(
            {"case": record["case"], "status": outcome["status"], "real_inference": False}
        )
        summary.append(
            {
                "case": record["case"],
                "canonical_equal": matches,
                "same_status": record["status"] == outcome["status"],
                "requests_replayed": replay.index,
                "recorded_requests": len(trace["requests"]),
            }
        )
    (args.output / "private-results.json").write_text(json.dumps(outcomes, indent=2))
    (args.output / "summary.json").write_text(
        json.dumps(
            {"mode": "RECORDED_OCR_REPLAY", "real_inference": False, "cases": summary}, indent=2
        )
    )
    if not all(r["canonical_equal"] and r["same_status"] for r in summary):
        raise SystemExit("Replay differs; inspect private output before claiming equivalence")
    print(f"Recorded replay: {len(summary)} identical canonical outcomes; no model inference")


if __name__ == "__main__":
    main()
