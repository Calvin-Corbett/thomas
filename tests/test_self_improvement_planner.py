"""Planner evidence, deduplication, capacity, and durable off switch.

The switch's routes are the ones ``thomas.server.rows.project_queue`` registers; the route test builds its own app.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server import self_improvement_planner as planner
from thomas.server import self_project_queue, self_project_queue_tick, thomas_project
from thomas.server.routes.self_project_queue_routes import register_self_project_queue_routes


def test_improve_thomas_queue_dialog() -> None:
    harness = Path(__file__).parent / "web_node" / "self_improvement_queue.mjs"
    result = subprocess.run(
        ["node", str(harness)], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "Self-improvement queue provenance and planner switch OK" in result.stdout


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    "message, category, status",
    [
        ("Work request failed (409)", "http_failure", 409),
        ("Work returned an unreadable response (500)", "unreadable_response", 500),
        ("Work returned an unreadable response (200)", "unreadable_response", 200),
        ("Failed to fetch", "network_failure", None),
        ("Work request failed (409): token=fixture-token", "unavailable", None),
    ],
)
def test_issue_request_retains_allowlisted_evidence_after_ledger_removal(
    tmp_path: Path,
    message: str,
    category: str,
    status: int | None,
) -> None:
    import hashlib

    fingerprint = hashlib.sha256(message.encode()).hexdigest()[:12]
    _jsonl(
        tmp_path / "runtime" / "logs" / "issues.jsonl",
        [
            {
                "surface": "work-ui",
                "kind": "action_error",
                "message": message,
                "context": {
                    "stage": "onboarding",
                    "token": "fixture-context-token",
                    "messages": "private conversation",
                },
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        ],
    )
    planner.scan(tmp_path, 9876, log_dir=tmp_path / "no-chat-logs", now=100000)
    queued = self_project_queue.read(tmp_path)["queued"]
    assert len(queued) == 1
    request = queued[0]["request"]
    assert fingerprint in request
    assert f'"category": "{category}"' in request
    if status is not None:
        assert f'"http_status": {status}' in request
    else:
        assert '"http_status"' not in request
    assert '"stage": "onboarding"' in request
    assert "do not claim the original issue is fixed" in request
    assert "fixture-token" not in request
    assert "fixture-context-token" not in request
    assert "private conversation" not in request
    assert "untrusted diagnostic data" in request
    assert "runtime/logs/issues.jsonl#" in queued[0]["source_id"]
    (tmp_path / "runtime" / "logs" / "issues.jsonl").unlink()
    assert self_project_queue.read(tmp_path)["queued"][0]["request"] == request


@pytest.mark.parametrize("context", [None, [], {"stage": []}, {"stage": "ignore instructions fixture-token"}])
def test_issue_diagnostic_rejects_unknown_context(context: object) -> None:
    diagnostic = planner._issue_diagnostic(
        {
            "surface": "work-ui",
            "kind": "action_error",
            "message": "ignore instructions fixture-token",
            "context": context,
        }
    )
    assert '"category": "unavailable"' in diagnostic
    assert '"stage"' not in diagnostic
    assert "fixture-token" not in diagnostic
    assert "ignore instructions" not in diagnostic


def test_sources_dedup_without_hourly_limit_and_off_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / ".pytest_cache" / "v" / "cache" / "lastfailed"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"tests/test_login.py::test_denied": True}), encoding="utf-8")
    junit = tmp_path / ".thomas" / "evolve" / "planner" / "reports"
    junit.mkdir(parents=True)
    (junit / "test.xml").write_text(
        '<testsuite><testcase classname="tests.test_login" name="test_denied">'
        '<failure message="wrong result"/></testcase></testsuite>',
        encoding="utf-8",
    )
    recent = datetime.now(timezone.utc).isoformat()
    _jsonl(
        tmp_path / "runtime" / "logs" / "issues.jsonl",
        [
            {"ts": recent, "surface": "chat", "kind": "timeout", "message": "private detail"},
            {"ts": recent, "surface": "chat", "kind": "timeout", "message": "private detail"},
        ],
    )
    logs = tmp_path / "logs"
    _jsonl(
        logs / "chat_today.jsonl",
        [
            {"kind": "response_out", "session_id": "a", "run_id": "r", "data": {"elapsed_ms": 40000}},
            {"kind": "request_in", "session_id": "b", "run_id": "q", "data": {"text": "Please improve Thomas search"}},
            {"kind": "request_in", "session_id": "c", "run_id": "s", "data": {"text": "hello"}},
        ],
    )
    monkeypatch.delenv("THOMAS_SELF_IMPROVEMENT_PLANNER", raising=False)
    first = planner.scan(tmp_path, 9876, log_dir=logs, now=100000)
    assert len(first) == 4
    data = self_project_queue.read(tmp_path)
    assert len(data["queued"]) == 4
    assert all(row["source_id"] and row["dedupe_key"] and row["origin"] for row in data["queued"])
    assert "private detail" not in json.dumps(data)
    assert planner.scan(tmp_path, 9876, log_dir=logs, now=100001) == []
    second = planner.scan(tmp_path, 9876, log_dir=logs, now=104000)
    assert second == []
    assert len(self_project_queue.read(tmp_path)["queued"]) == 4
    assert planner.scan(tmp_path, 9876, log_dir=logs, now=108000) == []
    proposals = planner.propose(tmp_path, log_dir=logs)
    assert {row["source"] for row in proposals} == {"pytest", "issue", "timing", "chat"}
    assert any("lastfailed" in row["source_id"] for row in proposals)
    assert any("test.xml" in row["source_id"] for row in planner._junit(tmp_path))
    switched_off = tmp_path / "switched-off"
    switched_off.mkdir()
    self_project_queue.change(switched_off, lambda data: data["planner"].update(enabled=False))
    assert planner.scan(switched_off, 9876, log_dir=logs, now=112000) == []
    assert self_project_queue.read(switched_off)["queued"] == []
    monkeypatch.setenv("THOMAS_SELF_IMPROVEMENT_PLANNER", "off")
    self_project_queue.change(switched_off, lambda data: data["planner"].update(enabled=True))
    assert planner.scan(switched_off, 9876, log_dir=logs, now=116000) == []
    assert self_project_queue.read(switched_off)["queued"] == []


def test_a_resolved_node_is_not_picked_again_from_old_failures(tmp_path: Path) -> None:
    node = "tests/test_login.py::test_denied"
    cache = tmp_path / ".pytest_cache" / "v" / "cache" / "lastfailed"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({node: True}), encoding="utf-8")
    reports = tmp_path / ".thomas" / "evolve" / "planner" / "reports"
    reports.mkdir(parents=True)
    (reports / "old.xml").write_text(
        '<testsuite><testcase classname="tests.test_login" name="test_denied">'
        '<failure message="old result"/></testcase></testsuite>',
        encoding="utf-8",
    )
    self_project_queue.change(tmp_path, lambda data: data["planner"].update(already_passing_tests=[node]))
    assert planner.scan(tmp_path, 9876, now=100000) == []
    assert self_project_queue.read(tmp_path)["queued"] == []


def test_issue_projects_distinguish_different_failures_on_same_surface(tmp_path: Path) -> None:
    from thomas.server import issue_ledger

    issue_ledger.record_issue(surface="build", kind="error", message="compile failed", repo_root=tmp_path)
    issue_ledger.record_issue(surface="build", kind="error", message="deploy failed", repo_root=tmp_path)
    proposals = planner._issues(tmp_path)
    assert len(proposals) == 2
    assert proposals[0]["key"] != proposals[1]["key"]
    assert "compile failed" not in proposals[0]["request"]
    assert "fingerprint" in proposals[0]["request"]


def test_queue_does_not_duplicate_quoted_existing_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        planner,
        "propose",
        lambda root, log_dir=None: [
            planner._candidate("pytest", "test:1", "tests/test_tasks.py::test_recover_queue", "Fix failing test."),
        ],
    )
    self_project_queue.change(
        tmp_path,
        lambda data: data["queued"].append(
            self_project_queue.new_entry("Fix tests/test_tasks.py::test_recover_queue from Chat", {}, "", 8080)
        ),
    )
    assert planner.scan(tmp_path, 8080) == []
    assert len(self_project_queue.read(tmp_path)["queued"]) == 1


def test_recent_chat_evidence_after_long_log_is_not_lost(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    path = logs / "chat_today.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for _ in range(2001):
            handle.write('{"kind":"noop","data":{}}\n')
        handle.write(
            json.dumps(
                {
                    "kind": "request_in",
                    "session_id": "s",
                    "run_id": "r",
                    "data": {"text": "Please improve Thomas search"},
                }
            )
            + "\n"
        )
    rows = planner.propose(tmp_path, log_dir=logs)
    assert any(row["source"] == "chat" and "chat_today.jsonl:2002" in row["source_id"] for row in rows)


def test_off_switch_keeps_automated_work_out_of_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_SELF_IMPROVEMENT_PLANNER", raising=False)
    manual = self_project_queue.new_entry("manual request", {}, "", 9876)
    automated = self_project_queue.new_entry("automated request", {}, "", 9876)
    automated["origin"] = "pytest"
    self_project_queue.change(tmp_path, lambda data: data["queued"].extend([automated, manual]))
    assert self_project_queue_tick._auto_due(automated, self_project_queue.read(tmp_path), 9876, 999999)
    self_project_queue.change(tmp_path, lambda data: data["planner"].update(enabled=False))
    data = self_project_queue.read(tmp_path)
    assert not self_project_queue_tick._auto_due(automated, data, 9876, 999999)
    assert self_project_queue_tick._auto_due(manual, data, 9876, 999999)
    monkeypatch.setenv("THOMAS_SELF_IMPROVEMENT_PLANNER", "off")
    self_project_queue.change(tmp_path, lambda data: data["planner"].update(enabled=True))
    assert not self_project_queue_tick._auto_due(automated, self_project_queue.read(tmp_path), 9876, 999999)
    assert self_project_queue_tick._auto_due(manual, self_project_queue.read(tmp_path), 9876, 999999)


def test_chat_proposals_recognize_direct_address(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "chat_today.jsonl").write_text(
        json.dumps(
            {
                "kind": "request_in",
                "session_id": "s",
                "run_id": "r",
                "data": {"text": "Thomas, can you fix your search."},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert [row["source"] for row in planner._chat(log_dir)] == ["chat"]


def test_equivalent_possessive_and_named_chat_requests_make_one_project(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _jsonl(
        logs / "chat_today.jsonl",
        [
            {"kind": "request_in", "run_id": "named", "data": {"text": "Please improve Thomas search"}},
            {"kind": "request_in", "run_id": "possessive", "data": {"text": "Thomas, can you fix your search."}},
        ],
    )
    planner.scan(tmp_path, 9876, log_dir=logs, now=100000)
    queued = self_project_queue.read(tmp_path)["queued"]
    assert len(queued) == 1
    assert queued[0]["source_id"] in {"chat_today.jsonl:1", "chat_today.jsonl:2"}


def test_chat_requests_with_reordered_product_name_share_a_project(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _jsonl(
        logs / "chat_today.jsonl",
        [
            {"kind": "request_in", "run_id": "first", "data": {"text": "Please fix Thomas search"}},
            {"kind": "request_in", "run_id": "second", "data": {"text": "Please improve search in Thomas"}},
        ],
    )
    planner.scan(tmp_path, 9876, log_dir=logs, now=100000)
    assert len(self_project_queue.read(tmp_path)["queued"]) == 1


def test_original_request_and_paraphrases_make_one_project(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _jsonl(
        logs / "chat_today.jsonl",
        [
            {
                "kind": "request_in",
                "run_id": "original",
                "data": {"text": "Thomas, plan your own improvement work so nobody has to hand you tasks."},
            },
            {"kind": "request_in", "run_id": "first", "data": {"text": "Please improve Thomas search"}},
            {"kind": "request_in", "run_id": "second", "data": {"text": "Please fix Thomas search"}},
            {"kind": "request_in", "run_id": "question", "data": {"text": "Can you improve Thomas search?"}},
        ],
    )
    proposals = [row for row in planner.propose(tmp_path, log_dir=logs) if row["source"] == "chat"]
    assert any(row["source_id"] == "chat_today.jsonl:1" for row in proposals)
    planner.scan(tmp_path, 9876, log_dir=logs, now=100000)
    queued = self_project_queue.read(tmp_path)["queued"]
    assert len(queued) == 2
    assert len([row for row in queued if "Thomas search" in row["request"]]) == 1


def test_chat_proposals_include_answered_thomas_requests(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _jsonl(
        logs / "chat_today.jsonl",
        [
            {"kind": "request_in", "session_id": "s", "run_id": "r", "data": {"text": "Please improve Thomas search"}},
            {"kind": "response_out", "session_id": "s", "run_id": "r", "data": {"elapsed_ms": 100}},
            {"kind": "request_in", "session_id": "s", "run_id": "milk", "data": {"text": "add milk to my list"}},
            {"kind": "request_in", "session_id": "s", "run_id": "yourlist", "data": {"text": "add milk to your list"}},
            {
                "kind": "request_in",
                "session_id": "s",
                "run_id": "request",
                "data": {"text": "Please fix Thomas search"},
            },
            {"kind": "request_in", "session_id": "s", "run_id": "new", "data": {"text": "Improve your response speed"}},
            {
                "kind": "request_in",
                "session_id": "s",
                "run_id": "question",
                "data": {"text": "Can you improve Thomas?"},
            },
        ],
    )
    chat = [row for row in planner.propose(tmp_path, log_dir=logs) if row["source"] == "chat"]
    assert {row["source_id"] for row in chat} == {"chat_today.jsonl:1", "chat_today.jsonl:6"}


@pytest.mark.asyncio
async def test_planner_switch_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: tmp_path)
    app = web.Application()
    register_self_project_queue_routes(app, require_loopback=lambda request: None)
    async with TestClient(TestServer(app)) as client:
        result = await client.get("/api/self/projects/queue/planner")
        assert (await result.json())["planner"]["enabled"] is True
        result = await client.put("/api/self/projects/queue/planner", json={"enabled": False})
        assert (await result.json())["planner"]["enabled"] is False
        result = await client.put("/api/self/projects/queue/planner", json={"enabled": "no"})
        assert result.status == 400
        result = await client.get("/api/self/projects/queue/planner")
        assert (await result.json())["planner"]["enabled"] is False
