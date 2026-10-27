"""Synthetic qualification-only worker faults. Never used by product dispatch."""

import os
import sys
import time
from pathlib import Path

from localocr import failsoft, postprocess


def main():
    mode, spool, staging = sys.argv[1:]
    if mode == "parser_timeout":
        setattr(failsoft, "extract", lambda *a, **kw: time.sleep(60))
    elif mode == "writer_timeout":
        setattr(failsoft, "write_failsoft", lambda *a, **kw: time.sleep(60))
    elif mode == "crash":
        os._exit(7)
    elif mode == "resource":

        def memory(*a, **kw):
            raise MemoryError()

        setattr(failsoft, "extract", memory)
    elif mode == "io":

        def denied(*a, **kw):
            raise PermissionError("synthetic")

        setattr(failsoft, "write_failsoft", denied)
    elif mode == "corrupt":
        setattr(failsoft.Workbook, "save", lambda self, path: Path(path).write_bytes(b"corrupt"))
    return postprocess.run_worker(Path(spool), Path(staging))


if __name__ == "__main__":
    raise SystemExit(main())
