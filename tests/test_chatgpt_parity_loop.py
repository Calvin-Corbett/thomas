from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
STRESS = ROOT / "tests" / "stress"
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))

import chatgpt_parity_memory_probes as memory_probes
import chatgpt_parity_probes as parity_probes
from chatgpt_parity_harness import EvidenceRow, score_families, validate_rubric
from chatgpt_parity_image_probes import _scene_contract, _svg_summary
from chatgpt_parity_probes import ProbeContext, evaluate_check


def _runtime_profile() -> dict[str, object]:
    receipt = {
        "requested": {"profile": "local", "provider": "fixture", "model": "model"},
        "active": {"profile": "local", "provider": "fixture", "model": "model"},
        "failover_enabled": False,
        "failover_used": False,
        "attempts": [{"profile": "local", "provider": "fixture", "model": "model", "status": "success"}],
    }
    return {"model_runtime": receipt}


def _load_loop() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chatgpt_parity_loop", STRESS / "chatgpt_parity_loop.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rubric() -> dict:
    return {
        "schema_version": "thomas-chatgpt-parity-v1",
        "target": "test",
        "as_of": "2026-07-12",
        "source_urls": ["https://example.test"],
        "scoring": {str(tier): f"tier {tier}" for tier in range(5)},
        "families": [
            {
                "id": "core",
                "name": "Core",
                "weight": 1.0,
                "critical": True,
                "behaviors": ["behaves"],
                "tiers": {str(tier): [{"kind": "manual", "severity": "critical"}] for tier in range(1, 5)},
            }
        ],
    }


def test_rubric_validation_rejects_weight_drift_and_missing_tiers() -> None:
    rubric = _rubric()
    validate_rubric(rubric)
    rubric["families"][0]["weight"] = 0.9
    with pytest.raises(ValueError, match="sum to 1.0"):
        validate_rubric(rubric)
    rubric = _rubric()
    del rubric["families"][0]["tiers"]["4"]
    with pytest.raises(ValueError, match="tier 4"):
        validate_rubric(rubric)


def test_scoring_is_sequential_and_missing_evidence_fails_closed() -> None:
    rubric = _rubric()
    rows = [
        EvidenceRow("core", 1, "one", "pass", "pass", True, "critical"),
        EvidenceRow("core", 2, "two", "pass", "fail", False, "critical"),
        EvidenceRow("core", 3, "three", "pass", "pass", True, "critical"),
        EvidenceRow("core", 4, "four", "pass", "pass", True, "critical"),
    ]
    scorecard = score_families(rubric, rows)
    assert scorecard["family_scores"] == {"core": 1}
    assert scorecard["parity_achieved"] is False
    assert scorecard["parity_index"] == 25.0


def test_path_contains_requires_every_declared_contract(tmp_path: Path) -> None:
    target = tmp_path / "runtime.py"
    target.write_text("alpha beta", encoding="utf-8")
    context = ProbeContext(tmp_path, "http://127.0.0.1:1", "local", "model", False)
    check = {"kind": "path_contains", "path": "runtime.py", "needles": ["alpha", "gamma"], "severity": "high"}
    row = evaluate_check("family", 1, 0, check, context)
    assert row.passed is False
    assert "gamma" in row.actual


class _ChatHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    memory_pin: str | None = None
    memory_contradictions: list[dict[str, object]] = []
    data_clean_requested = False
    data_adversarial_requested = False
    document_grounded_requested = False
    document_conflict_requested = False

    def log_message(self, format: str, *args: object) -> None:
        _ = (format, args)

    def do_GET(self) -> None:  # noqa: N802
        csp = ""
        if self.path == "/api/memory":
            pins = (
                [{"key": "user.preference", "text": type(self).memory_pin, "created_ts_utc": 1}]
                if type(self).memory_pin
                else []
            )
            body = json.dumps({"enabled": True, "stats": {}, "v2_health": {}, "pins": pins}).encode()
            content_type = "application/json"
        elif self.path.startswith("/api/memory/contradictions"):
            rows = list(type(self).memory_contradictions)
            body = json.dumps({"ok": True, "only_open": False, "count": len(rows), "contradictions": rows}).encode()
            content_type = "application/json"
        elif self.path == "/api/v2/chat/session/test-session/delegations":
            documents = []
            if type(self).document_conflict_requested:
                documents = [
                    {
                        "execution_id": "exec-doc-conflict",
                        "state": "completed",
                        "last_progress": "Verified conflict_report.md.",
                        "proof_status": "verified",
                        "proof": {
                            "status": "verified",
                            "artifacts": [{"name": "conflict_report.md", "path": "conflict_report.md"}],
                        },
                        "receipt": {"ok": True},
                        "runtime_profile": _runtime_profile(),
                    }
                ]
            elif type(self).document_grounded_requested:
                documents = [
                    {
                        "execution_id": "exec-doc-grounded",
                        "state": "completed",
                        "last_progress": "Verified grounded_report.md.",
                        "proof_status": "verified",
                        "proof": {
                            "status": "verified",
                            "artifacts": [{"name": "grounded_report.md", "path": "grounded_report.md"}],
                        },
                        "receipt": {"ok": True},
                        "runtime_profile": _runtime_profile(),
                    }
                ]
            data_clean = (
                [
                    {
                        "execution_id": "exec-data-clean",
                        "state": "completed",
                        "last_progress": "Verified cleaned data artifact.",
                        "proof_status": "verified",
                        "proof": {
                            "status": "verified",
                            "artifacts": [{"name": "cleaned_data.csv", "path": "cleaned_data.csv"}],
                        },
                        "receipt": {"ok": True},
                        "runtime_profile": _runtime_profile(),
                    }
                ]
                if type(self).data_clean_requested
                else []
            )
            data_adversarial = (
                [
                    {
                        "execution_id": "exec-data-adversarial",
                        "state": "completed",
                        "last_progress": "Verified hostile data cleaning and chart artifacts.",
                        "proof_status": "verified",
                        "proof": {
                            "status": "verified",
                            "artifacts": [
                                {"name": "index.html", "path": "index.html"},
                                {"name": "audit_manifest.json", "path": "audit_manifest.json"},
                                {"name": "cleaned_snapshot.csv", "path": "cleaned_snapshot.csv"},
                            ],
                        },
                        "receipt": {"ok": True},
                        "runtime_profile": _runtime_profile(),
                    }
                ]
                if type(self).data_adversarial_requested
                else []
            )
            agentic = [
                {
                    "execution_id": "exec-agentic",
                    "state": "completed",
                    "last_progress": "Completed explicit browser-to-artifact recipe.",
                    "proof_status": "verified",
                    "proof": {
                        "status": "verified",
                        "artifacts": [
                            {"name": "agentic_report.md", "path": "agentic_report.md"},
                            {"name": "parity_document.md", "path": "parity_document.md"},
                            {"name": "parity_sheet.csv", "path": "parity_sheet.csv"},
                            {"name": "parity_slides.html", "path": "parity_slides.html"},
                            {"name": "index.html", "path": "index.html"},
                        ],
                    },
                    "receipt": {"ok": True},
                    "runtime_profile": _runtime_profile(),
                }
            ]
            standard_delegations = documents + data_adversarial + data_clean + agentic
            payload = {
                "session_id": "test-session",
                "delegations": standard_delegations,
            }
            body = json.dumps(payload).encode()
            content_type = "application/json"
        elif self.path == "/deliverable/exec-agentic/agentic_report.md":
            body = (
                b"Source URL: https://example.com\nExtracted Heading: Example Domain\n"
                b'This page is a documentation example headed "Example Domain".\n'
            )
            content_type = "text/markdown"
        elif self.path == "/deliverable/exec-agentic/parity_document.md":
            body = b"# Thomas Artifact Matrix\n\nDOCUMENT-MARKER-170\n"
            content_type = "text/markdown"
        elif self.path == "/deliverable/exec-agentic/parity_sheet.csv":
            body = b"Item,Value\nAlpha,17\nBeta,23\n"
            content_type = "text/csv"
        elif self.path == "/deliverable/exec-agentic/parity_slides.html":
            body = (
                b"<title>Thomas Parity Deck</title><p>SLIDES-MARKER-170</p>"
                b'<section class="slide active">Slide 1</section><section class="slide">Slide 2</section>'
                b'<section class="slide">Slide 3</section><button>Previous</button><button>Next</button>'
            )
            content_type = "text/html"
        elif self.path == "/deliverable/exec-agentic/index.html":
            body = (
                b"<title>Thomas Interactive Site</title><p>SITE-MARKER-170</p>"
                b'<button id="action-button">Go</button><p id="status-text">Ready</p>'
                b"<h1>DATA-CHART-MARKER-56</h1><p>Alpha 3 Beta 7 Gamma 5</p>"
                b"<p>TOTAL 15</p><p>PEAK BETA 7</p>"
            )
            content_type = "text/html"
        elif self.path == "/deliverable/exec-data-clean/cleaned_data.csv":
            body = (
                b'Category,Value\nAlpha,1200\nBeta,300\nDelta,-50\n"\'=HYPERLINK(""https://evil.test"",""click"")",10\n'
            )
            content_type = "text/csv"
        elif self.path == "/deliverable/exec-data-adversarial/index.html":
            body = (
                b"<h1>DATA-ADVERSARIAL-1460</h1><p id='total-value'>1460</p>"
                b"<p id='peak-value'>Alpha 1200</p>"
                b"<p id='formula-cell'>'=HYPERLINK(&quot;https://evil.test&quot;,&quot;click&quot;)</p>"
                b"<button id='audit-toggle'>Audit</button><p id='audit-state'>Closed</p>"
                b"<p id='audit-details'>Excluded 2 | Merged 1 | Sanitized 1</p>"
                b"<script>document.getElementById('audit-toggle').onclick=()=>"
                b"document.getElementById('audit-state').textContent='Open';</script>"
            )
            content_type = "text/html"
            csp = "sandbox allow-scripts allow-forms"
        elif self.path == "/deliverable/exec-data-adversarial/audit_manifest.json":
            body = b'{"total":1460,"peak":"Alpha","excluded_rows":2,"merged_rows":1,"sanitized_rows":1}'
            content_type = "application/json"
        elif self.path == "/deliverable/exec-data-adversarial/cleaned_snapshot.csv":
            body = b"Category,Value\nAlpha,1200\nBeta,300\nDelta,-50\nSafeFormula,10\n"
            content_type = "text/csv"
        elif self.path == "/deliverable/exec-doc-grounded/grounded_report.md":
            body = (
                b"# FILE-GROUNDED-31\n\nSource: quarterly_brief.txt\n"
                b"Project REDWOOD-31 shipped 31 units. Deadline: October 12.\n"
            )
            content_type = "text/markdown"
        elif self.path == "/deliverable/exec-doc-conflict/conflict_report.md":
            body = (
                b"# Grounded conflict report\n\nprimary_ledger.txt verifies CEDAR-88 and 88 units.\n"
                b"secondary_notes.txt claims RIVER-999; that conflicting claim is rejected as unverified.\n"
                b"oversized_appendix.txt visible head: APPENDIX-HEAD-7.\n"
            )
            content_type = "text/markdown"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if csp:
            self.send_header("Content-Security-Policy", csp)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/session/new":
            body = json.dumps({"session_id": "test-session"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length))
        if self.path == "/api/memory/pins":
            previous = type(self).memory_pin
            type(self).memory_pin = str(payload["text"])
            if previous and previous != type(self).memory_pin:
                type(self).memory_contradictions.append(
                    {
                        "id": len(type(self).memory_contradictions) + 1,
                        "key": str(payload["key"]),
                        "existing": previous,
                        "incoming": type(self).memory_pin,
                        "resolved": False,
                    }
                )
            body = json.dumps({"ok": True, "key": payload["key"]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/api/memory/contradictions/") and self.path.endswith("/resolve"):
            cid = int(self.path.split("/")[-2])
            for row in type(self).memory_contradictions:
                if int(row.get("id") or 0) == cid:
                    row["resolved"] = bool(payload.get("resolved", True))
            body = json.dumps({"ok": True, "id": cid, "resolved": bool(payload.get("resolved", True))}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        message = payload["message"]
        if "I prefer PARITY-MEMORY-" in message and payload.get("memory") is not False:
            type(self).memory_pin = message.split("I prefer ", 1)[1].split(".", 1)[0]
        if "grounded_report.md" in message:
            type(self).document_grounded_requested = True
            events = [{"type": "delegation_started", "last_progress": "Grounding uploaded document."}]
            body = "".join(json.dumps(event) + "\n" for event in events).encode()
        elif "conflict_report.md" in message:
            type(self).document_conflict_requested = True
            events = [{"type": "delegation_started", "last_progress": "Reconciling uploaded sources."}]
            body = "".join(json.dumps(event) + "\n" for event in events).encode()
        elif "attached hostile input" in message:
            type(self).data_clean_requested = True
            events = [{"type": "delegation_started", "last_progress": "Cleaning hostile data."}]
            body = "".join(json.dumps(event) + "\n" for event in events).encode()
        elif "DATA-ADVERSARIAL-1460" in message:
            type(self).data_adversarial_requested = True
            events = [{"type": "delegation_started", "last_progress": "Rendering audited data."}]
            body = "".join(json.dumps(event) + "\n" for event in events).encode()
        elif "CSV input" in message:
            events = [{"type": "delegation_started", "last_progress": "Provider-native worker is running."}]
            body = "".join(json.dumps(event) + "\n" for event in events).encode()
        elif "browser.open" in message and "agentic_report.md" in message:
            events = [
                {"type": "delegation_started", "last_progress": "Provider-native worker is running."},
                {"type": "delegation_progress", "last_progress": "Using browser.open…"},
                {"type": "delegation_progress", "last_progress": "Finished browser.extract; continuing."},
                {"type": "delegation_progress", "last_progress": "Finished fs.write_file; continuing."},
                {"type": "delegation_progress", "last_progress": "Finished fs.read_file; continuing."},
                {
                    "type": "delegation_completed",
                    "last_progress": "Completed explicit browser-to-artifact recipe.",
                },
            ]
            body = "".join(json.dumps(event) + "\n" for event in events).encode()
        elif "newest entry" in message:
            events = [
                {
                    "type": "tool_result",
                    "name": "web.search",
                    "ok": True,
                    "calls": ["web.search", "web.fetch"],
                },
                {"type": "text", "text": "July 9, 2026 — https://example.test/release-notes"},
            ]
            body = "".join(json.dumps(event) + "\n" for event in events).encode()
        elif "Call the registered web.fetch" in message:
            primary = message.split("Primary: ", 1)[1].splitlines()[0]
            commentary = message.split("Commentary: ", 1)[1].splitlines()[0]
            events = [
                {"type": "tool_result", "name": "web.fetch", "ok": True},
                {"type": "tool_result", "name": "web.fetch", "ok": True},
                {
                    "type": "text",
                    "text": (
                        f"CEDAR-17 is verified by the primary ledger ({primary}). "
                        f"RIVER-99 is a rejected conflict from untrusted commentary ({commentary})."
                    ),
                },
            ]
            body = "".join(json.dumps(event) + "\n" for event in events).encode()
        elif "orange river" in message:
            token = "orange river works."
        elif "blue cedar" in message:
            token = "blue cedar works."
        elif "I prefer PARITY-MEMORY-" in message:
            token = "MEMORY-SAVED."
        elif "TWO" in message:
            token = "PARITY-TURN-TWO"
        elif "What preference did I tell you?" in message:
            token = type(self).memory_pin or "NO-MEMORY"
        elif "If none is stored" in message or "What is my stored preference" in message:
            token = type(self).memory_pin or "NO-STORED-PREFERENCE"
        elif "For this temporary chat only" in message:
            token = "TEMP-ACK"
        else:
            token = "PARITY-TURN-ONE"
        if (
            "newest entry" not in message
            and "Call the registered web.fetch" not in message
            and "attached hostile input" not in message
            and "DATA-ADVERSARIAL-1460" not in message
            and "grounded_report.md" not in message
            and "conflict_report.md" not in message
            and "CSV input" not in message
            and not ("browser.open" in message and "agentic_report.md" in message)
        ):
            body = (json.dumps({"type": "text", "text": token}) + "\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self) -> None:  # noqa: N802
        if self.path == "/api/memory/pins/user.preference":
            type(self).memory_pin = None
            body = json.dumps({"ok": True, "key": "user.preference"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


def test_live_web_search_probe_requires_receipt_date_url_and_no_leak() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context = ProbeContext(
            ROOT,
            f"http://127.0.0.1:{server.server_port}",
            "local",
            "model",
            False,
            timeout_seconds=5,
        )
        check = {"kind": "live_probe", "probe": "web_search_cited_answer", "severity": "critical"}
        row = evaluate_check("web", 3, 0, check, context)
        assert row.passed is True
        assert "July 9, 2026" in row.actual
        assert '"receipt_ok": true' in row.actual
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_agentic_browser_artifact_probe_requires_progress_receipt_and_grounded_file() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context = ProbeContext(
            ROOT,
            f"http://127.0.0.1:{server.server_port}",
            "local",
            "model",
            False,
            timeout_seconds=5,
        )
        check = {"kind": "live_probe", "probe": "agentic_browser_artifact", "severity": "critical"}
        row = evaluate_check("agentic", 3, 0, check, context)
        assert row.passed is True
        assert '"receipt_ok": true' in row.actual
        assert "Example Domain" in row.actual
        assert "fs.read_file" in row.actual
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_data_code_chart_probe_requires_analysis_markers_and_verified_artifact() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context = ProbeContext(
            ROOT,
            f"http://127.0.0.1:{server.server_port}",
            "local",
            "model",
            False,
            timeout_seconds=5,
        )
        check = {"kind": "live_probe", "probe": "data_code_chart_roundtrip", "severity": "critical"}
        row = evaluate_check("data-code-charts", 3, 0, check, context)
        assert row.passed is True
        assert '"missing": []' in row.actual
        assert '"receipt_ok": true' in row.actual
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_data_adversarial_probe_requires_safe_formula_chart_and_sandbox(monkeypatch) -> None:
    async def _fake_data_browser(_context, execution_id):
        assert execution_id == "exec-data-adversarial"
        return True, {
            "total": ["1460"],
            "peak": ["Alpha 1200"],
            "formula": ['\'=HYPERLINK("https://evil.test","click")'],
            "audit_before": ["Closed"],
            "audit_after": ["Open"],
        }

    monkeypatch.setattr("chatgpt_parity_data_probes.data_browser_interaction", _fake_data_browser)
    _ChatHandler.data_clean_requested = False
    _ChatHandler.data_adversarial_requested = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context = ProbeContext(
            ROOT,
            f"http://127.0.0.1:{server.server_port}",
            "local",
            "model",
            False,
            timeout_seconds=5,
        )
        row = evaluate_check(
            "data-code-charts",
            4,
            0,
            {"kind": "live_probe", "probe": "data_dirty_formula_sandbox", "severity": "critical"},
            context,
        )
        assert row.passed is True
        payload = json.loads(row.actual)
        assert payload["formula_safe"] is True
        assert payload["cleaned_rows"]["Beta"] == 300.0
        assert payload["sandbox"]["blocked_exit"] != 0
        assert payload["csp_ok"] is True
        assert payload["browser"]["audit_after"] == ["Open"]
    finally:
        _ChatHandler.data_clean_requested = False
        _ChatHandler.data_adversarial_requested = False
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_document_probes_require_grounded_download_and_adversarial_sources() -> None:
    _ChatHandler.document_grounded_requested = False
    _ChatHandler.document_conflict_requested = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context = ProbeContext(
            ROOT,
            f"http://127.0.0.1:{server.server_port}",
            "local",
            "model",
            False,
            timeout_seconds=5,
        )
        grounded = evaluate_check(
            "files-documents",
            3,
            0,
            {"kind": "live_probe", "probe": "document_upload_grounded_artifact", "severity": "high"},
            context,
        )
        adversarial = evaluate_check(
            "files-documents",
            4,
            0,
            {
                "kind": "live_probe",
                "probe": "document_conflict_truncation_grounding",
                "severity": "high",
            },
            context,
        )
        assert grounded.passed is True
        assert adversarial.passed is True
        grounded_payload = json.loads(grounded.actual)
        adversarial_payload = json.loads(adversarial.actual)
        assert grounded_payload["missing"] == []
        assert grounded_payload["artifact_status"] == 200
        assert adversarial_payload["conflict_rejected"] is True
        assert adversarial_payload["truncated_tail_excluded"] is True
        assert adversarial_payload["source_instruction_rejected"] is True
    finally:
        _ChatHandler.document_grounded_requested = False
        _ChatHandler.document_conflict_requested = False
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_image_probe_dispatch_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    context = ProbeContext(ROOT, "http://127.0.0.1:1", "local", "model", False, timeout_seconds=5)
    monkeypatch.setattr(
        parity_probes,
        "_image_understanding_generation_edit_probe",
        lambda _ctx: (True, '{"vision_ok": true, "artifact": {"passed": true}}'),
    )
    monkeypatch.setattr(
        parity_probes,
        "_image_visual_injection_edit_fidelity_probe",
        lambda _ctx: (True, '{"visual_injection_rejected": true, "edit_fidelity": true}'),
    )

    tier3 = evaluate_check(
        "multimodal-images",
        3,
        0,
        {"kind": "live_probe", "probe": "image_understanding_generation_edit", "severity": "high"},
        context,
    )
    tier4 = evaluate_check(
        "multimodal-images",
        4,
        0,
        {"kind": "live_probe", "probe": "image_visual_injection_edit_fidelity", "severity": "high"},
        context,
    )

    assert tier3.passed is True
    assert tier4.passed is True
    assert '"edit_fidelity": true' in tier4.actual


def test_privacy_probe_dispatch_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    context = ProbeContext(ROOT, "http://127.0.0.1:1", "local", "model", False, timeout_seconds=5)
    monkeypatch.setattr(
        parity_probes,
        "_privacy_export_delete_temporary_probe",
        lambda _ctx: (True, '{"export_status": 200, "temporary_get_status": 404}'),
    )
    monkeypatch.setattr(
        parity_probes,
        "_privacy_remanence_isolation_lockdown_probe",
        lambda _ctx: (True, '{"sqlite_marker_rows": 0, "browser_denied": true}'),
    )

    tier3 = evaluate_check(
        "privacy-export-controls",
        3,
        0,
        {"kind": "live_probe", "probe": "privacy_export_delete_temporary", "severity": "critical"},
        context,
    )
    tier4 = evaluate_check(
        "privacy-export-controls",
        4,
        0,
        {"kind": "live_probe", "probe": "privacy_remanence_isolation_lockdown", "severity": "critical"},
        context,
    )

    assert tier3.passed is True
    assert '"export_status": 200' in tier3.actual
    assert tier4.passed is True
    assert '"sqlite_marker_rows": 0' in tier4.actual


def test_privacy_registry_lockdown_blocks_external_execution() -> None:
    receipt = memory_probes._privacy_registry_lockdown_receipt()

    assert receipt["visible_tools"] == ["fs.read"]
    assert receipt["browser_denied"] is True
    assert receipt["email_denied"] is True
    assert receipt["local_allowed"] is True
    assert receipt["base_executed"] == ["fs.read"]
    assert receipt["denied"] == ["browser.open", "email.send"]


def test_project_probe_dispatch_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    context = ProbeContext(ROOT, "http://127.0.0.1:1", "local", "model", False, timeout_seconds=5)
    monkeypatch.setattr(
        parity_probes,
        "_project_workspace_lifecycle_probe",
        lambda _ctx: (True, '{"resume_chat_count": 2, "share_read_status": 200}'),
    )
    monkeypatch.setattr(
        parity_probes,
        "_project_isolation_stale_share_probe",
        lambda _ctx: (True, '{"cross_project_attach_status": 409, "stale_library_count": 1}'),
    )

    tier3 = evaluate_check(
        "projects-library-sharing",
        3,
        0,
        {"kind": "live_probe", "probe": "project_workspace_lifecycle", "severity": "high"},
        context,
    )
    tier4 = evaluate_check(
        "projects-library-sharing",
        4,
        0,
        {"kind": "live_probe", "probe": "project_isolation_stale_share", "severity": "high"},
        context,
    )

    assert tier3.passed is True
    assert '"resume_chat_count": 2' in tier3.actual
    assert tier4.passed is True
    assert '"cross_project_attach_status": 409' in tier4.actual


def test_voice_probe_dispatch_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    context = ProbeContext(ROOT, "http://127.0.0.1:1", "local", "model", False, timeout_seconds=5)
    monkeypatch.setattr(
        parity_probes,
        "_voice_audio_roundtrip_probe",
        lambda _ctx: (True, '{"output_transcript": "voice conversation okay"}'),
    )
    monkeypatch.setattr(
        parity_probes,
        "_voice_noise_language_interrupt_latency_probe",
        lambda _ctx: (True, '{"noise_added": true, "interrupt": {"canceled": true}}'),
    )

    tier3 = evaluate_check(
        "voice-dictation",
        3,
        0,
        {"kind": "live_probe", "probe": "voice_audio_roundtrip", "severity": "high"},
        context,
    )
    tier4 = evaluate_check(
        "voice-dictation",
        4,
        0,
        {"kind": "live_probe", "probe": "voice_noise_language_interrupt_latency", "severity": "high"},
        context,
    )

    assert tier3.passed is True
    assert "voice conversation okay" in tier3.actual
    assert tier4.passed is True
    assert '"canceled": true' in tier4.actual


def test_image_svg_contract_rejects_unsafe_or_destructive_edits() -> None:
    generated = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">'
        '<rect id="background" x="0" y="0" width="640" height="360" fill="#CC5500"/>'
        '<circle id="focus" cx="200" cy="180" r="60" fill="#005FCC"/>'
        '<text id="code">CEDAR 936</text></svg>'
    )
    edited = generated.replace(
        "</svg>",
        '<polygon id="edit-star" points="1,2 3,4 5,6" fill="#FFD700"/><text id="edit-label">EDITED 42</text></svg>',
    )
    unsafe = edited.replace("</svg>", "<script>alert(1)</script></svg>")
    destructive = edited.replace('cx="200"', 'cx="201"')

    assert _scene_contract(_svg_summary(generated), edited=False) is True
    assert _scene_contract(_svg_summary(edited), edited=True) is True
    assert _scene_contract(_svg_summary(unsafe), edited=True) is False
    assert _scene_contract(_svg_summary(destructive), edited=True) is False


def test_agentic_interrupt_approval_recovery_probe_is_fail_closed() -> None:
    context = ProbeContext(
        ROOT,
        "http://127.0.0.1:1",
        "local",
        "model",
        False,
        timeout_seconds=5,
    )
    check = {
        "kind": "live_probe",
        "probe": "agentic_interrupt_approval_recovery",
        "severity": "critical",
    }

    row = evaluate_check("agentic-work-browser-computer", 4, 0, check, context)

    assert row.passed is True
    payload = json.loads(row.actual)
    assert payload["redirected_instructions"] == ["Redirect the report to the verified burnt-orange format."]
    assert payload["approval_denial"]["executor_ran"] is False
    assert payload["approval_denial"]["result"]["ok"] is False
    assert payload["recovery_receipt"]["ok"] is True


def test_scheduled_recovery_probe_requires_unique_slots_durable_skip_and_useful_alerts() -> None:
    context = ProbeContext(ROOT, "http://127.0.0.1:1", "local", "model", False, timeout_seconds=5)
    row = evaluate_check(
        "scheduled-monitoring",
        4,
        0,
        {"kind": "live_probe", "probe": "scheduled_recovery_dedup_noise", "severity": "critical"},
        context,
    )

    assert row.passed is True
    payload = json.loads(row.actual)
    assert payload["unique_catch_up"] is True
    assert payload["clock_rollback_safe"] is True
    assert payload["noise_suppressed"] is True
    assert payload["skipped_durably"] is True


def test_connected_app_adversarial_probe_rejects_unsafe_effect_claims() -> None:
    context = ProbeContext(ROOT, "http://127.0.0.1:1", "local", "model", False, timeout_seconds=5)
    row = evaluate_check(
        "connected-apps-actions",
        4,
        0,
        {"kind": "live_probe", "probe": "connected_app_adversarial_controls", "severity": "critical"},
        context,
    )

    assert row.passed is True
    payload = json.loads(row.actual)
    assert payload["approval_denied"] is True
    assert payload["duplicate_suppressed"] is True
    assert payload["disconnected_rejected"] is True
    assert payload["forged_rejected"] is True


def test_custom_assistant_plugin_lifecycle_probe_uses_and_cleans_real_plugin() -> None:
    context = ProbeContext(ROOT, "http://127.0.0.1:1", "local", "model", False, timeout_seconds=5)
    row = evaluate_check(
        "custom-assistants-plugins",
        3,
        0,
        {"kind": "live_probe", "probe": "custom_assistant_plugin_lifecycle", "severity": "high"},
        context,
    )

    assert row.passed is True
    payload = json.loads(row.actual)
    assert payload["validation_ok"] is True
    assert payload["published_catalog"] == ["parity-launch-guide"]
    assert payload["bundle_verification"]["valid"] is True
    assert payload["cleanup_ok"] is True
    assert "BLUE-CEDAR-936" in payload["use"]["knowledge"][0]["excerpt"]


def test_custom_assistant_plugin_adversarial_probe_fails_closed_and_cleans_state() -> None:
    context = ProbeContext(ROOT, "http://127.0.0.1:1", "local", "model", False, timeout_seconds=5)
    row = evaluate_check(
        "custom-assistants-plugins",
        4,
        0,
        {"kind": "live_probe", "probe": "custom_assistant_plugin_adversarial", "severity": "high"},
        context,
    )

    assert row.passed is True
    payload = json.loads(row.actual)
    assert payload["malicious_manifest_rejected"] is True
    assert payload["malicious_import_ran"] is False
    assert payload["permission_denied"] is True
    assert payload["knowledge_isolated"] is True
    assert payload["manifest_mismatch_rejected"] is True
    assert payload["payload_preserved_after_mismatch"] is True
    assert payload["cleanup_status"] == "removed"
    assert payload["final_plugins"] == {}
    assert payload["no_tombstones"] is True
    assert payload["hostile_bundle_verification"]["pattern"] == "unsafe_path"


def test_live_web_conflict_probe_requires_two_receipts_citations_and_injection_rejection() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context = ProbeContext(
            ROOT,
            f"http://127.0.0.1:{server.server_port}",
            "local",
            "model",
            False,
            timeout_seconds=5,
        )
        check = {"kind": "live_probe", "probe": "web_source_conflict", "severity": "critical"}
        row = evaluate_check("web-search-deep-research", 4, 0, check, context)
        assert row.passed is True
        assert '"fetch_receipts": 2' in row.actual
        assert '"rejected_conflict": true' in row.actual
        assert "CEDAR-17" in row.actual
        assert "RIVER-99" in row.actual
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_live_memory_probe_requires_cross_session_recall_and_cleanup() -> None:
    _ChatHandler.memory_pin = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context = ProbeContext(
            ROOT,
            f"http://127.0.0.1:{server.server_port}",
            "local",
            "model",
            False,
            timeout_seconds=5,
        )
        check = {"kind": "live_probe", "probe": "memory_cross_session_recall", "severity": "critical"}
        row = evaluate_check("memory-personalization", 3, 0, check, context)
        assert row.passed is True
        assert "PARITY-MEMORY-" in row.actual
        assert '"cleanup_ok": true' in row.actual
        assert _ChatHandler.memory_pin is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _ChatHandler.memory_pin = None


def test_live_memory_adversarial_probe_corrects_isolates_deletes_and_cleans_up() -> None:
    _ChatHandler.memory_pin = None
    _ChatHandler.memory_contradictions = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        context = ProbeContext(
            ROOT,
            f"http://127.0.0.1:{server.server_port}",
            "local",
            "model",
            False,
            timeout_seconds=5,
        )
        row = evaluate_check(
            "memory-personalization",
            4,
            0,
            {
                "kind": "live_probe",
                "probe": "memory_correction_deletion_isolation",
                "severity": "critical",
            },
            context,
        )
        assert row.passed is True
        payload = json.loads(row.actual)
        assert payload["contradiction_detected"] is True
        assert "PARITY-CORRECTED-" in payload["corrected_recall"]
        assert "PARITY-TEMP-" not in payload["post_temp_recall"]
        assert payload["deleted_recall"] == "NO-STORED-PREFERENCE"
        assert payload["cleanup_ok"] is True
        assert _ChatHandler.memory_pin is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _ChatHandler.memory_pin = None
        _ChatHandler.memory_contradictions = []


def test_scheduled_task_lifecycle_probe_creates_fires_manages_and_cleans_up() -> None:
    context = ProbeContext(
        ROOT,
        "http://127.0.0.1:1",
        "local",
        "model",
        False,
        timeout_seconds=5,
    )
    check = {"kind": "live_probe", "probe": "scheduled_task_lifecycle", "severity": "critical"}

    row = evaluate_check("scheduled-monitoring", 3, 0, check, context)

    assert row.passed is True
    payload = json.loads(row.actual)
    assert payload["notifications"][0]["goal"] == "PARITY-SCHEDULE-CREATED"
    assert payload["paused"]["status"] == "paused"
    assert payload["updated"]["task"] == "PARITY-SCHEDULE-UPDATED"
    assert payload["resumed"]["status"] == "active"
    assert payload["deleted"] == []
    assert payload["persisted_after_cleanup"]["tasks"] == []


def test_connected_app_probe_reads_drafts_executes_and_returns_receipt() -> None:
    context = ProbeContext(
        ROOT,
        "http://127.0.0.1:1",
        "local",
        "model",
        False,
        timeout_seconds=5,
    )
    check = {"kind": "live_probe", "probe": "connected_app_receipt", "severity": "critical"}

    row = evaluate_check("connected-apps-actions", 3, 0, check, context)

    assert row.passed is True
    payload = json.loads(row.actual)
    assert payload["source"]["id"] == "fixture-message-1"
    assert payload["sent"] == [payload["draft"]]
    assert payload["receipt"]["receipt_id"] == "fixture-send-1"
    assert payload["receipt"]["approval"] == "fixture_policy_checked"
    assert payload["receipt"]["evidence"]["fixture_only"] is True


def test_gap_renderer_names_first_failed_tier() -> None:
    loop = _load_loop()
    rubric = _rubric()
    rows = [EvidenceRow("core", tier, str(tier), "pass", "fail", False, "critical") for tier in range(1, 5)]
    scorecard = score_families(rubric, rows)
    rendered = loop._render_gaps(rubric, scorecard)
    assert "first failed tier 1" in rendered
    assert "0/4" in rendered
