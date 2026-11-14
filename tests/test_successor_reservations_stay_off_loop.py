"""Successor reservations must not block Chat's loop or inspect green git metadata."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_store
from thomas.server import (
    chat_delegation_build_session,
    chat_self_project,
    green_checkout,
    thomas_project,
    thomas_project_successor,
)


def test_successor_scan_only_checks_git_directory_after_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(green_checkout, "green_root", lambda: tmp_path)
    (tmp_path / "work" / "unlinked").mkdir(parents=True)
    (tmp_path / "work" / "linked").mkdir()
    (tmp_path / "git" / "linked").mkdir(parents=True)
    record = forge_code_store.draft_conversation(
        title="Continue", thomas_project={"successor": {"conversation_id": "next"}}
    )
    forge_code_store.write_conversation(tmp_path / "work" / "linked", record)
    monkeypatch.setattr(green_checkout, "find_green", lambda eid: pytest.fail("scan called find_green"))
    monkeypatch.setattr(thomas_project, "project_phase", lambda *args: ("waiting", ""))
    assert thomas_project_successor.successor_greens() == {"linked"}
    (tmp_path / "git" / "linked").rmdir()
    assert thomas_project_successor.successor_greens() == set()


def test_start_sweep_and_workspace_keep_successor_scan_off_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    main_thread = threading.get_ident()
    calls: list[int] = []

    def reserved() -> set[str]:
        calls.append(threading.get_ident())
        assert threading.get_ident() != main_thread, "successor scan ran on the event loop"
        return {"reserved-green"}

    monkeypatch.setattr(chat_self_project, "successor_greens", reserved)
    monkeypatch.setattr(
        chat_delegation_build_session, "prepare_workspace", lambda **kwargs: SimpleNamespace(spare=kwargs["spare"])
    )
    monkeypatch.setattr(thomas_project_successor, "successor_greens", reserved)
    monkeypatch.setattr(chat_self_project, "_sweep_sparing", lambda in_use: list(in_use))
    monkeypatch.setattr(chat_self_project, "_last_sweep", None)
    monkeypatch.setattr(
        chat_self_project,
        "_look_back",
        lambda sid, root: (None, green_checkout.Green("reuse", tmp_path, tmp_path, "base", tmp_path)),
    )
    monkeypatch.setattr(chat_self_project, "build_settings", lambda **kwargs: {"autonomy_level": 4})

    async def start(*args: Any, **kwargs: Any) -> dict[str, str]:
        return {"conversation_id": "next"}

    monkeypatch.setattr(chat_self_project.thomas_project, "start_thomas_project", start)

    async def scenario() -> None:
        await chat_self_project._sweep_now_and_then({})
        _, profile = await chat_self_project._start_project(
            {chat_self_project.APP_LOCAL_PORT: 8899}, tmp_path, {"session_id": "one", "prompt": "continue"}
        )
        assert profile["autonomy_level"] == 4
        plan = await chat_delegation_build_session.prepare_workspace_async(
            app={},
            targets_live_repo=True,
            specialist_id="coding",
            title="test",
            repo_root=tmp_path,
            execution_id="new",
            task_workspace=lambda eid: tmp_path,
        )
        assert "reserved-green" in plan.spare

    asyncio.run(scenario())
    assert len(calls) == 3
