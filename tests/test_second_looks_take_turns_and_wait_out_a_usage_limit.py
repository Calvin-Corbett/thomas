"""At most two second looks run at once, and a usage limit pauses them until your plan resets (spec Part 1 item 6).

The second look runs on the same Claude plan as the operator. On 2026-09-25 a usage limit stalled every hand-in for
20.4 hours, each held one asking the CLI again every 15 minutes and spending its tries. Now second looks take turns, a
limit pauses every one until the reset the CLI printed, every held hand-in shows that time, and you get one notice.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._claude_plan_fakes import SESSION_LIMIT, THROTTLED
from thomas.core import claude_plan
from thomas.core.provider_limits import when_words
from thomas.server import capacity_ledger, capacity_ledger_locks, green_checkout
from thomas.server.precard import review, review_dial
from thomas.server.precard.check import PASSED, Checked

CHECKED = Checked(PASSED, "line")
T = 1_800_000_000.0
REPO = Path(__file__).resolve().parents[1]


def _reply(verdict: str) -> str:
    text = f"I read it.\n{json.dumps({'verdict': verdict, 'findings': []})}"
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text})


def _refused(said: str) -> tuple[int, str]:
    return 1, json.dumps({"type": "result", "is_error": True, "api_error_status": 429, "result": said})


SAFE = (0, _reply("SAFE"))


def _wait_until(test: Callable[[], bool], within: float = 5.0) -> None:
    ends = time.monotonic() + within
    while not test():
        assert time.monotonic() < ends, "it never happened"
        time.sleep(0.01)


class Gate:
    """Stands in for the Claude CLI: each call waits for its own release; records order and how many ran at once."""

    def __init__(self, count: int, answers: dict[int, tuple[int, str]] | None = None) -> None:
        self.release = {n: threading.Event() for n in range(count)}
        self.answers = answers or {}
        self.lock = threading.Lock()
        self.running = self.max_running = 0
        self.order: list[int] = []

    def __call__(self, argv: list[str], cwd: str, prompt: str, timeout: float) -> tuple[int, str]:
        number = int(re.search(r"request (\d+)", prompt).group(1))
        with self.lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            self.order.append(number)
        try:
            assert self.release[number].wait(10)
            return self.answers.get(number, SAFE)
        finally:
            with self.lock:
                self.running -= 1


class Answers:
    def __init__(self, *answers: tuple[int, str]) -> None:
        self.answers, self.calls = list(answers), 0

    def __call__(self, argv: list[str], cwd: str, prompt: str, timeout: float) -> tuple[int, str]:
        self.calls += 1
        return self.answers.pop(0)


@pytest.fixture(autouse=True)
def reviewer_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))  # this test's own turns and pause
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "greens"))
    monkeypatch.setattr(capacity_ledger, "POLL_S", 0.02)
    monkeypatch.setattr(review_dial, "notice", lambda *_a: None)  # a pause here records no issue (one test counts them)
    monkeypatch.delenv(review.REVIEW_ENV, raising=False)
    monkeypatch.delenv(review_dial.SECOND_LOOKS_ENV, raising=False)
    monkeypatch.setattr(review, "emergency_stop_active", lambda: False)
    monkeypatch.setattr(green_checkout, "find_green", lambda _eid: SimpleNamespace(work=tmp_path))


def _start(n: int, results: dict) -> threading.Thread:
    def look() -> None:
        try:
            results[n] = review.review_hand_in(f"e{n}", f"request {n}", CHECKED)
        except review.ReviewUnavailable as exc:
            results[n] = exc

    thread = threading.Thread(target=look)
    thread.start()
    return thread


def _start_all(count: int, gate: Gate, results: dict) -> list[threading.Thread]:
    threads = []
    for n in range(count):
        threads.append(_start(n, results))
        _wait_until(lambda n=n: review_dial.running() + review_dial.waiting() == n + 1)
        if n < 2:
            _wait_until(lambda n=n: n in gate.order)  # a place is free: it starts before the next is asked for
    return threads


def test_at_most_two_second_looks_run_at_once_and_the_rest_wait_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = Gate(5)
    monkeypatch.setattr(review, "run_reviewer", gate)
    results: dict = {}
    threads = _start_all(5, gate, results)
    assert gate.running == 2 and review_dial.waiting() == 3
    for n in range(5):
        gate.release[n].set()  # the place it gives back goes to the next in line, and only then is the next let go
        if n + 2 < 5:
            _wait_until(lambda n=n: n + 2 in gate.order)
    for thread in threads:
        thread.join(10)
    assert gate.max_running == 2 and gate.order == [0, 1, 2, 3, 4]
    assert all(results[n] == review.Verdict(True) for n in range(5))


@pytest.mark.parametrize(("value", "dial"), [("3", 3), ("0", 2), ("x", 2)])
def test_the_dial_is_set_by_THOMAS_SECOND_LOOKS(monkeypatch: pytest.MonkeyPatch, value: str, dial: int) -> None:
    monkeypatch.setenv(review_dial.SECOND_LOOKS_ENV, value)
    assert review_dial.capacity() == dial


def test_your_plans_session_limit_pauses_second_looks_until_the_reset_it_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = claude_plan.reset_from_words(SESSION_LIMIT, datetime.fromtimestamp(T).astimezone())
    assert expected is not None
    monkeypatch.setattr(review_dial, "clock", lambda: expected[0] - 3 * 3600)  # well before it, on any machine
    reviewer = Answers(_refused(SESSION_LIMIT), SAFE)
    monkeypatch.setattr(review, "run_reviewer", reviewer)

    with pytest.raises(review.UsageLimited) as first:
        review.review_hand_in("e1", "request 1", CHECKED)
    assert first.value.resets_at == expected[0] and first.value.estimated is (not expected[1])
    assert (first.value.step, first.value.costly) == ("second look", False)

    with pytest.raises(review.UsageLimited):
        review.review_hand_in("e2", "request 2", CHECKED)
    assert reviewer.calls == 1, "no CLI call while your plan is paused"

    monkeypatch.setattr(review_dial, "clock", lambda: first.value.resets_at + 1)
    assert review.review_hand_in("e3", "request 3", CHECKED) == review.Verdict(True)


def test_a_limit_releases_second_looks_already_waiting_as_held(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = Gate(3, {0: _refused(SESSION_LIMIT)})
    monkeypatch.setattr(review, "run_reviewer", gate)
    results: dict = {}
    threads = _start_all(3, gate, results)  # looks 0 and 1 hold both places, look 2 waits
    assert review_dial.pause(time.time() + 3600), "the limit your plan met in another server's second look"
    _wait_until(lambda: 2 in results)  # released as held with both places still in use
    assert isinstance(results[2], review.UsageLimited) and gate.running == 2
    gate.release[0].set()
    gate.release[1].set()
    for thread in threads:
        thread.join(10)
    assert isinstance(results[0], review.UsageLimited) and results[1] == review.Verdict(True)
    assert gate.order == [0, 1], "the one waiting never reached the CLI"


LOOKS = r"""
import sys, threading, time
from pathlib import Path
from thomas.server import capacity_ledger
from thomas.server.precard import review_dial
log, name = Path(sys.argv[1]), sys.argv[2]
capacity_ledger.POLL_S = 0.05
spans = []
def notice(until, estimated, waiting):
    (log.parent / f"notice-{name}-{time.time_ns()}").write_text(str(until), encoding="utf-8")
review_dial.notice = notice
def look():
    with review_dial.turn():
        start = time.time()
        time.sleep(0.3)
        spans.append(f"{name} {start} {time.time()}")
threads = [threading.Thread(target=look) for _ in range(5)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
log.write_text("\n".join(spans), encoding="utf-8")
(log.parent / f"done-{name}").write_text("x", encoding="utf-8")
ends = time.time() + 120
while len(list(log.parent.glob("done-*"))) < 2 and time.time() < ends:
    time.sleep(0.05)
review_dial.pause(time.time() + 3600)
"""


def test_two_servers_run_at_most_two_second_looks_and_you_get_one_notice(tmp_path: Path) -> None:
    logs = {name: tmp_path / f"{name}.log" for name in ("a", "b")}
    env = {key: value for key, value in os.environ.items() if key != review_dial.SECOND_LOOKS_ENV}
    env[capacity_ledger.ROOT_ENV] = str(tmp_path / "ledger")
    env[green_checkout.GREEN_ROOT_ENV] = str(tmp_path / "greens")
    children = [
        subprocess.Popen([sys.executable, "-c", LOOKS, str(log), name], cwd=REPO, env=env) for name, log in logs.items()
    ]
    for child in children:
        assert child.wait(180) == 0
    spans = [line.split() for log in logs.values() for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(spans) == 10 and {name for name, _, _ in spans} == {"a", "b"}
    edges = sorted([(float(start), 1) for _, start, _ in spans] + [(float(end), -1) for _, _, end in spans])
    running = most = 0
    for _, step in edges:
        running += step
        most = max(most, running)
    assert most == 2, "one dial of 2 for both servers"
    assert len(list(tmp_path.glob("notice-*"))) == 1, "both servers met the limit, and you get one notice"


def test_a_limit_with_no_believable_reset_is_looked_at_again_in_half_an_hour() -> None:
    recheck = (T + review_dial.RECHECK_S, True)
    assert review_dial.plan_reset("Claude AI usage limit reached|1790600000", now=T) == recheck
    assert review_dial.plan_reset("Claude AI usage limit reached", now=T) == recheck
    later = int(T) + 7200
    assert review_dial.plan_reset(f"Claude AI usage limit reached|{later}", now=T) == (float(later), False)
    assert review_dial.plan_reset(THROTTLED, now=T) is None


def test_a_short_throttle_is_unavailable_but_never_a_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    reviewer = Answers(_refused(THROTTLED), SAFE)
    monkeypatch.setattr(review, "run_reviewer", reviewer)

    with pytest.raises(review.ReviewUnavailable) as caught:
        review.review_hand_in("e1", "request 1", CHECKED)

    assert not isinstance(caught.value, review.UsageLimited)
    assert "your Claude plan's usage limit is reached" not in str(caught.value)
    assert review_dial.pause_shown() is None
    assert review.review_hand_in("e2", "request 2", CHECKED) == review.Verdict(True) and reviewer.calls == 2


def test_one_notice_per_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    notices: list[float] = []
    monkeypatch.setattr(review_dial, "notice", lambda until, _estimated, _waiting: notices.append(until))
    now = [T]
    monkeypatch.setattr(review_dial, "clock", lambda: now[0])
    monkeypatch.setattr(review, "run_reviewer", Answers(_refused(SESSION_LIMIT), _refused(SESSION_LIMIT), SAFE,
                                                        _refused(SESSION_LIMIT)))  # fmt: skip

    with pytest.raises(review.UsageLimited) as first:
        review.review_hand_in("e1", "request 1", CHECKED)
    with pytest.raises(review.UsageLimited):
        review.review_hand_in("e2", "request 2", CHECKED)  # refused during the pause: no CLI call, no notice
    now[0] = first.value.resets_at + 1
    with pytest.raises(review.UsageLimited) as again:
        review.review_hand_in("e3", "request 3", CHECKED)  # the limit again, with no answer between: no notice
    assert notices == [first.value.resets_at]

    now[0] = again.value.resets_at + 1
    assert review.review_hand_in("e4", "request 4", CHECKED) == review.Verdict(True)
    with pytest.raises(review.UsageLimited):
        review.review_hand_in("e5", "request 5", CHECKED)
    assert len(notices) == 2

    recorded: list[dict] = []
    monkeypatch.setattr("thomas.server.issue_ledger.record_issue", lambda **kwargs: recorded.append(kwargs))
    review_dial._record_notice(T + 3600, False, 3)
    assert recorded[0]["kind"] == "second_looks_paused" and when_words(T + 3600) in recorded[0]["message"]


def test_a_ledger_that_cannot_be_read_holds_the_second_look_and_never_runs_it_unadmitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreadable(_place: Path, _name: str) -> list:
        raise capacity_ledger_locks.LedgerUnreadable("the ledger cannot be read")

    reviewer = Answers(SAFE)
    monkeypatch.setattr(review, "run_reviewer", reviewer)
    monkeypatch.setattr(capacity_ledger_locks, "read_rows", unreadable)

    with pytest.raises(review.ReviewUnavailable, match="the ledger cannot be read.*did not run") as caught:
        review.review_hand_in("e1", "request 1", CHECKED)

    assert not isinstance(caught.value, review.UsageLimited) and getattr(caught.value, "costly", False) is False
    assert reviewer.calls == 0 and review_dial.pause_shown() is None
