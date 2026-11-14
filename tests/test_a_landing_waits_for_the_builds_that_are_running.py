"""A landing waits for the Builds that are running; it never stops them to load itself.

Until 2026-11-10 a landing that changed server Python asked every running Build to stop where it was, restarted the
server, and carried the Builds on afterwards. On 2026-11-10 at 12:58, ten Builds were ten minutes into their work when
one landing arrived: all ten were stopped, the server was gone 214 seconds later, and they were moving again at 13:04.
That day 25 landings began such a restart. You said: "Yes, hold restarts".

Now a landing does nothing to a running Build and holds no new start back. The page says newer code is waiting and
why, with the Restart button for when you want it at once; the restart happens by itself when no Build is running.
"""

from __future__ import annotations

import json

import pytest

from tests.test_background_thomas_reloads_landed_code_when_idle import read, scenario


@pytest.mark.asyncio
async def test_a_running_build_is_not_asked_to_stop_and_new_starts_are_not_held(monkeypatch, tmp_path) -> None:
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    answers["work"] = ("Build run",)

    for at in (0, 600, reload.RUN_YIELD_AFTER_S + 60, reload.BUILD_HOLD_S - 1):
        assert await read(reload, app, at) is None

    assert not reload.drain_signal_path().exists(), "no Build is asked to yield while the landing waits"
    assert not app.get(reload.APP_LANDED_CODE_DRAIN), "and no new start is held back while it waits"
    assert not event.is_set()


@pytest.mark.asyncio
async def test_after_the_longest_wait_the_builds_are_asked_to_stop_after_all(monkeypatch, tmp_path) -> None:
    """With Builds always running the restart would never come, and no fix would ever load."""
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    answers["work"] = ("Build run",)
    await read(reload, app, 0)
    answers["head"] = "newer"  # a second landing while the first waits does not start the wait again
    await read(reload, app, reload.BUILD_HOLD_S - 1)
    assert not reload.drain_signal_path().exists()

    await read(reload, app, reload.BUILD_HOLD_S)

    assert app[reload.APP_LANDED_CODE_DRAIN], "new starts are held"
    assert reload.drain_signal_path().read_text(encoding="utf-8").strip() == "newer", (
        "and the Builds are asked to yield"
    )


@pytest.mark.asyncio
async def test_builds_and_checks_together_still_do_not_stop_the_builds(monkeypatch, tmp_path) -> None:
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    answers["work"] = ("Build run", "check threads")

    await read(reload, app, 0)
    await read(reload, app, reload.RUN_YIELD_AFTER_S + 60)

    assert not reload.drain_signal_path().exists()
    assert not app.get(reload.APP_LANDED_CODE_DRAIN)


@pytest.mark.asyncio
async def test_the_page_is_told_newer_code_is_waiting_and_why(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("THOMAS_STEP_LOG_DIR", str(tmp_path / "metrics"))
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    answers["work"] = ("Build run",)

    await read(reload, app, 0)
    await read(reload, app, 30)

    notice = app[reload.APP_LANDED_CODE_NOTICE]["notice"]
    assert notice["files"] == ["thomas/server/routes/evolve_agent_routes.py"]
    assert "Build" in notice["reason"] and "Restart" in notice["reason"]
    rows = [
        json.loads(line) for path in (tmp_path / "metrics").glob("*.jsonl") for line in path.read_text().splitlines()
    ]
    assert [row["step"] for row in rows].count("reload_held") == 1, "said once for a landing, not every half minute"


@pytest.mark.asyncio
async def test_it_restarts_by_itself_once_no_build_is_running(monkeypatch, tmp_path) -> None:
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    answers["work"] = ("Build run",)
    await read(reload, app, 0)

    answers["work"] = ()
    idle = await read(reload, app, 900)
    assert app[reload.APP_LANDED_CODE_DRAIN], "with nothing running, new starts wait the half minute it takes"
    await read(reload, app, 900 + reload.RELOAD_QUIET_S, idle)

    assert event.is_set()


@pytest.mark.asyncio
async def test_a_build_that_starts_before_the_restart_puts_it_off_again(monkeypatch, tmp_path) -> None:
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    idle = await read(reload, app, 0)
    assert app[reload.APP_LANDED_CODE_DRAIN]

    answers["work"] = ("Build run",)
    await read(reload, app, 10, idle)

    assert not app.get(reload.APP_LANDED_CODE_DRAIN), "the hold on new starts is lifted again"
    assert not reload.drain_signal_path().exists() and not event.is_set()
