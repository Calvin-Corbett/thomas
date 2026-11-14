"""The notifications row on a real app, through off and on: who is given the tools, who is refused, and who is told.

``thomas.server.rows.notifications`` lends the six tools of ``thomas.notifications.tools`` in two places, because two
lists carry them. A worker builds its tools from the lent ones when it starts
(``thomas.server.app_helpers._build_tools``), and Chat uses the registry the app made at its creation, so the row adds
the tools there and takes them out. The notifier that a delegated task's ending
uses is the one ``thomas.server.chat_delegation_emitter`` is lent, and ``thomas.notifications.delegation_hooks`` is what
it saves through. The words of the row are held to these in ``tests/test_the_notifications_row_says_what_is_true.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.row_proof_fixture import choose
from thomas.agent.kernel_wiring import LENT_TOOLS, get_kernel
from thomas.notifications.delegation_hooks import set_active_dispatcher
from thomas.notifications.dispatcher import NotificationDispatcher
from thomas.notifications.store import NotificationStore
from thomas.server import app_core, app_helpers
from thomas.server.app_keys import APP_CONFIG, APP_TOOLS
from thomas.server.chat_delegation_emitter import _DelegationEmitter
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "notifications"
NAME = "notifications_get_store"


class _Bot:
    def to_event_dict(self) -> dict[str, Any]:
        return {}


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def saved(tmp_path: Path) -> NotificationStore:
    """Where the delegation notifier saves, so nothing is written to ``data/notifications.sqlite`` in this checkout."""
    store = NotificationStore(str(tmp_path / "saved.sqlite"))
    set_active_dispatcher(NotificationDispatcher(store=store))
    yield store
    set_active_dispatcher(None)


async def _a_call(registry: Any, path: str) -> Any:
    return await registry.execute(NAME, {"store_path": path})


async def _ending(execution_id: str) -> None:
    async def emit_event(_event: dict[str, Any]) -> None:
        return None

    record = {"execution_id": execution_id, "task_id": "t1", "session_id": "s1", "summary": "A task"}
    await _DelegationEmitter(emit_event).completed(record, specialist_id="sp", bot=_Bot(), text="done")


def _rows_state(app: Any) -> str:
    return fixture.state_of(app[APP_RUNTIME_PLUGINS], ROW)


def test_the_tools_and_the_notifier_follow_the_switch_for_both_who_use_them(
    tmp_path: Path, own_data_dir: Path, saved: NotificationStore
) -> None:
    choose(own_data_dir, on={ROW})
    folder = tmp_path / "memory" / "notifications"

    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            runtime = app[APP_RUNTIME_PLUGINS]
            await fixture.rows_once_started(runtime)
            assert _rows_state(app) == "active"
            config = app[APP_CONFIG]

            # On: Chat has the tools in the registry it keeps, a worker is given them as it starts, both work, and
            # a task's ending is saved.
            assert app[APP_TOOLS].get(NAME) is not None
            first_worker = app_helpers._build_tools(config)
            assert (await _a_call(app[APP_TOOLS], "chat.sqlite")).ok
            assert (await _a_call(first_worker, "worker.sqlite")).ok
            assert (folder / "chat.sqlite").is_file() and (folder / "worker.sqlite").is_file()
            await _ending("e1")
            assert len(saved.list()) == 1

            # Off: nothing is lent, the registry of Chat loses the tools, a worker that began earlier is refused, and
            # a task's ending notifies nobody.
            await runtime.turn_off(ROW)
            assert _rows_state(app) == "off"
            assert app[APP_TOOLS].get(NAME) is None
            assert app_helpers._build_tools(config).get(NAME) is None
            refused = await _a_call(first_worker, "after.sqlite")
            assert not refused.ok and "turned off" in refused.error
            assert not (folder / "after.sqlite").exists()
            assert not (await _a_call(app[APP_TOOLS], "after.sqlite")).ok
            await _ending("e2")
            assert len(saved.list()) == 1

            # On again: new runs have them, the worker that was refused stays refused, and endings are saved again.
            await runtime.turn_on(ROW)
            await fixture.rows_once_started(runtime)
            assert _rows_state(app) == "active"
            assert (await _a_call(app[APP_TOOLS], "chat2.sqlite")).ok
            assert (await _a_call(app_helpers._build_tools(config), "worker2.sqlite")).ok
            assert not (await _a_call(first_worker, "again.sqlite")).ok
            await _ending("e3")
            assert len(saved.list()) == 2

    asyncio.run(scenario())


def test_a_second_app_in_one_process_takes_over_the_loan_an_unstopped_app_left(
    tmp_path: Path, own_data_dir: Path
) -> None:
    """Only a test builds two apps in one process. One name cannot be lent twice, so the later app must not read failed.

    The first is built and never started or stopped, which is how a test leaves one.
    """
    choose(own_data_dir, on={ROW})
    first = app_core.create_app(fixture.config_in(tmp_path / "first"))
    assert _rows_state(first) != "failed", first[APP_RUNTIME_PLUGINS].report()
    second = app_core.create_app(fixture.config_in(tmp_path / "second"))

    states = {number: _rows_state(app) for number, app in (("first", first), ("second", second))}
    assert states["second"] != "failed", second[APP_RUNTIME_PLUGINS].report()
    assert len(get_kernel().root.get(LENT_TOOLS)) == 1
    assert states["first"] != "failed"
    # Built after the first, the second app's registry already held the first's tools, which no longer answer.
    assert asyncio.run(_a_call(second[APP_TOOLS], "second.sqlite")).ok


def test_a_hundred_presses_leave_one_loan_when_on_and_none_when_off(tmp_path: Path, own_data_dir: Path) -> None:
    choose(own_data_dir, on={ROW})

    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            runtime = app[APP_RUNTIME_PLUGINS]
            await fixture.rows_once_started(runtime)
            ledger = get_kernel().root.get(LENT_TOOLS)
            for _ in range(100):
                await runtime.turn_off(ROW)
                assert len(ledger) == 0 and app[APP_TOOLS].get(NAME) is None
                await runtime.turn_on(ROW)
                await fixture.rows_once_started(runtime)
                assert len(ledger) == 1 and app[APP_TOOLS].get(NAME) is not None

    asyncio.run(scenario())
