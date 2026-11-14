"""Shared setup for the BootDoctor tests: state that stays inside tmp_path, and small fake servers."""

from __future__ import annotations

import json
import os
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from thomas.core import boot_checks, boot_doctor, boot_process


def fake_owners(monkeypatch: pytest.MonkeyPatch, commands: dict[int, str] | None = None) -> None:
    """Say which programs hold a listening port (pid -> command line); by default, none that can be found.

    BootDoctor asks netstat, which would name the pytest process that hosts the fake servers below. Both modules
    that hold a reference to the lookups are patched.
    """
    owners = dict(commands or {})
    for module in (boot_doctor, boot_process):
        monkeypatch.setattr(module, "_listening_pids_windows", lambda port: list(owners))
        monkeypatch.setattr(module, "_pid_cmdline", lambda pid: owners.get(pid, ""))


def isolate_offline_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every folder the offline checks read or test-write at tmp_path, and fail if one escapes.

    The checks scan the state folders for databases and test-write into them. A test that let them
    fall back to the current directory (AppConfig() does) would be reading this checkout's live
    databases, so the guard turns that into a failure instead of a quiet read.
    """
    for key in [name for name in os.environ if name.startswith("THOMAS_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    # Deleted with the rest above, these two leave a test that builds an app in your real secret store and ~/.thomas.
    monkeypatch.setenv("THOMAS_SHARED_SECRET_STORE_DIR", str(tmp_path / "shared"))
    monkeypatch.setenv("THOMAS_OWNED_ROOT", str(tmp_path / "owned"))
    inside = tmp_path.resolve()
    real = boot_checks.state_bases

    def guarded(root: Path, memory_root: Path | None = None) -> list[Path]:
        bases = real(root, memory_root)
        outside = [base for base in bases if base != inside and inside not in base.parents]
        assert not outside, f"the offline checks would touch {outside}, outside {inside}"
        return bases

    monkeypatch.setattr(boot_checks, "state_bases", guarded)


class Quiet(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ForeignServer(Quiet):
    """Some other program: an HTML 404 for everything."""

    def do_GET(self) -> None:
        self.send(404, b"<html>some other program</html>", "text/html")


class JsonWithoutVersion(Quiet):
    """Another program that answers 200 with JSON, but not Thomas's health payload."""

    def do_GET(self) -> None:
        self.send(200, json.dumps({"status": "ok"}).encode(), "application/json")


class JsonVersionOnly(Quiet):
    """Another program that answers 200 with JSON carrying a "version" but no "status"."""

    def do_GET(self) -> None:
        self.send(200, json.dumps({"version": "0.0.0"}).encode(), "application/json")


class JsonList(Quiet):
    """Another program whose JSON body is not an object at all."""

    def do_GET(self) -> None:
        self.send(200, b"[1, 2, 3]", "application/json")


class Broken(Quiet):
    """A program that accepts the connection and answers 500 to everything."""

    def do_GET(self) -> None:
        self.send(500, b"broken", "text/plain")


class ThomasServer(Quiet):
    def do_GET(self) -> None:
        if self.path == "/api/health":
            self.send(200, json.dumps({"status": "ok", "version": "0.0.0"}).encode(), "application/json")
        else:
            self.send(200, b"ok", "text/plain")


# The fake servers only ever bind inside this block, so a run cannot land on a port another program uses.
PORT_BLOCK = range(22120, 22130)


@contextmanager
def listener(handler: type[BaseHTTPRequestHandler]) -> Iterator[int]:
    """Serve ``handler`` on the first free port of PORT_BLOCK."""
    for port in PORT_BLOCK:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError:
            continue
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield port
        finally:
            server.shutdown()
            server.server_close()
        return
    pytest.skip(f"no free port in {PORT_BLOCK.start}-{PORT_BLOCK.stop - 1}")


@contextmanager
def raw_listener(payload: bytes = b"this is not http\r\n") -> Iterator[int]:
    """A program that is not a web server: it reads what it is sent, answers with ``payload`` and hangs up.

    An HTTP client reading that answer raises http.client.BadStatusLine, which is not an OSError.
    """
    for port in PORT_BLOCK:
        server = socket.socket()
        try:
            server.bind(("127.0.0.1", port))
        except OSError:
            server.close()
            continue
        server.listen(8)
        server.settimeout(0.1)
        stop = threading.Event()

        def serve(server: socket.socket = server, stop: threading.Event = stop) -> None:
            while not stop.is_set():
                try:
                    conn, _addr = server.accept()
                except OSError:  # the accept timed out, or the socket was closed
                    continue
                with conn:
                    try:
                        conn.settimeout(1.0)
                        conn.recv(4096)  # read the request first, so closing does not reset the answer away
                        conn.sendall(payload)
                    except OSError:
                        pass  # a caller that only connected and left

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield port
        finally:
            stop.set()
            thread.join(timeout=2.0)
            server.close()
        return
    pytest.skip(f"no free port in {PORT_BLOCK.start}-{PORT_BLOCK.stop - 1}")


def free_port() -> int:
    """The first port of PORT_BLOCK that nothing is listening on."""
    for port in PORT_BLOCK:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    pytest.skip(f"no free port in {PORT_BLOCK.start}-{PORT_BLOCK.stop - 1}")
