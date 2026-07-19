from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STRESS = ROOT / "tests" / "stress"
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))

from chatgpt_parity_harness import EvidenceRow
from chatgpt_parity_probes import ProbeContext, evaluate_check


class _ConversationHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    messages: list[dict[str, str]] = []
    stale_revision = False
    drop_persisted_assistant = False
    opposite_constraint = False
    duplicate_pair = False

    def log_message(self, format: str, *args: object) -> None:
        _ = (format, args)

    def _respond(self, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/api/v2/chat/session/test-session":
            self.send_response(404)
            self.end_headers()
            return
        messages = list(type(self).messages)
        if type(self).duplicate_pair:
            messages[:0] = [
                {"role": "user", "content": "contaminating turn"},
                {"role": "assistant", "content": "contaminating reply"},
            ]
        if type(self).drop_persisted_assistant:
            for index in range(len(messages) - 1, -1, -1):
                if messages[index].get("role") == "assistant":
                    del messages[index]
                    break
        self._respond(
            json.dumps(
                {
                    "session_id": "test-session",
                    "conversation": {
                        "version": len(messages),
                        "messages": messages,
                        "message_count": len(messages),
                    },
                }
            ).encode()
        )

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/session/new":
            self._respond(json.dumps({"session_id": "test-session"}).encode())
            return
        if self.path != "/api/v2/chat":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length") or 0)
        message = str(json.loads(self.rfile.read(length))["message"])
        if "Start a working brief for later turns" in message:
            reply = (
                "Project LANTERN-41 serves independent bookstores, launches October 17, "
                "has a $12,000 budget, and uses email as the primary channel."
            )
        elif "Revise that working brief" in message:
            reply = (
                "Project LANTERN-41 | independent bookstores | October 17 | $12,000 | email"
                if type(self).stale_revision
                else "Project LANTERN-41 | independent bookstores | November 2 | $9,000 | email"
            )
        else:
            constraint = (
                "Paid advertising is not prohibited"
                if type(self).opposite_constraint
                else "Do not use paid advertising"
            )
            reply = json.dumps(
                {
                    "project": "LANTERN-41",
                    "audience": "independent bookstores",
                    "launch_date": "November 2",
                    "budget": "$9,000",
                    "primary_channel": "email",
                    "constraint": constraint,
                }
            )
        type(self).messages.extend(
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply},
            ]
        )
        self._respond((json.dumps({"type": "text", "text": reply}) + "\n").encode(), "application/x-ndjson")


def _run_conversation_probe(probe: str) -> EvidenceRow:
    _ConversationHandler.messages = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ConversationHandler)
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
        return evaluate_check(
            "core",
            4,
            0,
            {"kind": "live_probe", "probe": probe, "severity": "critical"},
            context,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _ConversationHandler.messages = []
        _ConversationHandler.stale_revision = False
        _ConversationHandler.drop_persisted_assistant = False
        _ConversationHandler.opposite_constraint = False
        _ConversationHandler.duplicate_pair = False


@pytest.mark.parametrize("probe", ["conversation_multi_turn", "conversation_adversarial_followup"])
def test_live_conversation_probe_revises_context_and_proves_persistence(probe: str) -> None:
    row = _run_conversation_probe(probe)

    assert row.passed is True
    payload = json.loads(row.actual)
    assert payload["revision_ok"] is True
    assert payload["contract_ok"] is True
    assert payload["poisoned"] is False
    assert payload["transcript_ok"] is True
    assert payload["persisted_message_count"] == 6


def test_live_conversation_probe_rejects_stale_revision() -> None:
    _ConversationHandler.stale_revision = True
    row = _run_conversation_probe("conversation_multi_turn")
    assert row.passed is False
    assert json.loads(row.actual)["revision_ok"] is False


def test_live_conversation_probe_rejects_unpersisted_streamed_reply() -> None:
    _ConversationHandler.drop_persisted_assistant = True
    row = _run_conversation_probe("conversation_adversarial_followup")
    assert row.passed is False
    payload = json.loads(row.actual)
    assert payload["contract_ok"] is True
    assert payload["transcript_ok"] is False


def test_live_conversation_probe_rejects_opposite_constraint_meaning() -> None:
    _ConversationHandler.opposite_constraint = True
    row = _run_conversation_probe("conversation_multi_turn")
    assert row.passed is False
    assert json.loads(row.actual)["contract_ok"] is False


def test_live_conversation_probe_rejects_contaminated_fresh_session() -> None:
    _ConversationHandler.duplicate_pair = True
    row = _run_conversation_probe("conversation_multi_turn")
    assert row.passed is False
    payload = json.loads(row.actual)
    assert payload["persisted_message_count"] == 8
    assert payload["transcript_ok"] is False
