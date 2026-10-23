"""Small explicit Direct OCR control benchmark; never used by the application runtime."""

import argparse
import base64
import hashlib
import io
import json
import time
from pathlib import Path

from localocr.imaging import (
    content_mask,
    detect_layout,
    grid_hypothesis,
    load_image,
    region_has_ink,
)
from localocr.ollama import OllamaClient, Settings
from localocr.service import discover
from localocr.synthetic import generate
from localocr.tables import parse_response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="glm-ocr:latest")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--complete-chat-control", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=args.complete_chat_control)
    client = OllamaClient(Settings(url=args.url, model=args.model, retries=0, timeout=args.timeout))
    client.doctor()
    manifest = {
        "version": client.request("GET", "/api/version"),
        "model": client.model_identity,
        "show": client.request("POST", "/api/show", {"model": args.model}),
    }
    if args.complete_chat_control:
        previous = json.loads((args.output / "environment.json").read_text())
        if previous["model"]["digest"] != manifest["model"]["digest"]:
            raise ValueError("Benchmark model changed")
    else:
        (args.output / "environment.json").write_text(json.dumps(manifest, indent=2))
    # Deterministic first/last images and two held-out generated controls. Input
    # selection never depends on names or recognized content.
    paths = discover(args.source)
    real = [load_image(paths[0]), load_image(paths[-1])]
    controls = [generate(713091 + i, simple=True) for i in range(2)]
    inputs = [(f"real-{i + 1}", im, None) for i, im in enumerate(real)] + [
        (f"control-{i + 1}", case.image, case.gold) for i, case in enumerate(controls)
    ]
    results: list[dict] = (
        json.loads((args.output / "metrics.json").read_text()) if args.complete_chat_control else []
    )

    def run(
        name,
        image,
        gold,
        *,
        predict=16000,
        stop=True,
        scale=1.0,
        encoding="PNG",
        endpoint="/api/generate",
        task="Table Recognition:",
    ):
        if len(results) >= 18:
            raise ValueError("Benchmark hard cap: 18 calls")
        if scale != 1:
            image = image.resize((round(image.width * scale), round(image.height * scale)))
        buffer = io.BytesIO()
        image.save(buffer, format=encoding, **({"quality": 95} if encoding == "JPEG" else {}))
        content = buffer.getvalue()
        encoded = base64.b64encode(content).decode("ascii")
        options = {"temperature": 0, "seed": 0, "num_ctx": 32768, "num_predict": predict}
        if stop and task == "Table Recognition:":
            options["stop"] = ["</table>"]
        payload = {"model": args.model, "stream": False, "options": options}
        if endpoint == "/api/chat":
            payload["messages"] = [{"role": "user", "content": task, "images": [encoded]}]
        else:
            payload.update(prompt=task, images=[encoded])
        record: dict = {
            "input": name,
            "image_size": image.size,
            "encoded_sha256": hashlib.sha256(content).hexdigest(),
            "endpoint": endpoint,
            "task": task,
            "encoding": encoding,
            "scale": scale,
            "generation": options,
            "digest": client.model_identity["digest"],
            "text_coverage": None,
            "human_gold": False,
            "parseable": False,
        }
        started = time.monotonic()
        try:
            data = client.request("POST", endpoint, payload)
            (args.output / f"private-response-{len(results) + 1}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2)
            )
            record.update(
                {
                    k: data.get(k)
                    for k in (
                        "done",
                        "done_reason",
                        "eval_count",
                        "prompt_eval_count",
                        "eval_duration",
                        "prompt_eval_duration",
                        "load_duration",
                        "total_duration",
                    )
                }
            )
            text = data.get("response", data.get("message", {}).get("content", ""))
            record["response_characters"] = len(text)
            record["thinking_output"] = (
                bool(data.get("thinking") or data.get("message", {}).get("thinking"))
                or "<think>" in text
            )
            if task == "Text Recognition:":
                record["nonempty_text_observation"] = bool(text.strip())
            else:
                if stop and data.get("done_reason") == "stop" and "</table>" not in text.lower():
                    text += "</table>"
                try:
                    document = parse_response(text)
                    record["parseable"] = True
                    record["anchors"] = sum(bool(c.text) for t in document.tables for c in t.cells)
                    layouts = detect_layout(image)
                    record["geometry_shape_agreement"] = len(layouts) == len(
                        document.tables
                    ) and all(
                        (t.rows, t.columns) == (len(layout.ys) - 1, len(layout.xs) - 1)
                        for t, layout in zip(document.tables, layouts)
                    )
                    if gold is not None and len(document.tables) == 1:
                        table = document.tables[0]
                        expected = gold.grid()
                        actual = table.grid()
                        matches = sum(
                            key in actual
                            and (actual[key].text, actual[key].rowspan, actual[key].colspan)
                            == (cell.text, cell.rowspan, cell.colspan)
                            for key, cell in expected.items()
                        )
                        record.update(
                            synthetic_matched_slots=matches,
                            synthetic_expected_slots=len(expected),
                            text_coverage=matches / len(expected),
                        )
                except ValueError as error:
                    record["parse_error"] = str(error)
        except Exception as error:
            record["error"] = {"type": type(error).__name__, "reason": str(error)[:200]}
        record["seconds"] = round(time.monotonic() - started, 3)
        record["runner"] = client.request("GET", "/api/ps")
        record["digest_after"] = next(
            m["digest"]
            for m in client.request("GET", "/api/tags")["models"]
            if m["name"] == args.model
        )
        results.append(record)
        (args.output / "metrics.json").write_text(json.dumps(results, indent=2))
        print(
            len(results),
            name,
            task,
            endpoint,
            predict,
            stop,
            record.get("done_reason"),
            record["parseable"],
            record["seconds"],
            flush=True,
        )

    if args.complete_chat_control:
        if len(results) != 17:
            raise ValueError("Expected the original 17-call bounded benchmark")
        run(*inputs[2], endpoint="/api/chat")
        return
    # Establish actual OCR correctness of the chat path on a known control
    # before comparing difficult real inputs; no endpoint migration by guess.
    run(*inputs[2], endpoint="/api/chat")
    for name, image, gold in inputs:
        for predict in (8000, 16000):
            run(name, image, gold, predict=predict)
    for name, image, gold in inputs[:2]:
        run(name, image, gold, stop=False)
        run(name, image, gold, endpoint="/api/chat")
        run(name, image, gold, scale=0.75)
    run(inputs[0][0], real[0], None, encoding="JPEG")
    # Same independent enclosed ROI, official text vs table prompt. No per-cell
    # enumeration in the runtime or the benchmark.
    mask = content_mask(real[0])
    for layout in detect_layout(real[0]):
        hypothesis = grid_hypothesis(real[0], layout)
        for row in range(len(layout.ys) - 1):
            for column in range(len(layout.xs) - 1):
                box = (layout.xs[column], layout.ys[row], layout.xs[column + 1], layout.ys[row + 1])
                if hypothesis.encloses(row, column) and region_has_ink(mask, box):
                    for task in ("Text Recognition:", "Table Recognition:"):
                        run("enclosed-roi", real[0].crop(box), None, task=task)
                    return


if __name__ == "__main__":
    main()
