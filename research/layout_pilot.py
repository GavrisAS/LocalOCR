"""Development-only Paddle pilot; never imported by the product runtime.

Run with the separate Python 3.12 environment. All artifacts must be under data/.
Fetch is an explicit development operation, not part of inference.
"""

import argparse
import hashlib
import importlib
import json
import os
import socket
import time
import urllib.request
from pathlib import Path
from typing import Never

MODELS = {
    "layout": "PP-DocLayoutV3",
    "orientation": "PP-LCNet_x1_0_doc_ori",
    "classification": "PP-LCNet_x1_0_table_cls",
    "wired_structure": "SLANeXt_wired",
    "wireless_structure": "SLANeXt_wireless",
    "wired_cells": "RT-DETR-L_wired_table_cell_det",
    "wireless_cells": "RT-DETR-L_wireless_table_cell_det",
    "text_detection": "PP-OCRv5_server_det",
    "text_recognition": "cyrillic_PP-OCRv5_mobile_rec",
}


def private(path):
    path = Path(path).resolve()
    path.relative_to(Path("data").resolve())
    return path


def fetch(root, pinned=None):
    root.mkdir(parents=True, exist_ok=True)
    previous = root / "manifest.json"
    identities = (
        json.loads(pinned.read_text())
        if pinned
        else json.loads(previous.read_text())
        if previous.exists()
        else {}
    )
    manifest = {}
    for role, name in MODELS.items():
        expected = identities.get(role)
        if expected and expected["repo"] != f"PaddlePaddle/{name}":
            raise ValueError("Manifest model role mismatch")
        target = root / name
        target.mkdir(exist_ok=True)
        revision_path = "/revision/" + expected["revision"] if expected else ""
        with urllib.request.urlopen(
            f"https://huggingface.co/api/models/PaddlePaddle/{name}{revision_path}", timeout=30
        ) as response:
            meta = json.load(response)
        revision = meta["sha"]
        if expected and revision != expected["revision"]:
            raise ValueError("Pinned revision mismatch")
        metadata = target / "hub-metadata.json"
        if metadata.exists() and json.loads(metadata.read_text())["sha"] != revision:
            raise ValueError("Upstream revision changed; use a new weight directory")
        metadata.write_text(json.dumps(meta, indent=2))
        files = []
        for item in meta["siblings"]:
            filename = item["rfilename"]
            if filename not in {
                "inference.json",
                "inference.pdiparams",
                "inference.yml",
                "README.md",
                "LICENSE",
                "LICENSE.txt",
            }:
                continue
            url = f"https://huggingface.co/PaddlePaddle/{name}/resolve/{revision}/{filename}"
            dest = target / filename
            if not dest.exists():
                print("FETCH", name, filename, flush=True)
                temporary = dest.with_suffix(dest.suffix + ".tmp")
                with (
                    urllib.request.urlopen(url, timeout=60) as response,
                    temporary.open("wb") as output,
                ):
                    while block := response.read(1024 * 1024):
                        output.write(block)
                temporary.replace(dest)
            if expected:
                expected_file = next(f for f in expected["files"] if f["file"] == filename)
                if hashlib.sha256(dest.read_bytes()).hexdigest() != expected_file["sha256"]:
                    raise ValueError("Pinned file hash mismatch")
            files.append(
                {
                    "file": filename,
                    "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
                    "bytes": dest.stat().st_size,
                }
            )
        manifest[role] = {
            "repo": f"PaddlePaddle/{name}",
            "revision": revision,
            "license": meta.get("cardData", {}).get("license"),
            "files": files,
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2))


def run(args):
    # Cache locations are private and portable; inference requires explicit local weights.
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(args.output / "paddlex-cache")

    def no_network(*args, **kwargs) -> Never:
        raise RuntimeError("RESEARCH_INFERENCE_NETWORK_FORBIDDEN")

    socket.socket.connect = no_network
    setattr(socket, "create_connection", no_network)
    import paddleocr  # ty: ignore[unresolved-import]

    models = json.loads((args.weights / "manifest.json").read_text())

    def model(role):
        item = models[role]
        directory = args.weights / item["repo"].split("/")[-1]
        for entry in item["files"]:
            if (
                hashlib.sha256((directory / entry["file"]).read_bytes()).hexdigest()
                != entry["sha256"]
            ):
                raise ValueError("Weight hash mismatch")
        return str(directory)

    started = time.monotonic()
    if args.task == "layout":
        pipeline = paddleocr.LayoutDetection(
            model_name="PP-DocLayoutV3",
            model_dir=model("layout"),
            device="cpu",
            enable_mkldnn=False,
            cpu_threads=4,
        )
    else:
        config = importlib.import_module("paddlex.inference").load_pipeline_config(
            "table_recognition_v2"
        )
        config["SubModules"]["TableOrientationClassify"]["model_dir"] = model("orientation")
        pipeline = paddleocr.TableRecognitionPipelineV2(
            paddlex_config=config,
            layout_detection_model_name="PP-DocLayoutV3",
            layout_detection_model_dir=model("layout"),
            doc_orientation_classify_model_dir=model("orientation"),
            table_classification_model_dir=model("classification"),
            wired_table_structure_recognition_model_dir=model("wired_structure"),
            wireless_table_structure_recognition_model_dir=model("wireless_structure"),
            wired_table_cells_detection_model_dir=model("wired_cells"),
            wireless_table_cells_detection_model_dir=model("wireless_cells"),
            text_detection_model_name="PP-OCRv5_server_det",
            text_detection_model_dir=model("text_detection"),
            text_recognition_model_name="cyrillic_PP-OCRv5_mobile_rec",
            text_recognition_model_dir=model("text_recognition"),
            use_doc_orientation_classify=True,
            use_doc_unwarping=False,
            device="cpu",
            enable_mkldnn=False,
            cpu_threads=4,
        )
        pipeline.export_paddlex_config_to_yaml(str(args.output / "effective-config.yaml"))
    init_seconds = time.monotonic() - started
    records = []
    inputs = [
        p
        for p in sorted(args.input.iterdir())
        if p.suffix.lower() in {".png", ".jpg", ".tif", ".jpeg"}
    ]
    if args.index is not None:
        inputs = [inputs[args.index]]
    for path in inputs:
        case = args.output / path.stem
        case.mkdir()
        started = time.monotonic()
        record = {
            "input": str(path),
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        try:
            for result in pipeline.predict(str(path)):
                result.save_to_json(str(case))
            record["status"] = "PROCESSED_UNVERIFIED"
        except Exception as error:
            record.update(status="ERROR", error=type(error).__name__ + ": " + str(error))
        record["seconds"] = time.monotonic() - started
        records.append(record)
        (args.output / "results.json").write_text(
            json.dumps({"init_seconds": init_seconds, "records": records}, indent=2)
        )
        print(path.stem, record["status"], round(record["seconds"], 3), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["fetch", "table", "layout"])
    parser.add_argument("--weights", type=private, required=True)
    parser.add_argument("--input", type=private)
    parser.add_argument("--output", type=private)
    parser.add_argument("--index", type=int)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.task == "fetch":
        fetch(args.weights, args.manifest)
    else:
        if args.input is None or args.output is None:
            parser.error("input and output required")
        args.output.mkdir(parents=True, exist_ok=False)
        run(args)


if __name__ == "__main__":
    main()
