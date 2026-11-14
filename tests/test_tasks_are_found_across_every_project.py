"""Unnamed task reads and updates find records in the project that started them."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.core import task_bot_runtime as rt
from thomas.server import chat_delegation_session as delegation
from thomas.server import tool_extensions


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    launcher = tmp_path / "launcher"
    launcher.mkdir()
    data = tmp_path / "data"
    for key in ("THOMAS_PROFILE", "THOMAS_HOME", "THOMAS_STATE_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data))
    monkeypatch.setenv("THOMAS_USER_DIR", str(data))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(launcher))
    monkeypatch.setattr(rt, "ROOT", launcher)
    monkeypatch.chdir(launcher)
    return launcher, data, tmp_path / "project"


def create(root: Path) -> str:
    return rt.create_execution(session_id="chat-a", summary="Make the report", repo_root=root)["execution_id"]


def test_recent_work_tool_finds_task_from_another_project(stores, monkeypatch):
    from thomas.forge.anvil import forge_code_projects

    create(stores[2])
    found = []
    monkeypatch.setattr(forge_code_projects, "conversation_roots", lambda *_args: [])
    tool_extensions._register_recent_work(SimpleNamespace(register=found.append))
    assert len(found) == 1
    result = asyncio.run(found[0].execute({}))
    assert result.ok
    assert "Make the report" in result.data


def test_cross_project_board_is_memoized_until_a_board_moves(stores, monkeypatch):
    first = create(stores[2])
    original = rt.list_user_executions
    builds = []

    def counted(*, refresh=True):
        builds.append(refresh)
        return original(refresh=refresh)

    monkeypatch.setattr(rt, "list_user_executions", counted)
    monkeypatch.setattr(delegation, "_BOARD_TTL_S", 60.0)
    delegation.reset_board_cache()
    for _ in range(3):
        assert {r["execution_id"] for r in delegation.session_active_delegations("chat-a")} == {first}
    assert len(builds) == 1
    second = create(stores[2])
    assert {r["execution_id"] for r in delegation.session_active_delegations("chat-a")} == {first, second}
    assert len(builds) == 2
    other = stores[1] / "another-project"
    third = create(other)
    assert {r["execution_id"] for r in delegation.session_active_delegations("chat-a")} == {first, second, third}
    assert len(builds) == 3


def test_unnamed_update_writes_summary_in_own_project(stores):
    launcher, _, project = stores
    eid = create(project)
    rt.update_execution(eid, progress_summary="Halfway there")
    rows = rt.list_executions(project, refresh=False)
    assert len(rows) == 1
    assert rows[0]["progress_summary"] == "Halfway there"
    assert not rt.summary_path(launcher).exists()
