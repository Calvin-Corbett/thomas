"""A tiny Thomas that serves the real chat page and answers every API it asks.

Every stub is the smallest body the page tolerates at boot. The reply to
POST /api/v2/chat drips one NDJSON text event every 150 ms for about three
seconds, which is what lets a test watch a bubble grow inside a HIDDEN tab.
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = REPO_ROOT / "thomas" / "server" / "web"
CONTENT_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
}


def _messages(prefix: str, count: int) -> list[dict[str, str]]:
    rows = []
    for i in range(count):
        rows.append({"role": "user", "content": f"{prefix} question {i}"})
        rows.append({"role": "assistant", "content": f"{prefix} answer {i} " + "words " * 30})
    return rows


def chats_body(extra: list[dict[str, object]] | None = None) -> dict[str, object]:
    rows: list[dict[str, object]] = [
        {
            "id": cid,
            "session_id": cid,
            "title": title,
            "updatedAt": 1000 + n,
            "messages": _messages(title, 20),
            "model": "fixture",
        }
        for n, (cid, title) in enumerate([("chat-a", "Alpha"), ("chat-b", "Beta"), ("chat-c", "Gamma")])
    ]
    # A conversation born in this run shows up in Recent after its first turn,
    # the way the real store lists a fresh session.
    return {"chats": list(extra or []) + rows}


STUBS: dict[str, object] = {
    "/api/models": {
        "profiles": [
            {
                "name": "local",
                "provider": "local",
                "has_api_key": True,
                "models": [{"id": "fixture-1", "label": "Fixture model"}],
            }
        ],
        "preferences": {"active_profile": "local"},
        "default": "local",
    },
    "/api/marketplace/installed": {"plugins": []},
    "/api/preferences": {},
    "/api/health": {"status": "ok", "version": "fixture", "commit": "fixture"},
    "/api/evolve/agent/status": {"running": False},
    "/api/evolve/agent/conversations": {"conversations": []},
    "/api/local/projects": {"projects": []},
    "/api/chats/title": {},
    "/api/issues": {},
}


def _log_archive() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("thomas.log", "fixture log line\n")
    return buf.getvalue()


@dataclass
class ThomasFixture:
    url: str
    requests: list[tuple[str, str]] = field(default_factory=list)
    chat_calls: int = 0
    fresh_chats: list[dict[str, object]] = field(default_factory=list)
    # What GET /api/logs/export answers: the real server has no such route
    # ("missing" is aiohttp's 14-byte 404 body); "zip" is what a real one would send.
    log_export: str = "missing"


class QuietHTTPServer(ThreadingHTTPServer):
    """A loopback server whose handler threads never outlive the test.

    Every browser test ends by closing Chromium while a response is still being
    written, which raises in the handler thread. socketserver answers that by
    printing the traceback to stderr, and a daemon thread printing to stderr
    while the interpreter is finalizing aborts the whole process -- pytest
    reports every test passed and then exits 0xC0000409 (measured 2026-09-24 on
    the Search tests, whose last act is closing the browser mid-stream). So:
    nothing is printed from a handler, and the exit waits for the handlers.
    """

    daemon_threads = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.closing = False
        self._handler_threads: list[threading.Thread] = []
        self._handler_lock = threading.Lock()

    def process_request_thread(self, request, client_address) -> None:
        current = threading.current_thread()
        with self._handler_lock:
            self._handler_threads.append(current)
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._handler_lock:
                self._handler_threads.remove(current)

    def handle_error(self, request, client_address) -> None:
        # A client that went away mid-response is the normal end of a test, not
        # a fault to report -- and reporting it is what kills the process.
        return

    def close_quietly(self, serve_thread: threading.Thread | None = None, timeout: float = 5.0) -> None:
        """Stop serving, then wait for the threads rather than abandoning them."""
        self.closing = True
        self.shutdown()
        self.server_close()
        deadline = time.monotonic() + timeout
        for thread in ([serve_thread] if serve_thread else []) + self._snapshot_handlers():
            thread.join(max(0.0, deadline - time.monotonic()))

    def _snapshot_handlers(self) -> list[threading.Thread]:
        with self._handler_lock:
            return list(self._handler_threads)


def _handler(fixture: ThomasFixture):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:  # keep pytest output clean
            return

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: object) -> None:
            self._send(200, json.dumps(payload).encode("utf-8"), "application/json")

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            path = self.path.split("?", 1)[0]
            fixture.requests.append(("GET", self.path))
            if path == "/":
                html = (WEB_DIR / "chat.html").read_text(encoding="utf-8").replace("__THOMAS_WEB_BUILD__", "fixture")
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/settings":
                html = (WEB_DIR / "settings.html").read_text(encoding="utf-8")
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/api/logs/export":
                if fixture.log_export == "zip":
                    return self._send(200, _log_archive(), "application/zip")
                return self._send(404, b"404: Not Found", "text/plain; charset=utf-8")
            if path.startswith("/static/"):
                target = (WEB_DIR / path[len("/static/") :]).resolve()
                if WEB_DIR in target.parents and target.is_file():
                    return self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
                return self._send(404, b"", "text/plain")
            if path.startswith("/api/chats") and "mode=chat" in self.path:
                return self._json(chats_body(fixture.fresh_chats))
            if path.startswith("/api/v2/chat/session/"):
                return self._json({"delegations": []})
            if path in STUBS:
                return self._json(STUBS[path])
            return self._json({})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            fixture.requests.append(("POST", self.path))
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            if path == "/api/session/new":
                return self._json({"session_id": f"fresh-{len(fixture.requests)}"})
            if path == "/api/v2/chat":
                fixture.chat_calls += 1
                try:
                    asked = json.loads(body.decode("utf-8") or "{}")
                except (ValueError, UnicodeDecodeError):
                    asked = {}
                if not asked.get("session_id") or str(asked.get("session_id")).startswith("fresh-"):
                    cid = f"conv-{fixture.chat_calls}"
                    fixture.fresh_chats.insert(0, {
                        "id": cid, "session_id": cid, "title": str(asked.get("message", "New chat"))[:40],
                        "updatedAt": 5000 + fixture.chat_calls, "messages": [], "model": "fixture",
                    })
                return self._drip(body)
            return self._json({})

        def _drip(self, body: bytes) -> None:
            try:
                asked = json.loads(body.decode("utf-8") or "{}").get("message", "")
            except (ValueError, UnicodeDecodeError):
                asked = ""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            for i in range(20):
                # A drip in flight when the test ends must stop at the next
                # piece instead of holding a thread open for three more seconds.
                if getattr(self.server, "closing", False):
                    return
                line = json.dumps({"type": "text", "text": f"piece {i} of the reply to {asked[:12]}. "}) + "\n"
                chunk = line.encode("utf-8")
                self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n")
                self.wfile.flush()
                time.sleep(0.15)
            done = (json.dumps({"type": "done", "session_id": "fresh-done"}) + "\n").encode("utf-8")
            self.wfile.write(f"{len(done):x}\r\n".encode("ascii") + done + b"\r\n0\r\n\r\n")
            self.wfile.flush()

        def do_HEAD(self) -> None:  # noqa: N802
            # aiohttp answers HEAD for every GET route; the export probe relies on it.
            path = self.path.split("?", 1)[0]
            fixture.requests.append(("HEAD", self.path))
            if path == "/api/logs/export" and fixture.log_export != "zip":
                self.send_response(404)
            else:
                self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_PATCH(self) -> None:  # noqa: N802
            fixture.requests.append(("PATCH", self.path))
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            return self._json({})

        def do_DELETE(self) -> None:  # noqa: N802
            fixture.requests.append(("DELETE", self.path))
            return self._json({})

    return Handler


class serve:
    """Context manager: a fixture Thomas on a free loopback port."""

    def __enter__(self) -> ThomasFixture:
        self.fixture = ThomasFixture(url="")
        self.server = QuietHTTPServer(("127.0.0.1", 0), _handler(self.fixture))
        self.fixture.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.fixture

    def __exit__(self, *_exc) -> None:
        self.server.close_quietly(self.thread)


# ── Driving the shell in a real browser ─────────────────────────────────


def browser_ok() -> bool:
    """True when Playwright can launch Chromium here; the tests skip otherwise.

    NotImplementedError is the Windows case: playwright drives its node transport
    with asyncio subprocesses, which a SelectorEventLoop cannot spawn. A skip is
    not a proof: with THOMAS_REQUIRE_BROWSER_TESTS=1 (CI) an unusable browser is
    an error rather than a silent green.
    """
    required = os.environ.get("THOMAS_REQUIRE_BROWSER_TESTS", "").strip() == "1"
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        if required:
            raise RuntimeError("THOMAS_REQUIRE_BROWSER_TESTS=1 but playwright is not installed") from None
        return False
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except (PlaywrightError, NotImplementedError, OSError) as exc:
        if required:
            raise RuntimeError(f"THOMAS_REQUIRE_BROWSER_TESTS=1 but Chromium cannot launch: {exc}") from None
        return False
    return True


@dataclass
class Shell:
    page: object
    fixture: ThomasFixture
    errors: list[str] = field(default_factory=list)

    def docs(self) -> list[object]:
        """The tab documents, in strip order (the static workspace frame is not one)."""
        return [f for f in self.page.frames if "embed=1&browser=0" in f.url]


@contextmanager
def open_shell(landing: str = "/") -> Iterator[Shell]:
    """Serve the fixture Thomas, open the chat page in headless Chromium, yield both."""
    from playwright.sync_api import sync_playwright

    with serve() as fixture, sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        shell = Shell(page=page, fixture=fixture)
        page.on("pageerror", lambda e: shell.errors.append(f"pageerror: {e}"))
        def note_console(message) -> None:
            if message.type != "error":
                return
            # The settings page probes /api/logs/export at load and the fixture
            # answers 404 on purpose; Chromium logs every 404 resource as an error.
            url = str((message.location or {}).get("url", ""))
            if url.endswith("/api/logs/export"):
                return
            shell.errors.append(f"console.error: {message.text}")

        page.on("console", note_console)

        def only_our_origin(route) -> None:
            if route.request.url.startswith(fixture.url):
                route.continue_()
            else:
                route.abort()

        page.route("**/*", only_our_origin)
        # The owner's profile restores the last open conversation at boot, so home is
        # never blank on arrival; a fresh profile is, and a blank home ADOPTS the first
        # row it is given (Chrome's new-tab rule). Seed the same state before any page
        # script runs; tab documents (child frames) are left to the shell's own seed.
        page.add_init_script(
            "if (window.parent === window && !localStorage.getItem('thomas_last_chat'))"
            " localStorage.setItem('thomas_last_chat', 'chat-a');"
        )
        page.goto(fixture.url + landing, wait_until="load")
        page.wait_for_selector("#bt-titlebar", timeout=20000)
        page.wait_for_timeout(800)
        try:
            yield shell
        finally:
            browser.close()
