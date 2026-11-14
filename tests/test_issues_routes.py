"""``GET /api/issues`` and ``POST /api/issues`` on a real app, with the issue ledger pointed at a folder of the test's own.

Proofs of ``thomas.server.rows.issues`` and ``thomas.server.routes.issues_aiohttp``. Neither handler asks the access
guard, so a caller on another machine with no token can read the summary today; the one that records is refused by the
server's own rule for writes, which is tested in ``tests/test_turning_issues_off_touches_only_its_routes.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from thomas.server import app_core, issue_ledger


@pytest.fixture
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The ledger moved to a folder of the test's own. The guard against a test writing the real one reads the same
    root, so it is lifted for this test only, and only after the root has moved."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(issue_ledger, "_REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(issue_ledger, "_is_test_run_writing_to_the_real_ledger", lambda path: False)
    return tmp_path / "repo" / "runtime" / "logs" / "issues.jsonl"


async def _client(tmp_path: Path) -> TestClient:
    client = TestClient(TestServer(app_core.create_app(views.config_in(tmp_path))))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_a_reported_failure_is_written_to_the_ledger_and_comes_back_in_the_summary(
    tmp_path: Path, ledger: Path
) -> None:
    client = await _client(tmp_path)
    try:
        posted = await client.post(
            "/api/issues",
            json={"surface": "chat-ui", "kind": "friction", "message": "retry: it hung", "context": {"session": "s1"}},
        )
        assert posted.status == 200
        assert await posted.json() == {"ok": True}

        written = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        assert [(w["surface"], w["kind"], w["message"], w["context"]) for w in written] == [
            ("chat-ui", "friction", "retry: it hung", {"session": "s1"})
        ]

        summary = await (await client.get("/api/issues")).json()
        assert summary["ok"] is True
        assert summary["total"] == 1
        assert summary["recent"][-1]["message"] == "retry: it hung"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_body_that_is_not_json_is_recorded_with_the_defaults(tmp_path: Path, ledger: Path) -> None:
    client = await _client(tmp_path)
    try:
        posted = await client.post("/api/issues", data=b"not json", headers={"Content-Type": "application/json"})
        assert posted.status == 200
        written = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        assert [(w["surface"], w["kind"], w["message"]) for w in written] == [("ui", "client_error", "")]
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("asked", "hours"),
    [("", 24), ("?hours=6", 6), ("?hours=0", 1), ("?hours=99999", 336), ("?hours=soon", 24)],
)
async def test_the_summary_window_is_kept_between_one_hour_and_two_weeks(
    tmp_path: Path, ledger: Path, monkeypatch: pytest.MonkeyPatch, asked: str, hours: int
) -> None:
    seen: list[int] = []

    def summarize(hours: int = 24, repo_root: Any = None) -> dict[str, Any]:
        seen.append(hours)
        return {"total": 0}

    monkeypatch.setattr(issue_ledger, "summarize", summarize)
    client = await _client(tmp_path)
    try:
        answer = await client.get(f"/api/issues{asked}")
        assert answer.status == 200
        assert seen == [hours]
    finally:
        await client.close()
