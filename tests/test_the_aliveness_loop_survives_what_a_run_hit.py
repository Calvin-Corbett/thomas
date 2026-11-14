"""The aliveness loop survives what a simulated run actually hit.

Robustness cases, structural sensor isolation, and the incremental log read
that stays correct while the file grows. Split from
test_the_aliveness_loop_records_instead_of_speaking.py on 2026-09-07 so each
file stays under the monolith guard's limit.
"""
from __future__ import annotations

import time

import pytest

from tests._aliveness_fakes import FakeSensor, isolated_gate, obs
from thomas.core.aliveness import (
    AlivenessLoop,
)
from thomas.core.aliveness_drives import Drives
from thomas.core.aliveness_log import (
    CandidateMessage,
    MuteLog,
)
from thomas.core.aliveness_world import Observation, WorldModel

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
