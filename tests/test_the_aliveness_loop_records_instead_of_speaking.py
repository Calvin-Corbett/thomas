"""The aliveness loop observes and records; it does not speak or act.

Covers the first slice of plans/thomas/ALIVENESS_DESIGN_2026-08-27.md: the
world model (§2), the drives (§4), the mute log and its scoring rules (§6), and
the dry-run executor that finally gives InitiativeEngine something to call (§8,
build order item 2).
"""
from __future__ import annotations

import time

import pytest

from tests._aliveness_fakes import FakeSensor, isolated_gate, obs
from thomas.core.aliveness import (
    AlivenessLoop,
    build_initiative_executor,
    granted_level,
    is_enabled,
)
from thomas.core.aliveness_drives import CONTACT_HORIZON_S, DEBT_FULL_AT, Drives
from thomas.core.aliveness_log import (
    DEFAULT_OUTCOME,
    OUTCOME_SCORES,
    CandidateMessage,
    MuteLog,
    outcome_score,
)
from thomas.core.aliveness_permissions import (
    SILENT,
)
from thomas.core.aliveness_world import Observation, WorldModel
from thomas.core.initiative import InitiativeEngine

# ---------------------------------------------------------------------------
# World model
# ---------------------------------------------------------------------------


def test_a_first_sweep_is_a_baseline_not_a_pile_of_news() -> None:
    sensor = FakeSensor([obs("branch", "dev"), obs("dirty", "0")])
    world = WorldModel([sensor])

    assert world.sweep() == []
    assert world.sweeps == 1
    assert sorted(world.topics()) == ["fake.topic"]


def test_only_facts_that_actually_changed_are_reported() -> None:
    sensor = FakeSensor([obs("branch", "dev"), obs("dirty", "0")])
    world = WorldModel([sensor])
    world.sweep()

    sensor.readings = [obs("branch", "dev"), obs("dirty", "3")]
    changes = world.sweep()

    assert len(changes) == 1
    assert changes[0].key == "dirty"
    assert changes[0].before == "0"
    assert changes[0].after == "3"
    assert changes[0].is_new is False


def test_a_newly_appearing_fact_is_marked_new() -> None:
    sensor = FakeSensor([obs("branch", "dev")])
    world = WorldModel([sensor])
    world.sweep()

    sensor.readings = [obs("branch", "dev"), obs("upstream", "behind:2")]
    changes = world.sweep()

    assert [c.key for c in changes] == ["upstream"]
    assert changes[0].is_new is True
    assert changes[0].before is None


def test_a_failing_sensor_does_not_take_down_the_sweep() -> None:
    class BrokenSensor:
        @property
        def name(self) -> str:
            return "broken"

        def sample(self) -> list[Observation]:
            raise OSError("sensor is unplugged")

    good = FakeSensor([obs("branch", "dev")])
    world = WorldModel([BrokenSensor(), good])

    world.sweep()
    good.readings = [obs("branch", "main")]
    changes = world.sweep()

    assert [c.after for c in changes] == ["main"]


# ---------------------------------------------------------------------------
# Drives
# ---------------------------------------------------------------------------


def test_silence_alone_never_makes_the_loop_want_to_act() -> None:
    """Contact is support, never cause — design §4."""
    drives = Drives()
    drives.observe_silence(CONTACT_HORIZON_S * 2)

    assert drives.contact.crossed is True
    assert drives.speak_support() is True
    assert drives.wants_action() is False


def test_unfinished_work_raises_debt_until_it_is_full() -> None:
    drives = Drives()

    drives.observe_debt(0)
    assert drives.debt.level == 0.0
    assert drives.debt.crossed is False

    drives.observe_debt(DEBT_FULL_AT)
    assert drives.debt.level == 1.0
    assert drives.debt.crossed is True
    assert drives.wants_action() is True


def test_freshness_rises_with_unobserved_change_and_falls_when_we_look() -> None:
    drives = Drives()
    now = time.time()
    drives.freshness.discharge(now=now)

    drives.observe_world(change_count=5, now=now)
    assert drives.freshness.level > 0.0

    drives.freshness.discharge(now=now)
    assert drives.freshness.level == 0.0


# ---------------------------------------------------------------------------
# The mute log — the scoring rules are the load-bearing part
# ---------------------------------------------------------------------------


def test_an_ignored_message_costs_something_it_is_never_free() -> None:
    """Design §6 rule 1. If silence is free, sending is always worth it."""
    assert DEFAULT_OUTCOME == "ignored"
    assert OUTCOME_SCORES["ignored"] < 0
    assert outcome_score("ignored") < 0
    assert outcome_score("anything-unrecognised") == OUTCOME_SCORES["ignored"]
    assert CandidateMessage(topic="t", text="x").score < 0


def test_being_told_to_stop_is_the_most_expensive_outcome() -> None:
    assert OUTCOME_SCORES["stopped"] == min(OUTCOME_SCORES.values())
    assert OUTCOME_SCORES["acted"] == max(OUTCOME_SCORES.values())


def test_a_recorded_candidate_can_be_read_back(tmp_path) -> None:
    mute_log = MuteLog(tmp_path / "mute.jsonl")
    mute_log.record(CandidateMessage(topic="repo.branch", text="dev moved"))

    entries = mute_log.entries()
    assert len(entries) == 1
    assert entries[0].topic == "repo.branch"
    assert entries[0].outcome == "ignored"


def test_resolving_a_candidate_appends_rather_than_rewrites(tmp_path) -> None:
    path = tmp_path / "mute.jsonl"
    mute_log = MuteLog(path)
    candidate = mute_log.record(CandidateMessage(topic="repo.branch", text="dev moved"))

    mute_log.resolve(candidate.id, "acted")

    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2
    entries = mute_log.entries()
    assert len(entries) == 1
    assert entries[0].outcome == "acted"
    assert entries[0].score > 0


def test_an_unknown_outcome_is_rejected(tmp_path) -> None:
    mute_log = MuteLog(tmp_path / "mute.jsonl")
    candidate = mute_log.record(CandidateMessage(topic="t", text="x"))

    with pytest.raises(ValueError):
        mute_log.resolve(candidate.id, "vibes")


def test_action_rate_is_the_leading_indicator(tmp_path) -> None:
    mute_log = MuteLog(tmp_path / "mute.jsonl")
    assert mute_log.action_rate() is None

    for index in range(4):
        candidate = mute_log.record(CandidateMessage(topic="t", text=f"m{index}"))
        if index < 1:
            mute_log.resolve(candidate.id, "acted")

    assert mute_log.action_rate(last_n=4) == pytest.approx(0.25)
    assert mute_log.net_score(last_n=4) < 0


def _fill(mute_log: MuteLog, topic: str, total: int, acted: int) -> None:
    for index in range(total):
        candidate = mute_log.record(CandidateMessage(topic=topic, text=f"{topic} {index}"))
        if index < acted:
            mute_log.resolve(candidate.id, "acted")


def test_the_mute_log_ranks_topics_as_a_draft_grant_list(tmp_path) -> None:
    """Design §5/§8: the log is what the first permissions are written from."""
    mute_log = MuteLog(tmp_path / "mute.jsonl")

    wanted = mute_log.record(CandidateMessage(topic="ci.status", text="ci red"))
    mute_log.resolve(wanted.id, "acted")
    for index in range(3):
        mute_log.record(CandidateMessage(topic="repo.worktree", text=f"dirty {index}"))

    ranking = mute_log.draft_grant_list()

    assert ranking[0][0] == "ci.status"
    assert ranking[0][2] > 0
    assert ranking[0][3] == 1.0
    assert ranking[-1][0] == "repo.worktree"
    assert ranking[-1][2] < 0
    assert ranking[-1][3] == 0.0


def test_a_rare_topic_you_always_want_outranks_a_chatty_one_you_half_want(tmp_path) -> None:
    """Found by simulating two weeks: ranking by net score gets this backwards.

    Production going down fires three times a fortnight and you act every time
    (net +3). PR review pings fire twenty-two times and you act on fourteen
    (net +6). Net score prefers the chatty one, which is precisely the
    alert-fatigue trade the design warns about, so the ranking sorts on hit rate.
    """
    mute_log = MuteLog(tmp_path / "mute.jsonl")
    _fill(mute_log, "deploy.status", total=3, acted=3)
    _fill(mute_log, "pr.reviews", total=22, acted=14)

    ranking = {row[0]: row for row in mute_log.draft_grant_list()}
    order = [row[0] for row in mute_log.draft_grant_list()]

    # The chatty topic genuinely has the better net score...
    assert ranking["pr.reviews"][2] > ranking["deploy.status"][2]
    # ...and the rare, reliable one is still ranked first.
    assert order[0] == "deploy.status"


def test_one_lucky_hit_does_not_outrank_a_topic_that_has_proven_itself(tmp_path) -> None:
    """Smoothing: 1-for-1 is not better evidence than 20-for-22."""
    mute_log = MuteLog(tmp_path / "mute.jsonl")
    _fill(mute_log, "fluke", total=1, acted=1)
    _fill(mute_log, "proven", total=22, acted=20)

    order = [row[0] for row in mute_log.draft_grant_list()]

    assert order[0] == "proven"


def test_a_noisy_topic_does_not_blind_the_leading_indicator(tmp_path) -> None:
    """Also from the two-week run: the mixture read 0.0 on a run with 45 hits.

    One high-volume topic fills the recency window, so the mixture measures the
    firehose. The per-topic rate is the one that means anything.
    """
    mute_log = MuteLog(tmp_path / "mute.jsonl")
    _fill(mute_log, "ci.status", total=4, acted=4)
    _fill(mute_log, "repo.worktree", total=60, acted=0)

    assert mute_log.action_rate(last_n=20) == 0.0
    assert mute_log.action_rate(last_n=20, topic="ci.status") == 1.0
    assert mute_log.action_rate(last_n=20, topic="never-seen") is None


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def test_an_empty_store_answers_silent_for_everything(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_ALIVENESS_PERMISSIONS", str(tmp_path / "permissions.json"))

    assert granted_level("repo.branch") == SILENT
    assert granted_level("anything at all") == SILENT


def test_the_loop_is_off_unless_it_is_explicitly_turned_on(monkeypatch) -> None:
    monkeypatch.delenv("THOMAS_ALIVENESS_ENABLED", raising=False)
    assert is_enabled() is False

    monkeypatch.setenv("THOMAS_ALIVENESS_ENABLED", "1")
    assert is_enabled() is True


def test_a_tick_records_what_it_would_have_said_and_says_nothing(tmp_path) -> None:
    sensor = FakeSensor([obs("branch", "dev")])
    loop = AlivenessLoop(
        world=WorldModel([sensor]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=isolated_gate(tmp_path),
    )

    first = loop.tick()
    assert first["changes"] == 0
    assert first["recorded"] == 0

    sensor.readings = [obs("branch", "main")]
    second = loop.tick()

    assert second["changes"] == 1
    assert second["recorded"] == 1
    assert second["delivered"] == 0

    entries = loop.mute_log.entries()
    assert entries[0].topic == "fake.topic"
    # Nothing is granted, so the gate holds it and the log keeps the reason.
    assert entries[0].channel == "held"
    assert entries[0].gate["reason"] == "no permission for this topic"
    assert entries[0].outcome == "ignored"


def test_change_is_recorded_even_when_no_drive_is_asking(tmp_path) -> None:
    """The log must be a complete sample, not only what a hot drive noticed."""
    sensor = FakeSensor([obs("branch", "dev")])
    loop = AlivenessLoop(
        world=WorldModel([sensor]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=isolated_gate(tmp_path),
    )
    loop.tick()

    sensor.readings = [obs("branch", "main")]
    summary = loop.tick()

    assert loop.drives.wants_action() is False
    assert summary["recorded"] == 1


def test_one_candidate_per_topic_not_one_per_change(tmp_path) -> None:
    sensor = FakeSensor([obs("a", "1"), obs("b", "1")])
    loop = AlivenessLoop(
        world=WorldModel([sensor]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=isolated_gate(tmp_path),
    )
    loop.tick()

    sensor.readings = [obs("a", "2"), obs("b", "2")]
    summary = loop.tick()

    assert summary["changes"] == 2
    assert summary["recorded"] == 1
    assert len(loop.mute_log.entries()[0].evidence) == 2


# ---------------------------------------------------------------------------
# The InitiativeEngine executor
# ---------------------------------------------------------------------------


def test_the_dry_run_executor_records_the_goal_without_running_it(tmp_path) -> None:
    loop = AlivenessLoop(
        world=WorldModel([FakeSensor([obs("branch", "dev")])]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=isolated_gate(tmp_path),
    )
    executor = build_initiative_executor(loop)

    result = executor("ship the thing")

    assert "mute mode" in result
    entries = loop.mute_log.entries()
    assert any("would have worked on: ship the thing" in e.text for e in entries)


def test_a_dry_run_goal_is_neither_closed_nor_announced() -> None:
    """Mute mode must not mark work done that was never done."""
    engine = InitiativeEngine()
    calls: list[str] = []
    announced: list[str] = []

    engine.start(
        executor_fn=lambda text: calls.append(text) or "recorded",
        notify_fn=announced.append,
        dry_run=True,
    )
    engine.stop()
    engine._run_goal({"id": "goal-1", "text": "do the thing"})

    assert calls == ["do the thing"]
    assert announced == []


def test_the_engine_still_reports_and_closes_when_not_in_dry_run(monkeypatch) -> None:
    engine = InitiativeEngine()
    announced: list[str] = []
    closed: list[str] = []

    class FakePersistence:
        def close_goal(self, goal_id: str) -> None:
            closed.append(goal_id)

    monkeypatch.setattr("thomas.core.persistence.get_persistence", lambda: FakePersistence(), raising=False)
    engine.start(executor_fn=lambda text: "done", notify_fn=announced.append, dry_run=False)
    engine.stop()
    engine._run_goal({"id": "goal-2", "text": "do the thing"})

    assert closed == ["goal-2"]
    assert len(announced) == 1


# ---------------------------------------------------------------------------
# The unattended sweep
# ---------------------------------------------------------------------------


def test_the_loop_sweeps_on_a_timer_with_no_goals_and_no_work(tmp_path) -> None:
    """Without this the log comes back empty after a two-week mute run.

    The InitiativeEngine only fires after 30 minutes of silence *and* an open
    goal. Recording what changed cannot be contingent on there being work.
    """
    sensor = FakeSensor([obs("branch", "dev")])
    loop = AlivenessLoop(
        world=WorldModel([sensor]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=isolated_gate(tmp_path),
    )

    loop.start(interval_s=0.02)
    try:
        deadline = time.time() + 3.0
        while loop.ticks < 1 and time.time() < deadline:
            time.sleep(0.01)
        sensor.readings = [obs("branch", "main")]
        while not loop.mute_log.entries() and time.time() < deadline:
            time.sleep(0.01)
    finally:
        loop.stop()

    assert loop.ticks >= 2
    entries = loop.mute_log.entries()
    assert len(entries) >= 1
    assert "dev -> main" in entries[0].text


def test_stopping_the_sweep_stops_it(tmp_path) -> None:
    loop = AlivenessLoop(
        world=WorldModel([FakeSensor([obs("branch", "dev")])]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=isolated_gate(tmp_path),
    )
    loop.start(interval_s=0.02)
    assert loop.running is True

    loop.stop()

    assert loop.running is False
    settled = loop.ticks
    time.sleep(0.15)
    assert loop.ticks == settled


def test_starting_twice_does_not_start_two_sweeps(tmp_path) -> None:
    loop = AlivenessLoop(
        world=WorldModel([FakeSensor([obs("branch", "dev")])]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=isolated_gate(tmp_path),
    )
    loop.start(interval_s=0.05)
    first = loop._thread
    loop.start(interval_s=0.05)
    try:
        assert loop._thread is first
    finally:
        loop.stop()


def test_the_sweep_stays_off_unless_the_flag_is_set(monkeypatch) -> None:
    from thomas.core.engine_manager import EngineManager

    monkeypatch.delenv("THOMAS_ALIVENESS_ENABLED", raising=False)
    manager = EngineManager()

    assert manager._start_aliveness() is True
    status = manager._status["aliveness"].to_dict()
    assert status["running"] is False
    assert "disabled" in str(status["error"])
