"""Bounded synthetic evaluation gates; only aggregate evidence leaves the runner."""

import argparse
import base64
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event
from typing import Any

from frozen_smoke import isolated_environment
from openpyxl import load_workbook
from PIL import Image, ImageDraw
from verify_release import inspect_zip

from localocr import postprocess, runtime
from localocr.ollama import Cancelled


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def qualify(root, version, commit):
    checks = {}
    env = isolated_environment()
    env["QT_QPA_PLATFORM"] = "offscreen"
    with tempfile.TemporaryDirectory(prefix="LocalOCR Русский путь ") as name:
        work = Path(name)
        moved = work / "Распаковано с пробелами" / "LocalOCR"
        shutil.copytree(root, moved)
        cli = moved / "LocalOCR-CLI/LocalOCR-CLI.exe"
        gui = moved / "LocalOCR.exe"
        cwd = work / "Произвольный CWD"
        cwd.mkdir()
        for key in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
            env[key] = str(work / key)
        for full in (False, True):
            subprocess.run(
                [
                    str(gui),
                    *(["--full-gui"] if full else []),
                    "--smoke-test",
                    "--expected-version",
                    version,
                    "--expected-commit",
                    commit,
                ],
                cwd=cwd,
                env=env,
                check=True,
                timeout=30,
            )
        assert json.loads((moved / "config.json").read_text("utf-8"))["fail_soft"] is False
        checks["relocated_simple_full_gui"] = "PASS_STARTUP_ONLY"
        for flag, expected in (("--version", version), ("--build-commit", commit)):
            assert (
                subprocess.check_output([str(cli), flag], cwd=cwd, env=env, timeout=30)
                .decode()
                .strip()
                == expected
            )
        checks["frozen_identity_without_python_path"] = "PASS"
        fixture = work / "Синтетический вход.png"
        image = Image.new("RGB", (320, 120), "white")
        ImageDraw.Draw(image).text((10, 10), "Synthetic OCR 001 42", fill="black")
        image.save(fixture)
        state: dict[str, Any] = {"raw": "", "posts": 0, "expected_token": None, "errors": []}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def respond(self, body):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_GET(self):
                self.respond(
                    {
                        "models": [{"name": "glm-ocr:latest", "digest": "synthetic-fixed"}],
                        "data": [{"id": "glm-ocr:latest"}],
                    }
                )

            def do_POST(self):
                try:
                    assert self.headers.get("Authorization") == state["expected_token"]
                    payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    assert payload["stream"] is False
                    if self.path == "/api/chat/completions":
                        data = payload["messages"][0]["content"]
                        encoded = next(
                            p["image_url"]["url"].split(",", 1)[1]
                            for p in data
                            if p["type"] == "image_url"
                        )
                    else:
                        encoded = payload["images"][0]
                    decoded = Image.open(io.BytesIO(base64.b64decode(encoded, validate=True)))
                    decoded.verify()
                    state["posts"] += 1
                    body = (
                        {
                            "choices": [
                                {"message": {"content": state["raw"]}, "finish_reason": "stop"}
                            ]
                        }
                        if self.path == "/api/chat/completions"
                        else {"response": state["raw"], "done": True}
                    )
                    self.respond(body)
                except Exception as error:
                    state["errors"].append(type(error).__name__)
                    self.send_error(500)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            cases = [
                ("plain", "001\n=1+1\nx\x00y\n" + "x" * 33000, "ollama", None),
                ("html", "<table><tr><td>001</td></tr><tr><td>truncated", "proxy", None),
                ("markdown", "| A | B |\n| --- | --- |\n| 001 |", "chat", None),
                ("token", "synthetic value", "chat", "synthetic-evaluation-only"),
                ("empty", "<think>no observations</think>", "ollama", None),
            ]
            for label, raw, api, token in cases:
                state["raw"] = raw
                state["expected_token"] = "Bearer " + token if token else None
                out = work / label
                command = [
                    str(cli),
                    "convert",
                    str(fixture),
                    "--model",
                    "glm-ocr:latest",
                    "--fail-soft",
                    "--output-dir",
                    str(out),
                ]
                url = f"http://127.0.0.1:{server.server_port}"
                command += (
                    ["--ollama-url", url]
                    if api == "ollama"
                    else ["--provider", "openwebui", "--url", url, "--openwebui-api", api]
                )
                if token:
                    command += ["--api-token", token]
                p = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=60)
                assert p.returncode == 1, (label, p.returncode)
                assert not state["errors"], state["errors"]
                report = json.loads(max(out.glob("report-*.json")).read_text("utf-8"))
                item = report["results"][0] if isinstance(report, dict) else report[0]
                target = out / (fixture.stem + ".xlsx")
                if label == "empty":
                    assert item["status"] == "FAILED" and not item["xlsx_with_data"]
                    assert not target.exists()
                    checks["no_content_no_false_yield"] = "PASS"
                    continue
                assert item["status"] in {"PARTIAL", "REVIEW"} and item["xlsx_with_data"]
                book = load_workbook(target)
                assert "Проверка" in book.sheetnames
                assert any(c.value for s in book if s.title != "Проверка" for row in s for c in row)
                assert all(c.data_type != "f" for s in book for row in s for c in row)
                book.close()
                checks[label + "_multimodal_readback"] = "PASS"
                if label == "plain":
                    before, posts = digest(target), state["posts"]
                    again = subprocess.run(
                        command, cwd=cwd, env=env, capture_output=True, timeout=60
                    )
                    assert (
                        again.returncode == 1
                        and state["posts"] == posts
                        and digest(target) == before
                    )
                    report = json.loads(max(out.glob("report-*.json")).read_text("utf-8"))
                    assert (
                        report[0]["resumed"]
                        if isinstance(report, list)
                        else report["results"][0]["resumed"]
                    )
                    # A foreign existing output with no journal is never overwritten.
                    foreign = work / "foreign"
                    foreign.mkdir()
                    existing = foreign / target.name
                    existing.write_bytes(b"synthetic existing user file")
                    command[command.index(str(out))] = str(foreign)
                    subprocess.run(
                        command, cwd=cwd, env=env, capture_output=True, timeout=60, check=True
                    )
                    assert (
                        existing.read_bytes() == b"synthetic existing user file"
                        and state["posts"] == posts
                    )
                    checks["resume_no_overwrite"] = "PASS"
        finally:
            server.shutdown()
            server.server_close()
        # Actual frozen postprocessor, source parent: exercise parent-only late cancellation.
        old_root, old_argv = runtime.ROOT_OVERRIDE, postprocess.worker_argv
        runtime.ROOT_OVERRIDE = moved
        setattr(
            postprocess,
            "worker_argv",
            lambda s, t: [str(cli), "--localocr-postprocess", str(s), str(t)],
        )
        try:
            target = work / "atomic.xlsx"
            target.write_bytes(b"previous synthetic file")
            cancel = Event()
            try:
                postprocess.convert_raw(
                    "001\n=1+1", target, overwrite=True, cancel=cancel, before_publish=cancel.set
                )
            except Cancelled:
                pass
            else:
                raise AssertionError("Cancellation published a workbook")
            assert target.read_bytes() == b"previous synthetic file"
            postprocess.convert_raw("next observed value", target, overwrite=True)
            book = load_workbook(target)
            assert book["Распознанный текст"]["A1"].value == "next observed value"
            book.close()
            checks["frozen_worker_late_cancel_then_next_readback"] = "PASS"
        finally:
            runtime.ROOT_OVERRIDE = old_root
            setattr(postprocess, "worker_argv", old_argv)
        assert not list(work.rglob(".localocr-pending-*"))
        assert not any(cwd.iterdir())
        assert all(
            not (work / key / "LocalOCR").exists()
            for key in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME")
        )
        assert not (moved / "LocalOCR-CLI/config.json").exists()
        assert not (moved / "_internal/config.json").exists()
        checks["portable_root_scoped_write_audit"] = "PASS"
    return {
        "status": "PASS",
        "platform": sys.platform,
        "version": version,
        "commit": commit,
        "checks": checks,
        "real_ocr": 0,
        "manual_gui": "PENDING",
        "server": "PENDING",
        "embedded": "NOT_BUNDLED",
        "production_release": "NO_GO",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--version", required=True)
    p.add_argument("--commit", required=True)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--zip", type=Path)
    a = p.parse_args()
    started = time.time()
    result = qualify(a.root.resolve(), a.version, a.commit)
    if a.zip:
        result["archive"] = inspect_zip(a.zip)
    result["seconds"] = round(time.time() - started, 2)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
