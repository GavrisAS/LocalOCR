"""Bounded opt-in parser/writer, small metadata IPC, parent-only publication.

Raw OCR travels only in a permission-restricted owned spool, never argv/stdout.
No inference occurs here. Both stages run in one disposable owned process.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event

from localocr.failsoft import MAX_RESPONSE
from localocr.journal import atomic_json, file_hash
from localocr.ollama import Cancelled
from localocr.runtime import portable_root
from localocr.supervisor import launch_owned, terminate_owned

PARSER_SECONDS = 10.0
WRITER_SECONDS = 30.0
MEMORY_BYTES = 2 * 1024**3
MAX_WORKBOOK_BYTES = 64 * 1024**2
MAX_METADATA_BYTES = 64 * 1024


def worker_argv(spool, staging):
    args = ["--localocr-postprocess", str(spool), str(staging)]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "localocr.postprocess", *args]


def bounded_json(path):
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError("RESOURCE_FAILURE")
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def spool_lease(path):
    stream = (path / "lease.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            if not stream.read(1):
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        stream.close()


def recover_spools(work):
    # Only our exact marker + unlocked lease authorizes stale data cleanup.
    # Live parents retain the lock. Do not follow symlinks or delete other work.
    for path in work.glob("job-*"):
        if path.is_symlink() or not path.is_dir():
            continue
        marker = path / "owner.json"
        if not marker.is_file() or marker.is_symlink():
            continue
        try:
            with spool_lease(path):
                info = bounded_json(marker)
                if info.get("schema") != "localocr-postprocess/1":
                    continue
                pending = Path(info["pending"])
                if (
                    pending.name.startswith(".localocr-pending-")
                    and not pending.is_symlink()
                    and (pending / "owner.json").is_file()
                    and bounded_json(pending / "owner.json") == {"spool": str(path.resolve())}
                ):
                    shutil.rmtree(pending)
                # Keep lock file open on POSIX; Windows permits removal after close.
            shutil.rmtree(path)
        except OSError, ValueError, KeyError:
            # Locked or inaccessible artifacts are not grounds to kill a PID.
            continue


def convert_raw(
    raw,
    target,
    *,
    truncated=False,
    completion=None,
    model_id="",
    diagnostics=None,
    normalization=None,
    cancel=None,
    overwrite=False,
    before_publish=None,
):
    cancel = cancel or Event()
    if cancel.is_set():
        raise Cancelled("CANCELLED")
    if len(raw) > MAX_RESPONSE:
        raise ValueError("RESOURCE_FAILURE")
    work = portable_root() / "work" / "postprocess"
    work.mkdir(parents=True, exist_ok=True)
    recover_spools(work)
    target.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    # Same filesystem staging preserves exclusive hard-link publication.
    with (
        tempfile.TemporaryDirectory(prefix="job-", dir=work) as private,
        tempfile.TemporaryDirectory(prefix=".localocr-pending-", dir=target.parent) as pending,
        spool_lease(Path(private)),
    ):
        spool, staging = Path(private), Path(pending)
        os.chmod(spool, 0o700)
        atomic_json(
            spool / "owner.json",
            {"schema": "localocr-postprocess/1", "pending": str(staging.resolve())},
        )
        atomic_json(staging / "owner.json", {"spool": str(spool.resolve())})
        (spool / "raw.txt").write_text(raw, encoding="utf-8", errors="surrogatepass")
        atomic_json(
            spool / "input.json",
            {
                "truncated": truncated,
                "completion": completion or {},
                "model_id": model_id,
                "save_layout": diagnostics is not None,
                "normalization": normalization or {},
            },
        )
        process = launch_owned(
            worker_argv(spool.resolve(), staging.resolve()),
            cwd=portable_root(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            memory_bytes=MEMORY_BYTES,
        )
        writer_started = None
        try:
            while process.poll() is None:
                if cancel.is_set():
                    raise Cancelled("CANCELLED")
                now = time.monotonic()
                if writer_started is None and (spool / "parsed.json").exists():
                    writer_started = bounded_json(spool / "parsed.json")["parser_finished"]
                    if writer_started - started > PARSER_SECONDS:
                        raise TimeoutError("PARSER_TIMEOUT")
                if writer_started is None and now - started >= PARSER_SECONDS:
                    raise TimeoutError("PARSER_TIMEOUT")
                if writer_started is not None and now - writer_started >= WRITER_SECONDS:
                    raise TimeoutError("WRITER_TIMEOUT")
                if now - started >= PARSER_SECONDS + WRITER_SECONDS:
                    raise TimeoutError("WRITER_TIMEOUT" if writer_started else "PARSER_TIMEOUT")
                cancel.wait(0.02)
            if cancel.is_set():
                raise Cancelled("CANCELLED")
            exit_code = process.poll()
            if time.monotonic() - started >= PARSER_SECONDS + WRITER_SECONDS:
                raise TimeoutError("WRITER_TIMEOUT" if writer_started else "PARSER_TIMEOUT")
            if not (spool / "result.json").is_file():
                raise ValueError("RESOURCE_FAILURE" if exit_code else "WRITER_FAILURE")
            metadata = bounded_json(spool / "result.json")
            if metadata.get("error"):
                raise ValueError(metadata["error"])
            parsed_at = bounded_json(spool / "parsed.json")["parser_finished"]
            if parsed_at - started > PARSER_SECONDS:
                raise TimeoutError("PARSER_TIMEOUT")
            if metadata["finished_at"] - parsed_at > WRITER_SECONDS:
                raise TimeoutError("WRITER_TIMEOUT")
            if exit_code or not metadata.get("outcome", {}).get("xlsx_with_data"):
                raise ValueError("WRITER_FAILURE")
            artifact = staging / "ready.xlsx"
            if (
                artifact.stat().st_size > MAX_WORKBOOK_BYTES
                or file_hash(artifact) != metadata["sha256"]
            ):
                raise ValueError("RESOURCE_FAILURE")
            if diagnostics is not None and (spool / "layout.json").exists():
                diagnostics.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(spool / "layout.json", diagnostics / "layout-provenance.json")
            if before_publish:
                before_publish()
            if cancel.is_set():
                raise Cancelled("CANCELLED")
            if overwrite:
                os.replace(artifact, target)
            else:
                os.link(artifact, target)
            return metadata
        finally:
            terminate_owned(process)


def run_worker(spool, staging):
    # Linux address space/file size caps; Windows job memory is set before resume.
    if os.name == "posix":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_WORKBOOK_BYTES, MAX_WORKBOOK_BYTES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    stage = "parser"
    try:
        from localocr.failsoft import (
            FailSoftDocument,
            extract,
            failure_code,
            result_metrics,
            write_failsoft,
        )

        started = time.monotonic()
        options = bounded_json(spool / "input.json")
        if (spool / "raw.txt").stat().st_size > MAX_RESPONSE * 4:
            raise ValueError("RESOURCE_FAILURE")
        raw = (spool / "raw.txt").read_text(encoding="utf-8", errors="surrogatepass")
        ex = extract(
            raw,
            truncated=options["truncated"],
            model_id=options.get("model_id", ""),
            completion=options.get("completion"),
        )
        if options.get("save_layout"):
            atomic_json(
                spool / "layout.json",
                {
                    "schema": "deepseek-layout/1",
                    "metadata": ex.layout_metadata,
                    "uncertain": ex.layout_uncertain,
                },
            )
        document = FailSoftDocument(
            ex.document.tables,
            ex.document.issues,
            options["normalization"],
            ex.lines,
            ex.codes,
            ex.source_format,
        )
        document.extraction_metrics = result_metrics(ex)
        document.validate()
        parsed = time.monotonic()
        atomic_json(spool / "parsed.json", {"stage": "writer", "parser_finished": parsed})
        stage = "writer"
        artifact = staging / "ready.xlsx"
        write_failsoft(document, artifact)
        outcome = document.outcome()
        shapes = [(t.rows, t.columns) for t in document.tables]
        metadata = dict(
            outcome=outcome,
            tables=len(shapes),
            shapes=shapes,
            sha256=file_hash(artifact),
            finished_at=time.monotonic(),
            stage_seconds={"parser": parsed - started, "writer": time.monotonic() - parsed},
        )
        if os.name == "posix":
            metadata["child_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        atomic_json(spool / "result.json", metadata)
    except Exception as error:
        from localocr.failsoft import failure_code

        code = failure_code(error, "xlsx" if stage == "writer" else "parser")
        if code == "MODEL_FAILURE":
            code = "PARSER_FAILURE" if stage == "parser" else "WRITER_FAILURE"
        atomic_json(spool / "result.json", {"error": code, "stage": stage})
        return 1
    return 0


def dispatch():
    if len(sys.argv) == 4 and sys.argv[1] == "--localocr-postprocess":
        raise SystemExit(run_worker(Path(sys.argv[2]), Path(sys.argv[3])))


if __name__ == "__main__":
    dispatch()
