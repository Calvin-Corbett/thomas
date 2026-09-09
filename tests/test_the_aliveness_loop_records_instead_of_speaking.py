"""The aliveness loop observes and records; it does not speak or act.

Covers the first slice of plans/thomas/ALIVENESS_DESIGN_2026-08-27.md: the
world model (§2), the drives (§4), the mute log and its scoring rules (§6), and
the dry-run executor that finally gives InitiativeEngine something to call (§8,
build order item 2).
"""

from __future__ import annotations

import time

import pytest

from thomas.core.aliveness import (
    AlivenessLoop,
    build_initiative_executor,
    granted_level,
    is_enabled,
)
from thomas.core.aliveness_drives import CONTACT_HORIZON_S, DEBT_FULL_AT, Drives
from thomas.core.aliveness_gate import PushBudget, SpeakGate
from thomas.core.aliveness_log import (
    DEFAULT_OUTCOME,
    OUTCOME_SCORES,
    CandidateMessage,
    MuteLog,
    outcome_score,
)
from thomas.core.aliveness_permissions import (
    BRIEF_ALWAYS,
    BRIEF_IF_ROOM,
    INTERRUPT,
    NOTIFY,
    SILENT,
    PermissionStore,
)
from thomas.core.aliveness_world import Observation, WorldModel
from thomas.core.initiative import InitiativeEngine


class FakeSensor:
    """A sensor whose readings the test controls."""

    def __init__(self, readings: list[Observation] | None = None) -> None:
        self.readings = readings or []

    @property
    def name(self) -> str:
        return "fake"

    def sample(self) -> list[Observation]:
        return list(self.readings)


def obs(key: str, value: str, topic: str = "fake.topic") -> Observation:
    return Observation(topic=topic, key=key, value=value, at=time.time())


def isolated_gate(tmp_path, budget: PushBudget | None = None) -> SpeakGate:
    """A gate whose permission store is a throwaway file.

    Tests must never touch the real store: it is the user's standing contract
    about what may interrupt them.
    """
    return SpeakGate(
        permissions=PermissionStore(tmp_path / "permissions.json"),
        budget=budget or PushBudget(),
    )


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


# ---------------------------------------------------------------------------
# Robustness — every case below is a bug a simulated run actually hit
# ---------------------------------------------------------------------------


class ThrowingSensor:
    def __init__(self, exc: BaseException, name: str = "throwing") -> None:
        self.exc = exc
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def sample(self) -> list[Observation]:
        raise self.exc


@pytest.mark.parametrize(
    "exc",
    [
        OSError("io"),
        ValueError("bad"),
        KeyError("k"),
        TypeError("t"),
        RuntimeError("unexpected"),
        AttributeError("attr"),
        ZeroDivisionError("div"),
        UnicodeDecodeError("utf-8", b"", 0, 1, "boom"),
    ],
)
def test_no_sensor_exception_can_stop_the_sweep(exc: BaseException) -> None:
    """Sensors are the extension point, so one of them must not kill the loop."""
    good = FakeSensor([obs("branch", "dev")])
    world = WorldModel([ThrowingSensor(exc), good])

    world.sweep()

    assert "fake.topic" in world.topics()


def test_a_sensor_that_always_fails_is_quarantined() -> None:
    from thomas.core.aliveness_world import SENSOR_FAILURE_LIMIT

    world = WorldModel([ThrowingSensor(RuntimeError("always"), name="bad")])

    for _ in range(SENSOR_FAILURE_LIMIT):
        world.sweep()

    assert "bad" in world.quarantined


def test_an_intermittent_sensor_is_not_quarantined() -> None:
    """Failing sometimes is not the same as being broken."""

    class Flaky:
        def __init__(self) -> None:
            self.calls = 0

        @property
        def name(self) -> str:
            return "flaky"

        def sample(self) -> list[Observation]:
            self.calls += 1
            if self.calls % 2:
                raise RuntimeError("intermittent")
            return [obs("branch", str(self.calls))]

    world = WorldModel([Flaky()])
    for _ in range(20):
        world.sweep()

    assert world.quarantined == set()


def test_a_sensor_returning_junk_cannot_poison_the_world() -> None:
    class Junk:
        @property
        def name(self) -> str:
            return "junk"

        def sample(self):
            return [None, "a string", 42, {"not": "an observation"}, obs("k", "v", "ok.topic")]

    class NotEvenASequence:
        @property
        def name(self) -> str:
            return "worse"

        def sample(self):
            return "definitely not a list"

    world = WorldModel([NotEvenASequence(), Junk()])
    world.sweep()

    assert world.topics() == ["ok.topic"]


def test_a_corrupt_log_still_yields_its_good_entries(tmp_path) -> None:
    """Partial writes and hand-edits must not make the log unreadable."""
    import json

    path = tmp_path / "corrupt.jsonl"
    good = CandidateMessage(topic="ci.status", text="real entry")
    path.write_text(
        json.dumps(good.to_dict())
        + "\n"
        + "this is not json at all\n"
        + '{"record":"candidate","id":"truncated"\n'
        + "[]\n"
        + '{"record":"candidate"}\n'
        + '{"record":"resolution","id":"ghost","outcome":"acted"}\n'
        + "\n",
        encoding="utf-8",
    )

    entries = MuteLog(path).entries()

    assert len(entries) == 1
    assert entries[0].topic == "ci.status"


def test_an_unwritable_log_degrades_quietly(tmp_path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("regular file")
    mute_log = MuteLog(blocker / "sub" / "mute.jsonl")

    mute_log.record(CandidateMessage(topic="t", text="x"))

    assert mute_log.entries() == []


def test_concurrent_writers_do_not_interleave_or_lose_lines(tmp_path) -> None:
    import threading

    path = tmp_path / "mute.jsonl"

    def hammer(tag: int) -> None:
        log = MuteLog(path)
        for index in range(50):
            log.record(CandidateMessage(topic=f"t{tag}", text=f"m{index}"))

    threads = [threading.Thread(target=hammer, args=(tag,)) for tag in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(MuteLog(path).entries()) == 300


def test_absurd_inputs_stay_clamped() -> None:
    drives = Drives()
    now = time.time()
    drives.freshness.discharge(now=now)

    drives.observe_world(3, now=now - 10_000)  # clock jumped backwards
    drives.observe_silence(-500)
    drives.observe_debt(-5)

    assert 0.0 <= drives.freshness.level <= 1.0
    assert drives.contact.level == 0.0
    assert drives.debt.level == 0.0

    drives.observe_debt(10**9)
    assert drives.debt.level == 1.0


def test_a_huge_unicode_message_survives_the_round_trip(tmp_path) -> None:
    mute_log = MuteLog(tmp_path / "mute.jsonl")
    text = "漢字 " + "x" * 100_000 + ' \\ " and a newline\n'

    mute_log.record(CandidateMessage(topic="emoji.🔥", text=text))
    entries = mute_log.entries()

    assert len(entries) == 1
    assert entries[0].topic == "emoji.🔥"
    assert entries[0].text == text


# ---------------------------------------------------------------------------
# Sensor isolation is structural, not a list of exception types
# ---------------------------------------------------------------------------


class _CustomFailure(Exception):
    """Derived straight from Exception — the case no explicit tuple covers."""


class _NotEvenAnException(BaseException):
    """Worse: does not derive from Exception at all."""


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
@pytest.mark.parametrize("exc", [_CustomFailure("custom"), _NotEvenAnException("nastier")])
def test_an_exception_type_nobody_anticipated_cannot_stop_the_sweep(exc) -> None:
    """Catching types can never be complete, so the isolation is structural.

    Each sensor is sampled in its own thread, so an exception of any type dies
    in that worker instead of reaching the loop.
    """
    good = FakeSensor([obs("branch", "dev")])
    world = WorldModel([ThrowingSensor(exc, name="exotic"), good])

    world.sweep()

    assert "fake.topic" in world.topics()


def test_a_sensor_that_never_returns_is_abandoned() -> None:
    """A hang used to stall the whole sweep; nothing caught it because nothing
    was raised."""

    class Hanger:
        @property
        def name(self) -> str:
            return "hanger"

        def sample(self):
            time.sleep(30)
            return []

    world = WorldModel([])
    started = time.perf_counter()
    readings, error = world._sample_isolated(Hanger(), timeout=0.2)
    elapsed = time.perf_counter() - started

    assert readings is None
    assert "timed out" in str(error)
    assert elapsed < 5.0


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_the_sweep_keeps_running_through_an_exotic_failure(tmp_path) -> None:
    class Rotten:
        @property
        def name(self) -> str:
            return "rotten"

        def sample(self):
            raise _CustomFailure("every single time")

    loop = AlivenessLoop(
        world=WorldModel([Rotten(), FakeSensor([obs("branch", "dev")])]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=isolated_gate(tmp_path),
    )
    loop.start(interval_s=0.01)
    try:
        deadline = time.time() + 3.0
        while loop.ticks < 8 and time.time() < deadline:
            time.sleep(0.01)
        assert loop.running is True
    finally:
        loop.stop()

    assert loop.ticks >= 8
    assert "rotten" in loop.world.quarantined


# ---------------------------------------------------------------------------
# The log reads incrementally, and stays correct while doing it
# ---------------------------------------------------------------------------


def test_reading_the_log_twice_does_not_reparse_it(tmp_path) -> None:
    path = tmp_path / "mute.jsonl"
    mute_log = MuteLog(path)
    for index in range(500):
        mute_log.record(CandidateMessage(topic="t", text=f"m{index}"))

    first = mute_log.entries()
    second = mute_log.entries()

    assert len(first) == len(second) == 500
    assert mute_log._offset == path.stat().st_size


def test_the_cache_sees_writes_made_by_someone_else(tmp_path) -> None:
    import json

    path = tmp_path / "mute.jsonl"
    mute_log = MuteLog(path)
    mute_log.record(CandidateMessage(topic="t", text="mine"))
    mute_log.entries()  # warm the cache

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(CandidateMessage(topic="t", text="theirs", id="ext").to_dict()) + "\n")

    ids = [c.id for c in mute_log.entries()]
    assert "ext" in ids

    mute_log.resolve("ext", "acted")
    assert [c.outcome for c in mute_log.entries() if c.id == "ext"] == ["acted"]


def test_a_half_written_line_is_not_consumed_until_it_is_finished(tmp_path) -> None:
    """A reader must never eat half of a line another writer is still writing."""
    import json

    path = tmp_path / "mute.jsonl"
    whole = CandidateMessage(topic="t", text="complete", id="whole")
    path.write_text(
        json.dumps(whole.to_dict()) + "\n" + '{"record":"candidate","id":"half"',
        encoding="utf-8",
    )
    mute_log = MuteLog(path)

    assert [c.id for c in mute_log.entries()] == ["whole"]

    with path.open("a", encoding="utf-8") as handle:
        handle.write(',"topic":"t","text":"now complete"}\n')

    assert sorted(c.id for c in mute_log.entries()) == ["half", "whole"]


def test_truncating_the_log_resets_the_cache(tmp_path) -> None:
    path = tmp_path / "mute.jsonl"
    mute_log = MuteLog(path)
    mute_log.record(CandidateMessage(topic="t", text="one"))
    assert len(mute_log.entries()) == 1

    path.write_text("", encoding="utf-8")

    assert mute_log.entries() == []


def test_a_resolution_that_arrives_before_its_candidate_still_applies(tmp_path) -> None:
    """Only possible in a hand-edited file, but it must not lose the outcome."""
    import json

    path = tmp_path / "mute.jsonl"
    path.write_text(
        json.dumps({"record": "resolution", "id": "late", "outcome": "acted", "outcome_at": 1.0})
        + "\n"
        + json.dumps(CandidateMessage(topic="t", text="arrives second", id="late").to_dict())
        + "\n",
        encoding="utf-8",
    )

    entries = MuteLog(path).entries()

    assert len(entries) == 1
    assert entries[0].outcome == "acted"


# ---------------------------------------------------------------------------
# Permission — the thing that makes the drives load-bearing
# ---------------------------------------------------------------------------


def test_permission_starts_at_zero_for_everything(tmp_path) -> None:
    store = PermissionStore(tmp_path / "p.json")

    assert store.level_for("ci.status") == SILENT
    assert store.grants() == []


def test_a_grant_survives_a_restart(tmp_path) -> None:
    path = tmp_path / "p.json"
    PermissionStore(path).grant("ci.status", NOTIFY, note="you said so")

    reopened = PermissionStore(path)

    assert reopened.level_for("ci.status") == NOTIFY
    assert reopened.grants()[0].note == "you said so"


def test_a_subtopic_inherits_weakly_and_never_the_full_ceiling(tmp_path) -> None:
    """Caring about ci.status should cover ci.status.nightly — quietly."""
    store = PermissionStore(tmp_path / "p.json")
    store.grant("ci.status", INTERRUPT)

    assert store.level_for("ci.status") == INTERRUPT
    assert store.level_for("ci.status.nightly") == INTERRUPT - 1
    assert store.level_for("unrelated.topic") == SILENT


def test_a_weak_grant_is_not_inherited_at_all(tmp_path) -> None:
    store = PermissionStore(tmp_path / "p.json")
    store.grant("ci.status", BRIEF_IF_ROOM)

    assert store.level_for("ci.status.nightly") == SILENT


def test_evidence_raises_a_proposal_not_a_grant(tmp_path) -> None:
    """Earned permission has to ask. That is what keeps it inspectable."""
    store = PermissionStore(tmp_path / "p.json")

    proposal = store.maybe_propose("deploy.status", samples=6, hit_rate=0.83)

    assert proposal is not None
    assert store.level_for("deploy.status") == SILENT  # still silent!
    assert "Want me to" in proposal.question()

    store.accept("deploy.status")
    assert store.level_for("deploy.status") == NOTIFY


def test_thin_or_unconvincing_evidence_proposes_nothing(tmp_path) -> None:
    store = PermissionStore(tmp_path / "p.json")

    assert store.maybe_propose("a.topic", samples=2, hit_rate=1.0) is None
    assert store.maybe_propose("b.topic", samples=20, hit_rate=0.1) is None


def test_the_same_question_is_not_asked_twice(tmp_path) -> None:
    store = PermissionStore(tmp_path / "p.json")
    assert store.maybe_propose("deploy.status", 6, 0.83) is not None
    assert store.maybe_propose("deploy.status", 9, 0.90) is None

    store.decline("deploy.status")
    assert store.proposals() == []


def test_a_grant_nobody_acts_on_decays(tmp_path) -> None:
    from thomas.core.aliveness_permissions import DECAY_AFTER_S

    store = PermissionStore(tmp_path / "p.json")
    store.grant("stale.project", NOTIFY)

    changed = store.decay(now=time.time() + DECAY_AFTER_S + 1)

    assert changed == [("stale.project", NOTIFY, NOTIFY - 1)]
    assert store.level_for("stale.project") == NOTIFY - 1


def test_acting_on_a_topic_keeps_it_fresh(tmp_path) -> None:
    from thomas.core.aliveness_permissions import DECAY_AFTER_S

    store = PermissionStore(tmp_path / "p.json")
    store.grant("live.project", NOTIFY)
    store.record_outcome("live.project", "acted")

    assert store.decay(now=time.time() + DECAY_AFTER_S - 60) == []


def test_the_loop_can_always_ask_for_permission(tmp_path) -> None:
    """Without a seed the design deadlocks: zero permission for everything
    includes the topic used to ask for permission."""
    store = PermissionStore(tmp_path / "p.json")
    store.ensure_seed()

    assert store.level_for(store.SYSTEM_TOPIC) == BRIEF_ALWAYS
    assert store.level_for("anything.else") == SILENT


# ---------------------------------------------------------------------------
# The speak gate
# ---------------------------------------------------------------------------


def hot_drives(debt: bool = True, freshness: bool = True, contact: bool = False) -> Drives:
    drives = Drives()
    drives.debt.set_level(1.0 if debt else 0.0)
    drives.freshness.set_level(1.0 if freshness else 0.0)
    drives.contact.set_level(1.0 if contact else 0.0)
    return drives


def test_without_permission_nothing_gets_through(tmp_path) -> None:
    gate = isolated_gate(tmp_path)

    decision = gate.decide("ci.status", "ci went red", hot_drives(), ["evidence"], idle_seconds=10_000)

    assert decision.deliver is False
    assert decision.reason == "no permission for this topic"


def test_a_brief_entry_costs_no_budget(tmp_path) -> None:
    """Pull is free. That is the whole reason the brief is the default."""
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", BRIEF_ALWAYS)
    before = gate.budget.balance

    decision = gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=10_000)

    assert decision.deliver is True
    assert decision.channel == "brief"
    assert gate.budget.balance == before


def test_silence_alone_can_never_produce_a_message(tmp_path) -> None:
    """Contact supports; it never causes.

    With nothing granted there is nothing for it to lift, however lonely it is.
    """
    gate = isolated_gate(tmp_path)
    only_lonely = hot_drives(debt=False, freshness=False, contact=True)

    decision = gate.decide("nothing.granted", "it has been a while", only_lonely, ["e"], idle_seconds=10_000)

    assert decision.deliver is False
    assert decision.asked_level == SILENT


def test_a_calm_day_settles_for_the_quiet_end_of_a_ceiling(tmp_path) -> None:
    """The drives hold a grant back; they do not build one up."""
    gate = isolated_gate(tmp_path)
    calm = Drives()

    assert gate.asked_level(calm, NOTIFY) == NOTIFY - 1
    assert gate.asked_level(hot_drives(), NOTIFY) == NOTIFY
    # Contact spares it the calm-day downgrade, and can do nothing more.
    lonely = hot_drives(debt=False, freshness=False, contact=True)
    assert gate.asked_level(lonely, NOTIFY) == NOTIFY
    assert gate.asked_level(lonely, SILENT) == SILENT


def test_a_grant_is_never_exceeded_however_hot_the_drives(tmp_path) -> None:
    gate = isolated_gate(tmp_path)

    assert gate.asked_level(hot_drives(contact=True), BRIEF_IF_ROOM) == BRIEF_IF_ROOM
    assert gate.asked_level(hot_drives(contact=True), BRIEF_ALWAYS) == BRIEF_ALWAYS


def test_a_push_is_held_while_you_are_mid_something(tmp_path) -> None:
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", NOTIFY)

    decision = gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=5)

    assert decision.deliver is False
    assert decision.reason == "you are mid-something"


def test_an_interrupt_grant_crosses_that_line(tmp_path) -> None:
    """Level 5 is the point of doing this per topic."""
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("prod.down", INTERRUPT)

    decision = gate.decide("prod.down", "prod is down", hot_drives(contact=True), ["e"], idle_seconds=1)

    assert decision.deliver is True
    assert decision.channel == "push"
    assert decision.level == INTERRUPT


def test_the_same_thing_is_not_said_twice(tmp_path) -> None:
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", BRIEF_ALWAYS)

    first = gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=10_000)
    second = gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=10_000)

    assert first.deliver is True
    assert second.deliver is False
    assert second.reason == "already said this recently"


def test_nothing_to_say_is_never_said(tmp_path) -> None:
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", INTERRUPT)

    decision = gate.decide("ci.status", "   ", hot_drives(), [], idle_seconds=10_000)

    assert decision.deliver is False
    assert decision.reason == "nothing to say"


def test_the_push_budget_binds_and_says_so(tmp_path, caplog) -> None:
    gate = isolated_gate(tmp_path, budget=PushBudget(daily=1.0, balance=1.0))
    gate.permissions.grant("a.topic", NOTIFY)
    gate.permissions.grant("b.topic", NOTIFY)

    first = gate.decide("a.topic", "one", hot_drives(), ["e"], idle_seconds=10_000)
    with caplog.at_level("INFO"):
        second = gate.decide("b.topic", "two", hot_drives(), ["e"], idle_seconds=10_000)

    assert first.deliver is True
    assert second.deliver is False
    assert second.reason == "push budget spent for today"
    assert "too many grants" in caplog.text.lower()


def test_a_message_you_act_on_is_refunded(tmp_path) -> None:
    """Closed loop: what works costs nothing, what is ignored drains extra."""
    gate = isolated_gate(tmp_path, budget=PushBudget(daily=1.0, balance=1.0))
    gate.permissions.grant("ci.status", NOTIFY)
    gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=10_000)
    spent = gate.budget.balance

    gate.record_outcome("ci.status", "acted", channel="push")

    assert gate.budget.balance > spent


def test_being_told_to_stop_puts_the_budget_in_debt(tmp_path) -> None:
    """Not just empty — in debt, so it takes days of daily top-up to recover.
    That debt is the auto-mute period."""
    gate = isolated_gate(tmp_path, budget=PushBudget(daily=1.0, balance=3.0))

    gate.record_outcome("ci.status", "stopped", channel="push")

    assert gate.budget.balance < 0
    assert gate.budget.can_spend() is False


def test_a_drained_budget_does_not_come_back_full_tomorrow(tmp_path) -> None:
    """Resetting daily would erase the closed loop entirely."""
    budget = PushBudget(daily=1.0, balance=-3.0, day="2026-08-01")

    budget._roll(time.time())

    assert budget.balance == -2.0
    assert budget.can_spend() is False


def test_a_granted_topic_actually_gets_delivered_by_the_loop(tmp_path) -> None:
    """End to end: grant, change the world, watch it come out of the gate."""
    sensor = FakeSensor([obs("dev", "green", topic="ci.status")])
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", BRIEF_ALWAYS)
    loop = AlivenessLoop(
        world=WorldModel([sensor]),
        drives=Drives(),
        mute_log=MuteLog(tmp_path / "mute.jsonl"),
        gate=gate,
    )
    loop.tick(idle_seconds=10_000)

    sensor.readings = [obs("dev", "red", topic="ci.status")]
    summary = loop.tick(idle_seconds=10_000)

    assert summary["delivered"] == 1
    # The drives are quiet, so it settled for the quiet end of its ceiling
    # rather than all of it. That is the drives doing work.
    assert loop.sink.delivered == [("ci.status", "brief", BRIEF_IF_ROOM)]

    entry = [c for c in loop.mute_log.entries() if c.topic == "ci.status"][-1]
    assert entry.channel == "brief"
    loop.record_outcome(entry.id, entry.topic, "acted")
    assert [c.outcome for c in loop.mute_log.entries() if c.id == entry.id] == ["acted"]


def test_a_held_message_never_costs_the_push_budget(tmp_path) -> None:
    """It was never sent. A fortnight of ignored held candidates drove the
    balance to its floor, which would have silently disabled every push."""
    gate = isolated_gate(tmp_path, budget=PushBudget(daily=1.0, balance=1.0))
    before = gate.budget.balance

    for _ in range(50):
        gate.record_outcome("ungranted.topic", "ignored", channel="held")

    assert gate.budget.balance == before
    assert gate.budget.can_spend() is True


def test_an_ignored_brief_entry_costs_nothing_either(tmp_path) -> None:
    """Pull costs no attention, so ignoring it cannot cost budget."""
    gate = isolated_gate(tmp_path, budget=PushBudget(daily=1.0, balance=1.0))
    before = gate.budget.balance

    gate.record_outcome("ci.status", "ignored", channel="brief")

    assert gate.budget.balance == before


def test_a_notify_grant_actually_reaches_notify(tmp_path) -> None:
    """A granted ceiling above 'brief' has to be reachable, or the escalation
    levels are decoration."""
    gate = isolated_gate(tmp_path)
    gate.permissions.grant("ci.status", NOTIFY)

    decision = gate.decide("ci.status", "ci went red", hot_drives(), ["e"], idle_seconds=10_000)

    assert decision.deliver is True
    assert decision.channel == "push"
    assert decision.level == NOTIFY
