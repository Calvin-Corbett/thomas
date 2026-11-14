"""The notifications row, off: no tool is lent, no notifier is lent, and a server started that way never loads them.

This row has no routes, so a 404 proves nothing. What it lends is two things. The six ``notifications_*`` tools are given
to the runs Thomas builds, and ``thomas.server.chat_delegation_emitter.lend_notifier`` is what a delegated task's ending
notifies through. A fresh server is started with only this row off, then the switch is pressed on and off the way the
Plugins page presses it, and what is lent is read at each of the three.

``thomas.server.rows.notifications`` is the row, and ``thomas.notifications.tools`` and
``thomas.notifications.delegation_hooks`` are what it names. ``tests/test_notifications_row_tools.py`` holds what the
tools do and refuse, and ``tests/test_notifications_row_through_off_and_on.py`` holds a real app.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import ast
from typing import Any

import pytest

from tests.row_off_fixture import start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

ROW = "notifications"
TOOLS = [
    "notifications_clear",
    "notifications_create",
    "notifications_get_store",
    "notifications_get_unread_count",
    "notifications_list",
    "notifications_mark_read",
]
OWN_CODE = (
    "thomas.server.rows.notifications",
    "thomas.notifications.tools",
    "thomas.notifications.delegation_hooks",
)

# Run in the fresh process at each of the three points. It imports nothing the row names.
READING = """\
def reading():
    from thomas.agent.kernel_wiring import contributed_tools
    from thomas.server import chat_delegation_emitter

    return {
        "lent": sorted(tool.name for tool in contributed_tools()),
        "notifier": chat_delegation_emitter._lent_notifier is not None,
    }


"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("notifications-off")
    started, found = start_with_one_row_off(ROW, [], folder, reading=READING)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_nothing_is_lent_and_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert seen["read_off"] == {"lent": [], "notifier": False}
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_lends_the_six_tools_and_the_notifier_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert seen["read_on"] == {"lent": TOOLS, "notifier": True}


def test_it_adds_no_route_on_or_off(seen: dict[str, Any]) -> None:
    assert seen["live_off"] == seen["live_on"]


def test_turned_off_on_a_running_server_both_loans_end_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that what it lent goes and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["read_off_again"] == {"lent": [], "notifier": False}
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


@pytest.mark.parametrize("changed", ["thomas/server/rows/notifications.py", "thomas/notifications/tools.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports the row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_notifications_off_touches_only_its_tools.py" in chosen
    assert "tests/test_notifications_row_tools.py" in chosen
    assert "tests/test_notifications_row_through_off_and_on.py" in chosen


def test_the_emitter_names_no_import_of_the_notifications_code() -> None:
    """Off means no notifier, never an import: the emitter reads what is lent and loads nothing."""
    tree = ast.parse((ROOT / "thomas" / "server" / "chat_delegation_emitter.py").read_text(encoding="utf-8"))
    imported = [
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    ]
    assert [name for name in imported if name and "notifications" in name] == []
