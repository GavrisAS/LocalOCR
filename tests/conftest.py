import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def server():
    state: dict[str, Any] = {
        "status": 200,
        "body": None,
        "text": "<table><tr><td>А</td><td>2</td></tr><tr><td></td><td>=1+1</td></tr></table>",
        "requests": [],
        "delay": 0,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args):
            pass

        def do_GET(self):
            self.respond(None)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.respond(payload)

        def respond(self, payload):
            import time

            state["requests"].append((self.path, payload))
            time.sleep(state["delay"])
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            if state["status"] == 302:
                self.send_header("Location", "https://example.com")
            self.end_headers()
            body = state["body"]
            if body is None:
                body = (
                    {"models": [{"name": "glm-ocr:latest"}]}
                    if self.path == "/api/tags"
                    else {"response": state["text"], "done": True, "done_reason": "stop"}
                )
            try:
                self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())
            except BrokenPipeError, ConnectionResetError:
                pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", state
    httpd.shutdown()
    httpd.server_close()
