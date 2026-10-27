"""Owned native subprocess isolation. No shell, fork, arbitrary code or model loading.

Existing llama-server is a bounded persistent worker with one inference slot.
A failed worker is closed and the next job starts a fresh owned process.
"""

import os
import signal
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from threading import Event, Thread

from localocr.ollama import Cancelled


def process_options():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


class OwnedPopen(subprocess.Popen):
    def poll(self):
        # Keep an exited POSIX leader waitable until group cleanup. Its PID/PGID
        # cannot be reused in the exit/descendant/cancel race before wait().
        if os.name == "posix" and self.returncode is None:
            info = os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if info is None:
                return None
            return info.si_status if info.si_code == os.CLD_EXITED else -info.si_status
        return super().poll()


def launch_owned(argv, *, memory_bytes=None, **kwargs):
    options = process_options()
    if os.name == "nt":
        options["creationflags"] |= 0x4  # CREATE_SUSPENDED: no pre-assignment race
    process = subprocess.Popen(argv, **kwargs, **options)
    if os.name == "posix" and isinstance(process, OwnedPopen.__bases__[0]):
        process.__class__ = OwnedPopen
    if os.name == "nt":
        try:
            from localocr.windows_job import OwnedJob

            setattr(process, "owned_job", OwnedJob(process, memory_bytes))
        except BaseException:
            process.kill()
            process.wait(timeout=2)
            raise
    return process


def terminate_owned(process, grace=2.0):
    """Terminate only our held process/job; never taskkill a possibly reused PID."""
    if getattr(process, "owned_cleaned", False):
        return
    if os.name == "nt":
        job = getattr(process, "owned_job", None)
        if job is None:
            # Legacy/test handle: fail closed for tree guarantees; kill own handle.
            if process.poll() is None:
                process.kill()
        else:
            job.close()  # KILL_ON_JOB_CLOSE includes descendants after leader exit.
        process.wait(timeout=grace)
    else:
        alive = process.poll() is None
        if alive:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + grace
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
        # launch_owned retains a zombie leader, preventing PID/PGID reuse.
        # For legacy Popen handles only signal a still-live owned leader.
        if isinstance(process, OwnedPopen) or process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=grace)
    process.owned_cleaned = True


@dataclass(frozen=True)
class WorkerResult:
    exit_code: int
    seconds: float
    output_bytes: int
    worker_crashed: bool


def run_owned(argv, *, cwd, timeout, cancel=None):
    """Generic finite worker gate. Drain bounded private bytes, expose metadata only.

    Producers write their structured output to an explicitly owned temporary cwd;
    callers validate it only after normal exit. This API never parses stdout as OCR.
    """
    cancel = cancel or Event()
    started = time.monotonic()
    process = launch_owned(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    captured = deque(maxlen=16)
    count = [0]

    def drain():
        assert process.stdout is not None
        while chunk := process.stdout.read(4096):
            captured.append(chunk)
            count[0] += len(chunk)

    reader = Thread(target=drain, daemon=True)
    reader.start()
    try:
        while process.poll() is None:
            if cancel.is_set():
                raise Cancelled("CANCELLED")
            if time.monotonic() - started >= timeout:
                raise TimeoutError("TIMEOUT")
            cancel.wait(0.02)
        reader.join(timeout=2)
        code = process.poll()
        return WorkerResult(code, time.monotonic() - started, count[0], code != 0)
    finally:
        terminate_owned(process)
        reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
        captured.clear()
