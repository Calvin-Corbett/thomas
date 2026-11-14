"""Stand-ins for what the Asset Studio row talks to, so its tests run real processes with no fakes in Thomas.

A job is a real child process, so it needs something to wait on: ``NeverAnswers`` takes a connection and says nothing. A
ComfyUI is a real server in a process of its own, because what off does to one is the question, and ``end_comfy`` ends
it, since the point of the test is that Thomas cannot.

Asserts stay in the test that calls this, because pytest rewrites them only in a test module.
"""

from __future__ import annotations

import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import TracebackType
from typing import Any

COMFY = """\
import http.server
import json
import os
import sys


class Comfy(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/end":
            os._exit(0)
        body = json.dumps({"queue_running": [], "queue_pending": [], "system": {"python_version": "3"}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Comfy).serve_forever()
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def comfy_script(folder: Path) -> Path:
    script = folder / "stand_in_comfy.py"
    script.write_text(COMFY, encoding="utf-8")
    return script


def _ask_comfy(port: int, path: str) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as answer:
            return answer.status == 200
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return False


def comfy_is_up(port: int) -> bool:
    return _ask_comfy(port, "/queue")


def end_comfy(port: int) -> None:
    _ask_comfy(port, "/end")


def job_waiting_on(port: int) -> dict[str, Any]:
    """A real connector's real action, whose child process waits on ``port`` for as long as it is left."""
    return {
        "connector_id": "comfyui",
        "action_id": "get_history",
        "payload": {"server_url": f"http://127.0.0.1:{port}", "prompt_id": "p1", "timeout_s": 120},
    }


class NeverAnswers:
    """A port that takes a connection and what is sent on it, and never answers."""

    def __init__(self) -> None:
        self._listening = socket.socket()
        self._listening.bind(("127.0.0.1", 0))
        self._listening.listen(16)
        self.port = int(self._listening.getsockname()[1])
        self._held: list[socket.socket] = []

    def __enter__(self) -> NeverAnswers:
        threading.Thread(target=self._hold, daemon=True).start()
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None
    ) -> None:
        self._listening.close()
        for held in self._held:
            held.close()

    def _hold(self) -> None:
        while True:
            try:
                held, _ = self._listening.accept()
            except OSError:
                return
            held.setblocking(False)
            self._held.append(held)

    def received(self) -> bytes:
        """What the newest connection has sent, left there to be read again."""
        for held in reversed(self._held):
            try:
                return held.recv(4096, socket.MSG_PEEK)
            except BlockingIOError:
                continue
            except OSError:
                return b""
        return b""

    def still_held_open(self) -> bool:
        """True if the sender of the newest connection has not gone, so what it was doing is still going on."""
        try:
            data = self._held[-1].recv(1 << 20)
        except BlockingIOError:
            return True
        except OSError:
            return False
        return bool(data)
