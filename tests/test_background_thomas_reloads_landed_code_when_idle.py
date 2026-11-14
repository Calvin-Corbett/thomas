"""Caged and tray-started servers leave on landed Python only after in-memory work is safe."""

import asyncio
import json
import logging
import threading
from types import SimpleNamespace

import pytest
from scripts.cage.cage_keepalive import SERVER_CODE

from thomas.server import self_change_status
from thomas.server.app_keys import APP_RESTART_REQUESTED, APP_RUNTIME_GUARD_STATE, APP_SHUTDOWN_EVENT
from thomas.server.precard import workers


def scenario(monkeypatch, tmp_path, *, changed="thomas/server/routes/evolve_agent_routes.py"):
    from thomas.server import landed_code_reload as reload

    event = asyncio.Event()
    app = {
        APP_SHUTDOWN_EVENT: event,
        APP_RESTART_REQUESTED: False,
        APP_RUNTIME_GUARD_STATE: {"boot": {"source": {"git_head": "old"}}},
    }
    answers = {"head": "new", "changed": changed, "dirty": "", "work": (), "desk": True, "stopping": False}
    monkeypatch.setattr(reload.owner_desk, "enabled", lambda: answers["desk"])
    monkeypatch.setattr(reload, "active_work", lambda _app: tuple(answers["work"]))
    monkeypatch.setattr(reload.workers, "generation_stopping", lambda: answers["stopping"])
    monkeypatch.setattr(reload, "resolve_thomas_data_dir", lambda: tmp_path)
    monkeypatch.setattr(reload.cage_shell, "cage_root", lambda: tmp_path)

    def git(args, **_kwargs):
        if "rev-parse" in args:
            text = answers["head"]
        elif "--name-only" in args and "HEAD" in args and "old" not in args:
            text = answers["dirty"]
        else:
            text = answers["changed"]
        return SimpleNamespace(ok=True, output=lambda: text)

    async def off_loop(_label, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(reload, "run_git", git)
    # HEAD is read from .git's files first (462c49b7c); this scenario's HEAD is the fake git's answer.
    monkeypatch.setattr(reload, "head_sha", lambda _root: None)
    monkeypatch.setattr(reload, "off_loop", off_loop)
    return reload, app, event, answers


async def read(reload, app, at, idle=None):
    return await reload.check_once(app, idle, at)


def test_only_caged_or_tray_port_starts_watcher(monkeypatch):
    from thomas.server import landed_code_reload as reload

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(reload.owner_desk, "enabled", lambda: True)
    assert reload.loop_enabled(8898)
    assert not reload.loop_enabled(8899)
    monkeypatch.setenv(reload.TRAY_PORT_ENV, "8899")
    assert reload.loop_enabled(8899)
    assert not reload.loop_enabled(8900)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test")
    assert not reload.loop_enabled(8898)
    assert not reload.loop_enabled(8899)
    monkeypatch.setenv("THOMAS_LANDED_CODE_RELOAD_LOOP", "1")
    assert reload.loop_enabled(8898)
    assert reload.loop_enabled(8899)
    monkeypatch.setattr(reload.owner_desk, "enabled", lambda: False)
    assert not reload.loop_enabled(8898)
    assert reload.loop_enabled(8899)


@pytest.mark.asyncio
async def test_tray_reload_drains_work_without_owner_desk_and_uses_own_marker(monkeypatch, tmp_path):
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    monkeypatch.setenv(reload.TRAY_PORT_ENV, "8899")
    answers["desk"] = False
    (tmp_path / "caged_server.off").touch()
    idle = await read(reload, app, 0)
    await read(reload, app, reload.RELOAD_QUIET_S, idle)
    assert event.is_set() and app[APP_RESTART_REQUESTED] is False
    assert (tmp_path / "landed-code-reload-head-tray-8899").read_text(encoding="utf-8").strip() == "new"
    assert not (tmp_path / reload.MARKER_NAME).exists()


def test_tray_watch_only_runs_on_the_childs_own_port(monkeypatch):
    from thomas.server import landed_code_reload as reload

    monkeypatch.setenv(reload.TRAY_PORT_ENV, "8899")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(reload.owner_desk, "enabled", lambda: False)
    assert reload.loop_enabled(8899)
    assert not reload.loop_enabled(8898)
    assert not reload.loop_enabled(8900)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test")
    assert not reload.loop_enabled(8899)


def test_server_code_paths_match_keepalive():
    from thomas.server.landed_code_reload import SERVER_CODE_PATHS

    assert SERVER_CODE_PATHS == SERVER_CODE


@pytest.mark.asyncio
async def test_landed_python_exits_once_with_reason_and_without_restart(monkeypatch, tmp_path, caplog):
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    with caplog.at_level(logging.WARNING):
        idle = await read(reload, app, 0)
        await read(reload, app, reload.RELOAD_QUIET_S, idle)
    assert event.is_set() and app[APP_RESTART_REQUESTED] is False
    assert "old" in caplog.text and "new" in caplog.text
    assert answers["changed"] in caplog.text and "no work" in caplog.text
    event.clear()
    await read(reload, app, reload.RELOAD_QUIET_S * 2, idle)
    assert not event.is_set()
    answers["head"] = "newer"
    await read(reload, app, reload.RELOAD_QUIET_S * 3, idle)
    assert event.is_set()


@pytest.mark.asyncio
async def test_non_server_changes_or_missing_heads_do_not_exit(monkeypatch, tmp_path):
    reload, app, event, answers = scenario(monkeypatch, tmp_path, changed="docs/a.md\ntests/test_a.py")
    await read(reload, app, 500, 0)
    assert not event.is_set()
    answers["changed"] = "thomas/server/routes/evolve_agent_routes.py"
    answers["head"] = ""
    await read(reload, app, 500, 0)
    assert not event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("work", ["Build run", "check threads", "restart pending", "promoter inbox"])
async def test_each_kind_of_work_waits_and_quiet_starts_after_it(monkeypatch, tmp_path, work):
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    answers["work"] = (work,)
    idle = await read(reload, app, 0)
    idle = await read(reload, app, 500, idle)
    assert idle is None and not event.is_set()
    answers["work"] = ()
    idle = await read(reload, app, 501, idle)
    await read(reload, app, 501 + reload.RELOAD_QUIET_S, idle)
    assert event.is_set()


@pytest.mark.asyncio
async def test_wait_log_only_when_landed_server_code_needs_reload(monkeypatch, tmp_path, caplog):
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    answers["head"] = "old"
    answers["work"] = ("Build run",)
    monkeypatch.setattr(reload, "RELOAD_CHECK_S", 0.005)
    task = asyncio.create_task(reload.watch(app))
    try:
        with caplog.at_level(logging.INFO, logger=reload.__name__):
            await asyncio.sleep(0.03)
            assert "landed code reload waits" not in caplog.text
            answers["head"] = "new"
            await asyncio.sleep(0.03)
            assert caplog.text.count("landed code reload waits for Build run") == 1
            answers["work"] = ("check threads",)
            await asyncio.sleep(0.03)
            assert caplog.text.count("landed code reload waits for check threads") == 1
            answers["head"] = "old"
            answers["work"] = ("Build run",)
            await asyncio.sleep(0.03)
            assert caplog.text.count("landed code reload waits") == 2
    finally:
        event.set()
        await task


@pytest.mark.asyncio
async def test_off_switch_during_drain_reopens_code_admission(monkeypatch, tmp_path):
    reload, app, _event, _answers = scenario(monkeypatch, tmp_path)
    from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN

    app[APP_LANDED_CODE_DRAIN] = {"head": "new-head"}
    signal = reload.drain_signal_path()
    signal.parent.mkdir(parents=True, exist_ok=True)
    signal.write_text("drain", encoding="utf-8")
    (tmp_path / "caged_server.off").write_text("off", encoding="utf-8")

    await reload.check_once(app, None, 10.0)

    assert APP_LANDED_CODE_DRAIN not in app
    assert not signal.exists()


@pytest.mark.asyncio
async def test_shutdown_during_landed_probe_clears_drain(monkeypatch, tmp_path):
    reload, app, event, _answers = scenario(monkeypatch, tmp_path)
    app[reload.APP_LANDED_CODE_DRAIN] = {"head": "new-head"}
    signal = reload.drain_signal_path()
    signal.parent.mkdir(parents=True, exist_ok=True)
    signal.write_text("drain", encoding="utf-8")

    async def stopping_probe(_app):
        event.set()
        return "new-head", "old-head", ["thomas/server/landed_code_reload.py"]

    monkeypatch.setattr(reload, "_landed_change", stopping_probe)
    await reload.watch(app)

    assert reload.APP_LANDED_CODE_DRAIN not in app
    assert not signal.exists()


@pytest.mark.asyncio
async def test_work_between_quiet_reads_drains_until_safe(monkeypatch, tmp_path):
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    monkeypatch.setattr(reload, "BUILD_HOLD_S", 0.0)  # once landed code has waited its longest for the Builds
    idle = await read(reload, app, 0)
    answers["work"] = ("Build run",)
    idle = await read(reload, app, 120, idle)
    assert app[reload.APP_LANDED_CODE_DRAIN]
    answers["work"] = ()
    idle = await read(reload, app, 180, idle)
    await read(reload, app, 210, idle)
    assert event.is_set()


@pytest.mark.asyncio
async def test_off_switch_dirty_server_and_owner_desk_disabled(monkeypatch, tmp_path):
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    off = tmp_path / "caged_server.off"
    off.touch()
    idle = await read(reload, app, 500, 0)
    assert idle is None and not event.is_set()
    off.unlink()
    # An uncommitted server file holds the restart only while Python cannot read it (2026-11-09).
    monkeypatch.setattr(reload, "REPO_ROOT", tmp_path)
    half = tmp_path / "thomas/server/app_lifecycle.py"
    half.parent.mkdir(parents=True, exist_ok=True)
    half.write_text("def unfinished(:", encoding="utf-8")
    answers["dirty"] = "thomas/server/app_lifecycle.py"
    await read(reload, app, 500, 0)
    assert not event.is_set()
    assert app[reload.APP_LANDED_CODE_NOTICE]["notice"]["broken"] == ["thomas/server/app_lifecycle.py"]
    answers["dirty"] = ""
    answers["desk"] = False
    await read(reload, app, 500, 0)
    assert not event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("stopping", [False, True])
async def test_other_stop_or_generation_stop_is_not_overridden(monkeypatch, tmp_path, caplog, stopping):
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    answers["stopping"] = stopping
    if not stopping:
        event.set()
    app[APP_RESTART_REQUESTED] = True
    with caplog.at_level(logging.WARNING):
        await read(reload, app, 500, 0)
    assert app[APP_RESTART_REQUESTED] is True
    assert "no work" not in caplog.text


@pytest.mark.asyncio
async def test_waiting_hand_in_survives_until_wait_ends(monkeypatch, tmp_path):
    reload, app, event, _answers = scenario(monkeypatch, tmp_path)
    monkeypatch.setattr(
        reload,
        "active_work",
        lambda _app: tuple(name for name, count in self_change_status.active_hand_ins().items() if count),
    )
    monkeypatch.setitem(self_change_status._WAITS, "test-reload", self_change_status.HandInWait("sid", [], 0))
    try:
        idle = await read(reload, app, 0)
        await read(reload, app, 500, idle)
        assert not event.is_set()
        self_change_status._WAITS["test-reload"].state = "handed in"
        idle = await read(reload, app, 501)
        await read(reload, app, 501 + reload.RELOAD_QUIET_S, idle)
        assert event.is_set()
    finally:
        self_change_status._WAITS.pop("test-reload", None)


@pytest.mark.asyncio
async def test_git_failure_does_not_retire_server(monkeypatch, tmp_path):
    reload, app, event, _answers = scenario(monkeypatch, tmp_path)
    monkeypatch.setattr(reload, "run_git", lambda *_args, **_kwargs: SimpleNamespace(ok=False))
    await read(reload, app, 500, 0)
    assert not event.is_set()


@pytest.mark.asyncio
async def test_check_threads_count_queued_or_running_calls():
    entered, release = threading.Event(), threading.Event()

    def check():
        entered.set()
        assert release.wait(4)

    task = asyncio.create_task(workers.off_the_loop(check))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        assert workers.active_calls() >= 1
    finally:
        release.set()
        await task
    assert workers.active_calls() == 0


@pytest.mark.asyncio
async def test_real_work_reads_include_all_in_memory_and_external_waits(monkeypatch, tmp_path):
    from thomas.server import landed_code_reload as reload

    app = {}
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "submission").mkdir()
    monkeypatch.setattr(reload, "active_code_runs", lambda _app: {"run": "active"})
    monkeypatch.setattr(reload.workers, "active_calls", lambda: 1)
    monkeypatch.setattr(reload.autopilot_restart, "report", lambda: {"pending": ["run"]})
    monkeypatch.setattr(reload.green_handoff, "inbox_dir", lambda: inbox)
    monkeypatch.setattr(
        reload.self_change_status, "active_hand_ins", lambda: {"claims": 1, "background": 1, "waits": 1}
    )
    assert set(reload.active_work(app)) == {
        "Build run",
        "check threads",
        "restart pending",
        "promoter inbox",
        "claims",
        "background",
        "waits",
    }


@pytest.mark.asyncio
async def test_in_memory_claim_and_background_task_are_counted(monkeypatch):
    claim = "test-reload-claim"
    task = asyncio.create_task(asyncio.sleep(0))
    monkeypatch.setattr(self_change_status, "_BACKGROUND", {task})
    assert self_change_status.claim(claim)
    try:
        assert self_change_status.active_hand_ins()["claims"] >= 1
        assert self_change_status.active_hand_ins()["background"] >= 1
        await task
        assert self_change_status.active_hand_ins()["background"] >= 1
    finally:
        self_change_status.release(claim)


@pytest.mark.asyncio
async def test_teams_keep_working_until_only_their_runs_hold_the_reload(monkeypatch, tmp_path):
    """2026-10-24: every team yielded at 09:00 and sat idle until the checks let the server go at 09:33."""
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    monkeypatch.setattr(reload, "BUILD_HOLD_S", 0.0)  # once landed code has waited its longest for the Builds
    answers["work"] = ("Build run", "check threads")
    await read(reload, app, 0)
    assert not app.get(reload.APP_LANDED_CODE_DRAIN), "new runs may start while the check finishes (2026-11-13)"
    assert not reload.drain_signal_path().exists(), "running teams keep working while the check finishes"
    answers["work"] = ("Build run",)
    await read(reload, app, 600)
    assert app[reload.APP_LANDED_CODE_DRAIN], "no new run starts once the Builds are asked to yield"
    assert reload.drain_signal_path().read_text(encoding="utf-8").strip() == "new"
    answers["work"] = ()
    idle = await read(reload, app, 700)
    await read(reload, app, 700 + reload.RELOAD_QUIET_S, idle)
    assert event.is_set()


@pytest.mark.asyncio
async def test_teams_yield_after_the_cap_while_other_work_goes_on_but_never_for_a_check(monkeypatch, tmp_path):
    import json

    monkeypatch.setenv("THOMAS_STEP_LOG_DIR", str(tmp_path / "metrics"))
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    monkeypatch.setattr(reload, "BUILD_HOLD_S", 0.0)  # once landed code has waited its longest for the Builds
    answers["work"] = ("Build run", "check threads")
    for at in range(0, int(reload.RUN_YIELD_AFTER_S * 3) + 1, 600):  # looked at every ten minutes, as watch() does
        await read(reload, app, at)
        assert not reload.drain_signal_path().exists(), "a running check never makes the Builds yield (2026-11-13)"
    answers["work"] = ("Build run", "promoter inbox")
    await read(reload, app, reload.RUN_YIELD_AFTER_S * 3 + 30)
    assert reload.drain_signal_path().exists() and not event.is_set()
    rows = [
        json.loads(line) for path in (tmp_path / "metrics").glob("*.jsonl") for line in path.read_text().splitlines()
    ]
    [yielded] = [row for row in rows if row["step"] == "reload_yield"]
    assert yielded["seconds"] == reload.RUN_YIELD_AFTER_S * 3 + 30 and yielded["held_by"] == "promoter inbox"


@pytest.mark.asyncio
async def test_a_second_landing_or_a_brief_clear_does_not_restart_the_cap(monkeypatch, tmp_path):
    """Teams hand in during the drain, so a second landing mid-drain is usual; a git read can time out on a busy PC."""
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    monkeypatch.setattr(reload, "BUILD_HOLD_S", 0.0)  # once landed code has waited its longest for the Builds
    answers["work"] = ("Build run", "promoter inbox")  # the cap is for waits that are not checks
    await read(reload, app, 0)
    answers["head"] = ""  # git did not answer: the drain clears for a moment
    await read(reload, app, 300)
    answers["head"] = "newer"  # and another change landed meanwhile
    await read(reload, app, 900)
    await read(reload, app, reload.RUN_YIELD_AFTER_S - 1)
    assert not reload.drain_signal_path().exists()
    await read(reload, app, reload.RUN_YIELD_AFTER_S)
    assert reload.drain_signal_path().read_text(encoding="utf-8").strip() == "newer", "counted from the first landing"


@pytest.mark.asyncio
async def test_a_drain_long_after_the_last_one_starts_its_own_clock(monkeypatch, tmp_path):
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    monkeypatch.setattr(reload, "BUILD_HOLD_S", 0.0)  # once landed code has waited its longest for the Builds
    answers["work"] = ("Build run", "promoter inbox")  # the cap is for waits that are not checks
    await read(reload, app, 0)
    answers["head"] = ""
    await read(reload, app, 100)
    answers["head"] = "much-later"
    later = 100 + reload.RUN_YIELD_AFTER_S + 1
    await read(reload, app, later)
    await read(reload, app, later + reload.RUN_YIELD_AFTER_S - 1)
    assert not reload.drain_signal_path().exists()


@pytest.mark.parametrize(
    ("cards", "holds"),
    [
        ([{"state": "asking"}], False),  # waiting on you: lands nothing until you answer
        ([{"state": "approved"}, {"state": "asking"}], False),  # the next card is still asking
        ([{"state": "approved"}], True),  # every card answered: it may be landing now
        (None, True),  # no card record yet: the promoter has only just taken it
    ],
)
def test_a_card_waiting_on_you_does_not_hold_the_reload(monkeypatch, tmp_path, cards, holds):
    """On 2026-10-26 one card waiting for you held a reload half an hour, with every yielded team stopped."""
    from thomas.server import landed_code_reload as reload

    inbox, outbox = tmp_path / "inbox", tmp_path / "outbox"
    (inbox / "self-thomas-abc").mkdir(parents=True)
    outbox.mkdir()
    if cards is not None:
        (outbox / "self-thomas-abc.pending.json").write_text(json.dumps({"cards": cards}), encoding="utf-8")
    monkeypatch.setattr(reload, "active_code_runs", lambda _app: {})
    monkeypatch.setattr(reload.workers, "active_calls", lambda: 0)
    monkeypatch.setattr(reload.autopilot_restart, "report", lambda: {"pending": []})
    monkeypatch.setattr(reload.green_handoff, "inbox_dir", lambda: inbox)
    monkeypatch.setattr(reload.self_change_status, "outbox_dir", lambda: outbox)
    monkeypatch.setattr(reload.self_change_status, "active_hand_ins", lambda: {})

    assert ("promoter inbox" in reload.active_work({})) is holds
