"""What the words of ``thomas.server.rows.notifications`` say, a sentence at a time, held to the real code.

The row has no page, so nobody sees it but on the Plugins page, and a person reads its words there. Each test below is a
sentence of ``thomas/server/rows/default.toml`` that the proof of a row cannot see: that no page shows these
notifications, which tools are meant to work and which do, where the record of a task's ending is saved and when, that
a call already running is not cut off, and that the command line never had the tools back.

``thomas.notifications.tools`` and ``thomas.notifications.delegation_hooks`` are what the row names.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from tests.row_proof_fixture import ROOT, ROWS
from thomas.agent.kernel_wiring import contribute_tools, contributed_tools, default_kernel, set_kernel
from thomas.core.config import AppConfig
from thomas.notifications import delegation_hooks
from thomas.notifications.delegation_hooks import emit_delegation_notification
from thomas.server.chat_delegation_emitter import _DelegationEmitter, lend_notifier
from thomas.tools.base import Tool, ToolResult

WEB = ROOT / "thomas" / "server" / "web"
NAMES = (
    "notifications_clear",
    "notifications_create",
    "notifications_get_store",
    "notifications_get_unread_count",
    "notifications_list",
    "notifications_mark_read",
)


class _Bot:
    def to_event_dict(self) -> dict[str, Any]:
        return {}


@pytest.fixture
def where_it_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder to start from, with no dispatcher built yet, so the first record makes the default file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("THOMAS_NOTIFICATIONS_DB", raising=False)
    monkeypatch.setattr(delegation_hooks, "_active_dispatcher", None)
    monkeypatch.setattr(delegation_hooks, "_fallback_dispatcher", None)
    return tmp_path


def _the_row() -> dict[str, str]:
    return next(dict(row.config["words"]) for row in ROWS if row.id == "notifications")


def _record(execution_id: str) -> dict[str, Any]:
    return {"execution_id": execution_id, "task_id": "t1", "session_id": "s1", "summary": "A task"}


async def _ending(kind: str, execution_id: str, events: list[dict[str, Any]]) -> None:
    async def emit_event(event: dict[str, Any]) -> None:
        events.append(event)

    emitter = _DelegationEmitter(emit_event)
    if kind == "approval_needed":
        await emitter.approval_needed(_record(execution_id), specialist_id="sp", bot=_Bot(), text="wait")
    elif kind == "started":
        await emitter.started(_record(execution_id), specialist_id="sp", bot=_Bot())
    elif kind == "progress":
        await emitter.progress(_record(execution_id), specialist_id="sp", bot=_Bot(), text="half")
    else:
        await getattr(emitter, kind)(_record(execution_id), specialist_id="sp", bot=_Bot(), text="x")


def test_the_words_name_the_six_tools_and_say_only_three_work() -> None:
    about = _the_row()["about"]
    for phrase in (
        "open a store",
        "create a notification",
        "list them",
        "mark them read",
        "count the unread ones",
        "clear them",
        "Today only three of the six work",
    ):
        assert phrase in about, phrase
    assert len(NAMES) == 6


def test_a_task_finishing_failing_or_waiting_saves_a_record_and_a_start_or_progress_saves_none(
    where_it_saves: Path,
) -> None:
    """The three events the words name. Each is saved in ``data/notifications.sqlite`` beside where Thomas started."""
    undo = lend_notifier(emit_delegation_notification)
    events: list[dict[str, Any]] = []
    try:
        for number, kind in enumerate(("started", "progress", "completed", "failed", "approval_needed")):
            asyncio.run(_ending(kind, f"e{number}", events))
    finally:
        undo()
    saved = where_it_saves / "data" / "notifications.sqlite"
    assert saved.is_file()
    stored = delegation_hooks.get_dispatcher().store.list()
    assert sorted(row.type for row in stored) == ["approval_needed", "blocked", "completion"]
    assert [event["type"] for event in events if event["type"].startswith("delegation_")][:2] == [
        "delegation_started",
        "delegation_progress",
    ]


def test_another_place_for_the_file_is_honoured(where_it_saves: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    elsewhere = where_it_saves / "elsewhere" / "n.sqlite"
    monkeypatch.setenv("THOMAS_NOTIFICATIONS_DB", str(elsewhere))
    undo = lend_notifier(emit_delegation_notification)
    try:
        asyncio.run(_ending("completed", "e1", []))
    finally:
        undo()
    assert elsewhere.is_file()
    assert not (where_it_saves / "data" / "notifications.sqlite").exists()


def test_the_record_makes_no_pop_up_and_no_push(where_it_saves: Path) -> None:
    dispatcher = delegation_hooks.get_dispatcher()
    assert dispatcher.enable_desktop_toasts is False
    assert dispatcher.vapid is None


def test_with_nothing_lent_an_ending_still_reaches_the_chat_and_saves_nothing(where_it_saves: Path) -> None:
    events: list[dict[str, Any]] = []
    asyncio.run(_ending("completed", "e1", events))
    asyncio.run(_ending("approval_needed", "e2", events))
    assert [event["type"] for event in events if event["type"] == "delegation_completed"] == ["delegation_completed"]
    assert not (where_it_saves / "data").exists()


def test_a_notifier_given_to_an_emitter_is_used_whatever_is_lent() -> None:
    seen: list[str] = []
    undo = lend_notifier(lambda event, record, *, text="": seen.append(f"lent {event}"))

    async def emit_event(_event: dict[str, Any]) -> None:
        return None

    try:
        emitter = _DelegationEmitter(emit_event, notifier=lambda event, record, *, text="": seen.append(f"own {event}"))
        asyncio.run(emitter.approval_needed(_record("e1"), specialist_id="sp", bot=_Bot(), text=""))
    finally:
        undo()
    assert seen == ["own approval_needed"]


def test_taking_back_a_notifier_does_not_take_back_a_newer_one() -> None:
    seen: list[str] = []
    old = lend_notifier(lambda event, record, *, text="": seen.append("old"))
    new = lend_notifier(lambda event, record, *, text="": seen.append("new"))
    try:
        old()
        asyncio.run(_ending("approval_needed", "e1", []))
        assert seen == ["new"]
    finally:
        new()
    asyncio.run(_ending("approval_needed", "e2", []))
    assert seen == ["new"]


class _Slow(Tool):
    name = "slow.tool"
    description = "Waits to be let go"
    parameters = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        await self.release.wait()
        return ToolResult(ok=True, data="finished")


def test_a_call_already_running_is_not_cut_off_when_the_loan_ends() -> None:
    """The row's words say so, and its loan is the kernel's: a lent tool refuses a new call and leaves a running one."""
    kernel = default_kernel()
    set_kernel(kernel)
    try:

        async def scenario() -> tuple[ToolResult, ToolResult]:
            tool = _Slow()
            end = contribute_tools(kernel.root, [tool], owner="notifications")
            (lent,) = contributed_tools()
            running = asyncio.ensure_future(lent.safe_execute({}))
            await asyncio.sleep(0.05)
            end()
            refused = await lent.safe_execute({})
            tool.release.set()
            return await running, refused

        finished, refused = asyncio.run(scenario())
    finally:
        set_kernel(None)
    assert finished.ok and finished.data == "finished"
    assert not refused.ok and "turned off" in refused.error


def test_the_command_line_has_none_of_the_six_tools_in_either_state(tmp_path: Path) -> None:
    from thomas.cli._commands_base import _build_tools

    config = AppConfig()
    config.tools.sandbox_root = str(tmp_path)
    config.tools.allow_shell = False
    assert [name for name in NAMES if _build_tools(config).get(name) is not None] == []


def test_no_page_and_no_script_in_thomas_reads_or_shows_these_notifications() -> None:
    """Words: no page in Thomas shows any of this. A page that did would have to ask for it by one of these names."""
    asking = re.compile(r"notifications_|api/notifications|notifications\.sqlite|/notifications/stream", re.IGNORECASE)
    found = [
        path.relative_to(ROOT).as_posix()
        for path in sorted(WEB.rglob("*"))
        if path.suffix in {".js", ".html", ".css", ".json"} and asking.search(path.read_text(encoding="utf-8"))
    ]
    assert found == []


def test_nothing_else_that_runs_in_the_server_builds_these_tools_or_starts_the_api() -> None:
    """The words and the row hold only while the server has no other way in to them."""
    reaching = re.compile(r"register_notifications_tools|build_notifications_tools|init_notifications\b")
    found = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "thomas").rglob("*.py")
        if "notifications" not in path.relative_to(ROOT).parts and reaching.search(path.read_text(encoding="utf-8"))
    }
    assert found == {"thomas/server/rows/notifications.py"}
