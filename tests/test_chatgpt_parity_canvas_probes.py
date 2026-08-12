from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
STRESS = ROOT / "tests" / "stress"
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))

from chatgpt_parity_probes import ProbeContext, evaluate_check

ARTIFACTS = (
    ("document", "parity_document.md"),
    ("sheet", "parity_sheet.csv"),
    ("slides", "parity_slides.html"),
    ("site", "index.html"),
)


def _runtime_receipt() -> dict[str, object]:
    return {
        "requested": {"profile": "local", "provider": "fixture", "model": "model"},
        "active": {"profile": "local", "provider": "fixture", "model": "model"},
        "failover_enabled": False,
        "failover_used": False,
        "attempts": [{"profile": "local", "provider": "fixture", "model": "model", "status": "success"}],
    }


def _delegation(prefix: str, slug: str, name: str, *, receipt_ok: bool = True) -> dict[str, object]:
    return {
        "execution_id": f"exec-{prefix}-{slug}",
        "state": "completed",
        "last_progress": f"Completed and verified {name}.",
        "proof_status": "verified",
        "proof": {"status": "verified", "artifacts": [{"name": name, "path": name}]},
        "receipt": {"ok": receipt_ok},
        "runtime_profile": {"model_runtime": _runtime_receipt()},
    }


class _CanvasHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    revision_requested = False
    combined = False
    duplicate_owner = False
    missing_owner = False
    bad_receipt = False
    mutate_original = False
    last_message = ""

    def log_message(self, format: str, *args: object) -> None:
        _ = (format, args)

    def _respond(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.endswith("/delegations"):
            prefix = "revised" if type(self).revision_requested else "canvas"
            rows = [
                _delegation(prefix, slug, name, receipt_ok=not (type(self).bad_receipt and name == "index.html"))
                for slug, name in ARTIFACTS
            ]
            if type(self).combined:
                rows = [
                    {
                        "execution_id": "exec-combined",
                        "state": "completed",
                        "last_progress": "Completed all artifacts in one workspace.",
                        "proof_status": "verified",
                        "proof": {
                            "status": "verified",
                            "artifacts": [{"name": name, "path": name} for _, name in ARTIFACTS],
                        },
                        "receipt": {"ok": True},
                        "runtime_profile": {"model_runtime": _runtime_receipt()},
                    }
                ]
            if type(self).missing_owner:
                rows = [row for row in rows if row["execution_id"] != f"exec-{prefix}-sheet"]
            if type(self).duplicate_owner:
                rows.append(_delegation(prefix, "duplicate-site", "index.html"))
            self._respond(
                json.dumps({"session_id": "test-session", "delegations": rows}).encode(),
                "application/json",
            )
            return

        content = self._artifact_content()
        if content is None:
            self.send_response(404)
            self.end_headers()
            return
        body, content_type = content
        self._respond(body, content_type)

    def _artifact_content(self) -> tuple[bytes, str] | None:
        path = self.path
        revised = "/exec-revised-" in path
        if path.endswith("/parity_document.md"):
            marker = (
                b"# Thomas Artifact Matrix Revised\n\nDOCUMENT-MARKER-170-REV2\n"
                if revised
                else b"# Thomas Artifact Matrix\n\nDOCUMENT-MARKER-170\n"
            )
            body, content_type = marker, "text/markdown"
        elif path.endswith("/parity_sheet.csv"):
            body = (
                b"Item,Value\nAlpha,17\nBeta,23\nGamma,31\nRevision,2\n"
                if revised
                else b"Item,Value\nAlpha,17\nBeta,23\n"
            )
            content_type = "text/csv"
        elif path.endswith("/parity_slides.html"):
            body = (
                b"<title>Thomas Parity Deck Revised</title><p>SLIDES-MARKER-170-REV2</p>"
                b'<section class="slide active">Revised Slide 1</section>'
                b'<section class="slide">Revised Slide 2</section>'
                b'<section class="slide">Revised Slide 3</section><button>Previous</button><button>Next</button>'
                if revised
                else b"<title>Thomas Parity Deck</title><p>SLIDES-MARKER-170</p>"
                b'<section class="slide active">Slide 1</section><section class="slide">Slide 2</section>'
                b'<section class="slide">Slide 3</section><button>Previous</button><button>Next</button>'
            )
            content_type = "text/html"
        elif path.endswith("/index.html"):
            body = (
                b"<title>Thomas Interactive Site Revised</title><p>SITE-MARKER-170-REV2</p>"
                b'<button id="action-button">Go</button><p id="status-text">Ready</p>'
                b"<script>document.getElementById('action-button').onclick=()=>"
                b"document.getElementById('status-text').textContent='Revised';</script>"
                if revised
                else b"<title>Thomas Interactive Site</title><p>SITE-MARKER-170</p>"
                b'<button id="action-button">Go</button><p id="status-text">Ready</p>'
            )
            content_type = "text/html"
        else:
            return None
        if type(self).mutate_original and type(self).revision_requested and not revised:
            body += b"\nMUTATED-AFTER-REVISION"
        return body, content_type

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/session/new":
            self._respond(json.dumps({"session_id": "test-session"}).encode(), "application/json")
            return
        if self.path != "/api/v2/chat":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        message = str(json.loads(self.rfile.read(length))["message"])
        type(self).last_message = message
        if "Create revised versions" in message:
            type(self).revision_requested = True
        event = {"type": "delegation_started", "last_progress": "Provider-native workers are running."}
        self._respond((json.dumps(event) + "\n").encode(), "application/x-ndjson")


@contextmanager
def _canvas_server() -> Iterator[ProbeContext]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CanvasHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield ProbeContext(
            ROOT,
            f"http://127.0.0.1:{server.server_port}",
            "local",
            "model",
            False,
            timeout_seconds=1,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _CanvasHandler.revision_requested = False
        _CanvasHandler.combined = False
        _CanvasHandler.duplicate_owner = False
        _CanvasHandler.missing_owner = False
        _CanvasHandler.bad_receipt = False
        _CanvasHandler.mutate_original = False
        _CanvasHandler.last_message = ""


def _tier3(context: ProbeContext):
    return evaluate_check(
        "canvas-sites-artifacts",
        3,
        0,
        {"kind": "live_probe", "probe": "canvas_artifact_matrix", "severity": "critical"},
        context,
    )


def _tier4(context: ProbeContext):
    return evaluate_check(
        "canvas-sites-artifacts",
        4,
        0,
        {"kind": "live_probe", "probe": "canvas_revision_integrity", "severity": "critical"},
        context,
    )


def test_canvas_matrix_requires_four_separate_verified_workspaces(monkeypatch) -> None:
    async def _interactions(_context, execution_ids):
        assert execution_ids["index.html"] == "exec-canvas-site"
        assert execution_ids["parity_slides.html"] == "exec-canvas-slides"
        return True, {"site_after": ["Working"], "slide_after": ["Slide 2"]}

    monkeypatch.setattr("chatgpt_parity_probes._matrix_browser_interactions", _interactions)
    with _canvas_server() as context:
        row = _tier3(context)
    assert row.passed is True
    payload = json.loads(row.actual)
    assert payload["separate_workspaces"] is True
    assert payload["terminal_verified"] is True
    assert len(set(payload["execution_ids"].values())) == 4


def test_canvas_matrix_rejects_combined_missing_duplicate_and_bad_receipt(monkeypatch) -> None:
    async def _unexpected_interactions(_context, _execution_ids):
        raise AssertionError("invalid ownership must fail before browser interaction")

    monkeypatch.setattr("chatgpt_parity_probes._matrix_browser_interactions", _unexpected_interactions)
    for failure in ("combined", "missing_owner", "duplicate_owner", "bad_receipt"):
        setattr(_CanvasHandler, failure, True)
        with _canvas_server() as context:
            row = _tier3(context)
        assert row.passed is False, failure


def test_canvas_revision_uses_separate_workspaces_and_preserves_originals(monkeypatch) -> None:
    async def _matrix_interactions(_context, execution_ids):
        assert len(set(execution_ids.values())) == 4
        return True, {"site_after": ["Working"], "slide_after": ["Slide 2"]}

    async def _revision_interactions(_context, original_execution_ids, revised_execution_ids):
        assert original_execution_ids["index.html"] == "exec-canvas-site"
        assert revised_execution_ids["index.html"] == "exec-revised-site"
        assert revised_execution_ids["parity_slides.html"] == "exec-revised-slides"
        return True, {"revised_after": ["Revised"], "slide_after": ["Revised Slide 2"]}

    monkeypatch.setattr("chatgpt_parity_probes._matrix_browser_interactions", _matrix_interactions)
    monkeypatch.setattr(
        "chatgpt_parity_artifact_probes.revision_browser_interactions",
        _revision_interactions,
    )
    with _canvas_server() as context:
        tier3 = _tier3(context)
        tier4 = _tier4(context)
        revision_prompt = _CanvasHandler.last_message
    assert tier3.passed is True
    assert tier4.passed is True
    payload = json.loads(tier4.actual)
    assert payload["steer"]["accepted"] is True
    assert payload["original_hashes_unchanged"] is True
    assert payload["revised_hashes_distinct"] is True
    assert len(set(payload["revised_execution_ids"].values())) == 4
    source_line = next(line for line in revision_prompt.splitlines() if "source receipts" in line)
    assert '"site": "exec-canvas-site"' in source_line
    assert "index.html" not in source_line


def test_canvas_revision_rejects_original_mutation(monkeypatch) -> None:
    async def _matrix_interactions(_context, _execution_ids):
        return True, {}

    async def _revision_interactions(_context, _original_execution_ids, _revised_execution_ids):
        return True, {}

    monkeypatch.setattr("chatgpt_parity_probes._matrix_browser_interactions", _matrix_interactions)
    monkeypatch.setattr(
        "chatgpt_parity_artifact_probes.revision_browser_interactions",
        _revision_interactions,
    )
    _CanvasHandler.mutate_original = True
    with _canvas_server() as context:
        assert _tier3(context).passed is True
        tier4 = _tier4(context)
    assert tier4.passed is False
    assert json.loads(tier4.actual)["original_hashes_unchanged"] is False
