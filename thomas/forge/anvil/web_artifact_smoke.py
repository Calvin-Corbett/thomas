"""Bounded real-browser smoke checks for local Forge Code web artifacts.

The verifier executes generated HTML in an isolated headless Chrome/Edge
profile, serves only ordinary web assets from the selected project, and blocks
external network resolution.  It proves browser boot, basic interaction, and
the absence of uncaught/runtime console errors.  It intentionally does not call
that evidence a full end-to-end test.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import shutil
import subprocess  # nosec B404 - fixed browser executable and arguments
import tempfile
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .web_artifact_smoke_assets import (
    _MAX_ASSET_BYTES,
    _RECEIPT_RE,
    _SMOKE_CSP,
    _SMOKE_HARNESS,
    _SMOKE_HOST,
    _SMOKE_ORIGIN,
    _WEB_ASSET_SUFFIXES,
)


@dataclass(frozen=True)
class BrowserSmokeResult:
    """Outcome of a bounded browser smoke attempt."""

    ok: bool
    attempted: bool
    summary: str
    receipts: tuple[dict[str, Any], ...] = ()


def _browser_executable() -> str | None:
    candidates = [
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def _instrument_html(source: str) -> str:
    """Inject the observer before application scripts without changing the source artifact."""

    head = re.search(r"<head\b[^>]*>", source, re.IGNORECASE)
    if head:
        return source[: head.end()] + _SMOKE_HARNESS + source[head.end() :]
    html = re.search(r"<html\b[^>]*>", source, re.IGNORECASE)
    if html:
        return source[: html.end()] + "<head>" + _SMOKE_HARNESS + "</head>" + source[html.end() :]
    return _SMOKE_HARNESS + source


def _receipt_from_dom(dom: str) -> dict[str, Any] | None:
    match = _RECEIPT_RE.search(str(dom or ""))
    if not match:
        return None
    encoded = match.group(1) or match.group(2) or ""
    try:
        raw = base64.b64decode(encoded, validate=True).decode("utf-8")
        payload = json.loads(raw)
    except (ValueError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _safe_web_path(root: Path, raw_path: str) -> Path | None:
    relative = unquote(urlsplit(raw_path).path).lstrip("/").replace("\\", "/")
    parts = [part for part in relative.split("/") if part]
    if not parts or any(part in {".", ".."} or part.startswith(".") for part in parts):
        return None
    target = (root / Path(*parts)).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    if target.suffix.lower() not in _WEB_ASSET_SUFFIXES:
        return None
    try:
        if target.stat().st_size > _MAX_ASSET_BYTES:
            return None
    except OSError:
        return None
    return target


def _allowed_proxy_path(raw_target: str, host_header: str = "") -> str | None:
    """Return a path only when it targets the isolated synthetic smoke origin.

    Proxy navigations normally use an absolute request target, while Chromium
    can fetch same-origin subresources with an origin-form target such as
    ``/styles.css``.  Origin-form requests are accepted only when their Host
    header names the synthetic origin, preserving the network boundary.
    """

    if raw_target.startswith("/") and not raw_target.startswith("//"):
        host = str(host_header or "").strip().lower().rstrip(".")
        if host not in {_SMOKE_HOST, f"{_SMOKE_HOST}:80"}:
            return None
        return unquote(urlsplit(raw_target).path or "/")

    parsed = urlsplit(raw_target)
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "http"
        or str(parsed.hostname or "").lower() != _SMOKE_HOST
        or port not in (None, 80)
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return unquote(parsed.path or "/")


# Requests the BROWSER makes on its own, which the page never asked for. Counting
# these as missing assets would fail every deliverable that ships no icon, which
# is the same mistake as passing a broken page, pointed the other way. Confirmed
# by logging the real request stream during a smoke run: for a one-page artifact
# Chromium asked for the page, the page's own fetch, and this.
_BROWSER_INITIATED_PATHS = {"favicon.ico", "apple-touch-icon.png", "apple-touch-icon-precomposed.png"}


def _handler_for(
    root: Path,
    page_path: str,
    instrumented: bytes,
    missing: list[str] | None = None,
) -> type[BaseHTTPRequestHandler]:
    class ArtifactHandler(BaseHTTPRequestHandler):
        def _note_missing(self, request_path: str) -> None:
            """Record a file the PAGE asked for that is not in the folder.

            A `fetch` that 404s is an ordinary response, not an `error` event,
            so nothing in the receipt sees it: `resource_errors` only catches
            `<script src>`/`<img>`-style failures, and a page that handles its
            own failure tidily raises nothing at all. The server, on the other
            hand, simply knows. This is a fact about the deliverable rather than
            an inference about it.
            """

            if missing is None or request_path in _BROWSER_INITIATED_PATHS:
                return
            if request_path not in missing:
                missing.append(request_path)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            allowed_path = _allowed_proxy_path(self.path, self.headers.get("Host", ""))
            if allowed_path is None:
                self.send_error(403, "Browser smoke network access is denied")
                return
            request_path = allowed_path.lstrip("/").replace("\\", "/")
            if request_path == page_path:
                body = instrumented
                content_type = "text/html; charset=utf-8"
            else:
                target = _safe_web_path(root, allowed_path)
                if target is None:
                    self._note_missing(request_path)
                    self.send_error(404)
                    return
                try:
                    body = target.read_bytes()
                except OSError:
                    self._note_missing(request_path)
                    self.send_error(404)
                    return
                content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", _SMOKE_CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_CONNECT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            self.send_error(403, "Browser smoke network access is denied")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return ArtifactHandler


def _run_one(
    browser: str,
    root: Path,
    name: str,
    *,
    timeout: int,
    runner: Any = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    path = (root / name).resolve()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return False, f"{name}: could not read HTML for browser smoke ({exc})", None

    page_path = str(path.relative_to(root)).replace("\\", "/")
    missing: list[str] = []
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler_for(root, page_path, _instrument_html(source).encode(), missing)
    )
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="thomas-web-smoke", daemon=True)
    thread.start()
    run = runner or subprocess.run
    try:
        with tempfile.TemporaryDirectory(prefix="thomas-web-smoke-") as profile:
            url = f"{_SMOKE_ORIGIN}/{page_path}"
            command = [
                browser,
                "--headless=new",
                "--disable-background-networking",
                "--disable-breakpad",
                "--disable-extensions",
                "--disable-gpu",
                "--disable-quic",
                "--disable-sync",
                "--metrics-recording-only",
                "--no-default-browser-check",
                "--no-first-run",
                "--safebrowsing-disable-auto-update",
                "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1",
                f"--proxy-server=http://127.0.0.1:{server.server_port}",
                "--proxy-bypass-list=<-loopback>",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=1400",
                "--window-size=1280,900",
                "--dump-dom",
                url,
            ]
            completed = run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(5, int(timeout)),
                check=False,
            )
    except subprocess.TimeoutExpired:
        return False, f"{name}: browser smoke timed out", None
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return False, f"{name}: browser smoke could not run ({exc})", None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    if int(getattr(completed, "returncode", 1) or 0) != 0:
        error = str(getattr(completed, "stderr", "") or "").strip().splitlines()
        detail = error[-1][:300] if error else f"browser exited {completed.returncode}"
        return False, f"{name}: {detail}", None
    receipt = _receipt_from_dom(str(getattr(completed, "stdout", "") or ""))
    if receipt is None:
        return False, f"{name}: browser did not publish a smoke receipt", None
    # A resource this harness REFUSED to fetch is not a defect of the page. The
    # browser runs with external name resolution mapped away on purpose, so a
    # page that loads three.js from a CDN could never pass -- and blocktown-84
    # does exactly that. Failing it would say "your game is broken" about a game
    # that works, which is the same error as passing a broken one, pointed the
    # other way. Local resource failures still fail: those are ours, and a
    # missing local script is precisely the breakage this exists to catch.
    blocked, local_failures = [], []
    for value in receipt.get("resource_errors") or []:
        (blocked if _is_external_reference(str(value)) else local_failures).append(str(value))
    problems = [
        *[str(value) for value in receipt.get("errors") or []],
        *[str(value) for value in receipt.get("console_errors") or []],
        *local_failures,
    ]
    # Files the page asked this server for that are not in the folder. Observed
    # on a real run: Thomas was asked for a chart reading `sales.csv`, wrote the
    # page and not the CSV, and the page reported "Could not load sales.csv"
    # over an empty canvas -- while this check returned "browser boot clean".
    # Every DOM-side signal had an honest reason to stay quiet: a 404 from
    # `fetch` is a normal response rather than an `error` event, the page caught
    # its own failure so nothing was uncaught, and `paintState` calls a canvas
    # `unverifiable` until someone asks it for a context, which this page never
    # got far enough to do. Asking the server closes all three at once, and it
    # is a fact rather than a heuristic: the file was requested, and it is not
    # there.
    if missing:
        listed = ", ".join(sorted(missing)[:5])
        problems.append(f"the page asked for {listed}, which is not in the project folder")
    # A <canvas> in the DOM is not a drawing. A game that renders nothing has
    # the same markup as a game that renders perfectly, so accepting the element
    # as proof of rendering passed exactly the builds this check exists to
    # catch. Only a canvas whose pixels were READ and found to differ from an
    # untouched one of the same size counts.
    canvas = receipt.get("canvas") or {}
    paint = str(canvas.get("paint") or "") if canvas else ""
    if not receipt.get("dom_ready"):
        problems.append("DOMContentLoaded did not complete")
    if paint == "blank":
        # Named separately from "no canvas", and reported even when the page has
        # text: for a canvas app the canvas IS the page, so surrounding chrome
        # proves nothing about it, and "no text or canvas" would send whoever
        # reads this looking for a missing element that is right there.
        # Plain first, precise second. The owner reads these lines too, and
        # "the canvas was never drawn to" means nothing to someone who does not
        # write web code -- while the repair loop still needs to know it is the
        # canvas specifically.
        problems.append("the page shows a blank picture area: nothing was ever drawn to the canvas")
    elif not (int(receipt.get("body_text_chars") or 0) > 0 or bool(canvas)):
        problems.append("page rendered no text or canvas")
    if problems:
        return False, f"{name}: " + "; ".join(problems[:5]), receipt
    interactions = ", ".join(str(value) for value in receipt.get("interactions") or []) or "boot only"
    # Surfaced, not silently dropped: the page booted clean against everything
    # this harness could actually serve, and the reader should know what it
    # could not reach rather than infer full coverage from a clean line.
    offline = f"; {len(blocked)} external resource(s) not fetched offline" if blocked else ""
    # Prefixed, because joined with the interactions a note reads as another
    # thing that happened: "clicked:Start Over; clicked a start-like control and
    # saw no change" gives a reader no way to tell the observation from the
    # action. A note is a caveat about the check, not a result of it.
    notes = "; ".join(f"note: {value}" for value in receipt.get("notes") or [])
    return True, f"{name}: browser boot clean; {interactions}{offline}{'; ' + notes if notes else ''}", receipt


def _is_external_reference(value: str) -> bool:
    """Does this resource-error line name a host the harness deliberately blocks?"""
    match = re.search(r"https?://([^/\s]+)", value)
    if not match:
        return False
    host = match.group(1).split(":")[0].lower()
    return host not in {"127.0.0.1", "localhost", "[::1]", _SMOKE_HOST.lower()}


def smoke_html_artifacts(
    cwd: str | Path,
    files: list[str],
    *,
    timeout: int = 20,
    runner: Any = None,
) -> BrowserSmokeResult:
    """Smoke changed HTML in a real local browser, or report why it was unavailable."""

    root = Path(cwd).resolve()
    html_files = [name for name in files if Path(name).suffix.lower() in {".html", ".htm"} and (root / name).is_file()]
    if not html_files:
        return BrowserSmokeResult(ok=True, attempted=False, summary="no HTML artifacts require browser smoke")
    browser = _browser_executable()
    if browser is None:
        return BrowserSmokeResult(
            ok=True,
            attempted=False,
            summary="browser smoke unavailable; static checks only (Chrome or Edge not found)",
        )
    receipts: list[dict[str, Any]] = []
    summaries: list[str] = []
    for name in html_files:
        ok, summary, receipt = _run_one(browser, root, name, timeout=timeout, runner=runner)
        summaries.append(summary)
        if receipt is not None:
            receipts.append(receipt)
        if not ok:
            return BrowserSmokeResult(False, True, "; ".join(summaries), tuple(receipts))
    return BrowserSmokeResult(True, True, "; ".join(summaries), tuple(receipts))
