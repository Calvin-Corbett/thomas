"""The schedules row, off: its six routes answer 404, no task starts at its time, and the list stays.

This row starts a thread, so a 404 proves little here. The row can read off with every route gone and ``TaskScheduler``
still firing tasks, and only a test that names the thread can see that.

What runs is a process, not the thread: the thread hands each task to a pool, which starts a chat as a process of its
own. A stop ends the thread and neither waits for nor ends what the pool already has, so the row's words say so.

The word schedule names other things. ``/api/mission/*`` and the job queue the System page lists keep their own jobs in a database, and
``thomas/autonomy/scheduler.py`` works out their next times. ``thomas cron`` shares this row's list, as a process of its
own, so off does not reach it. These tests hold the row's words to all of that, with
``tests/test_scheduled_tasks_through_off_and_on.py``, which keeps what happens to a task and to a row that fails.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did. The id is one that does not
# exist, because a run of a real one starts a chat.
ROUTES = {
    "GET /api/schedules": "GET /api/schedules",
    "POST /api/schedules": "POST /api/schedules",
    "POST /api/schedules/{task_id}/pause": "POST /api/schedules/s1/pause",
    "POST /api/schedules/{task_id}/resume": "POST /api/schedules/s1/resume",
    "POST /api/schedules/{task_id}/run": "POST /api/schedules/s1/run",
    "DELETE /api/schedules/{task_id}": "DELETE /api/schedules/s1",
}
OWN_CODE = (
    "thomas.server.rows.schedules",
    "thomas.server.routes.schedule_routes",
    "thomas.core.schedule_executor",
    "thomas.core.scheduler",
)
LISTED = {*ROUTES, "HEAD /api/schedules"}

ROW = "schedules"
WEB = ROOT / "thomas" / "server" / "web"


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("schedules-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("schedules-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_six_routes_without_a_restart(seen: dict[str, Any]) -> None:
    """The four that name a task answer 404 themselves for an id that does not exist, so only ``live_on`` tells them apart."""
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"]["GET /api/schedules"] == 200
    assert seen["on"]["POST /api/schedules"] == 400  # the handler, asking for a cron and a task


def test_its_thread_runs_only_while_the_row_is_on(seen: dict[str, Any]) -> None:
    assert "TaskScheduler" not in seen["threads_off"]
    assert "TaskScheduler" in seen["threads_on"]
    assert "TaskScheduler" not in seen["threads_off_again"]


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_the_settings_card_is_the_only_page_that_uses_these_routes_and_says_what_the_words_say() -> None:
    """The row's words describe this card. If it changes, or a second page starts calling these routes, they have to too."""
    scripts = {path: path.read_text(encoding="utf-8") for path in WEB.rglob("*.js")}
    fetching = [path.name for path, text in scripts.items() if "/api/schedules" in text]
    card = scripts[WEB / "js" / "settings_parity.js"]

    assert fetching == ["settings_parity.js"]
    assert [path for path in WEB.rglob("*.html") if "/api/schedules" in path.read_text(encoding="utf-8")] == []
    assert '<div class="group-title">Scheduled tasks</div>' in card
    assert "Could not load schedules: " in card
    assert "Not scheduled: " in card
    assert "That did not work: " in card
    # The System page lists the job queue from /api/mission/control, a separate list, as the words say.
    assert "/api/mission/control" in (WEB / "js" / "system_page.js").read_text(encoding="utf-8")


def test_nothing_else_on_the_server_reaches_this_scheduler() -> None:
    """With the row off there is no scheduler, and ``get_scheduler`` would build a stand-in on a file no list reads.

    So this row's words hold only while the server has no other way in. ``thomas cron`` is a process of its own, and it
    installs the real scheduler on the real file first.
    """
    reaching = re.compile(r"\b(?:get_scheduler|install_scheduler|TaskScheduler)\b|\bthomas\.tools\.schedule\b")
    files = {path.relative_to(ROOT).as_posix() for path in (ROOT / "thomas").rglob("*.py")}
    found = {name for name in files if reaching.search((ROOT / name).read_text(encoding="utf-8"))}

    assert found - {"thomas/core/scheduler.py", "thomas/core/schedule_executor.py"} == {
        "thomas/cli/commands/cron.py",
        "thomas/server/routes/schedule_routes.py",
        "thomas/server/rows/schedules.py",
        "thomas/tools/schedule.py",
    }


@pytest.mark.parametrize("changed", ["thomas/server/rows/schedules.py", "thomas/server/routes/schedule_routes.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these three only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_schedules_off_touches_only_its_routes.py" in chosen
    assert "tests/test_scheduled_tasks_through_off_and_on.py" in chosen
    assert "tests/test_schedule_routes.py" in chosen
