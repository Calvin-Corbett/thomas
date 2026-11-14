"""Your window opens only with you at this PC, and ends on every rule spec section 8.4 names.

A fake clock and a fake presence stand in for Windows; no sign-in is shown and nothing is written outside tmp.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.cage import window_presence as wp
from scripts.cage import window_state as ws
from scripts.cage.referee.presence import Presence
from scripts.cage.referee.presence_win import FLAG_LOCKED, FLAG_UNLOCKED, SessionInfo


class Clock:
    def __init__(self) -> None:
        self.wall, self.mono = 1_000_000.0, 500.0

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.mono += seconds


class Seen:
    def __init__(self) -> None:
        self.locked, self.idle_seconds, self.logon_session = False, 5.0, "1:1234"
        self.broken = False

    def state(self) -> Presence:
        if self.broken:
            raise OSError("WTS said no")
        return Presence(self.locked, self.idle_seconds, self.logon_session)


@pytest.fixture
def parts(tmp_path: Path) -> tuple[ws.Window, Clock, Seen, Path]:
    clock, seen, marker = Clock(), Seen(), tmp_path / "pins" / ws.OFF_NAME
    window = ws.Window(
        presence=seen, off_markers=[marker], ceiling_minutes=120, max_landings=25, idle_minutes=15, clock=clock
    )
    return window, clock, seen, marker


def _open(window: ws.Window, minutes: int = 120) -> ws.Opened:
    why, before = window.may_open()
    assert why == "" and before is not None
    return window.open(minutes, "ABC-DEF", "0123456789abcdef", before=before)


def test_a_window_opens_for_up_to_the_pinned_ceiling_and_says_until_when(parts) -> None:
    window, clock, _, _ = parts
    for minutes in (0, 121):
        with pytest.raises(ws.WindowRefused):
            window.open(minutes, "ABC-DEF", "0123456789abcdef", before=Presence(False, 1.0, "1:1234"))
    opened = _open(window)
    assert window.why_not() == "" and opened.pairing_code == "ABC-DEF"
    status = window.status()
    assert status["open"] and status["minutes"] == 120 and status["landings"] == 0
    assert status["ends_at"] == ws._iso(clock.wall + 120 * 60)


@pytest.mark.parametrize("state", ["locked", "away", "broken", "off"])
def test_a_window_is_not_asked_for_unless_you_are_here(parts, state: str) -> None:
    window, _, seen, marker = parts
    if state == "locked":
        seen.locked = True
    elif state == "away":
        seen.idle_seconds = 120.0
    elif state == "broken":
        seen.broken = True
    else:
        marker.parent.mkdir(parents=True)
        marker.write_text("off", encoding="utf-8")
    why, before = window.may_open()
    assert why and before is None


def test_the_session_must_not_change_between_the_card_and_the_opening(parts) -> None:
    window, _, seen, _ = parts
    _, before = window.may_open()
    seen.logon_session = "1:9999"
    with pytest.raises(ws.WindowRefused):
        window.open(120, "ABC-DEF", "0123456789abcdef", before=before)


def test_it_ends_when_its_time_is_up(parts) -> None:
    window, clock, _, _ = parts
    _open(window, 30)
    clock.advance(30 * 60 - 1)
    assert window.why_not() == ""
    clock.advance(2)
    assert window.why_not() == "its time is up" and window.opened is None


def test_setting_the_wall_clock_back_gives_no_time_back(parts) -> None:
    window, clock, _, _ = parts
    _open(window, 30)
    clock.mono += 31 * 60
    clock.wall -= 3600
    assert window.why_not() == "its time is up"


def test_it_ends_at_the_pinned_number_of_landings(parts) -> None:
    window, _, _, _ = parts
    _open(window)
    for _ in range(25):
        assert window.why_not() == ""
        window.landed()
    assert "landed 25 changes" in window.why_not() and window.opened is None


def test_a_locked_pc_pauses_it_and_fifteen_locked_minutes_end_it(parts) -> None:
    window, clock, seen, _ = parts
    _open(window)
    seen.locked = True
    assert "locked" in window.why_not() and window.opened is not None
    clock.advance(14 * 60)
    assert "landings wait" in window.why_not()
    clock.advance(2 * 60)
    assert "locked for more than 15 minutes" in window.why_not() and window.opened is None


def test_fifteen_idle_minutes_end_it(parts) -> None:
    window, _, seen, _ = parts
    _open(window)
    seen.idle_seconds = 15 * 60 + 1
    assert "idle for more than 15 minutes" in window.why_not() and window.opened is None


def test_a_sign_out_or_restart_ends_it(parts) -> None:
    window, _, seen, _ = parts
    _open(window)
    seen.logon_session = "2:4321"
    assert "signed out" in window.why_not()


def test_an_off_switch_ends_it(parts) -> None:
    window, _, _, marker = parts
    _open(window)
    marker.parent.mkdir(parents=True)
    marker.write_text("off", encoding="utf-8")
    assert "off switch" in window.why_not() and window.opened is None


def test_presence_that_cannot_be_read_holds_landings_without_ending_the_window(parts) -> None:
    window, _, seen, _ = parts
    _open(window)
    seen.broken = True
    assert "could not be read" in window.why_not() and window.opened is not None


def test_each_ended_window_is_handed_over_once_with_why(parts) -> None:
    window, _, _, _ = parts
    opened = _open(window)
    assert window.close("you closed it") == opened
    assert window.take_ended() == [(opened, "you closed it")]
    assert window.take_ended() == [] and window.close("again") is None


def test_the_in_session_reader_reads_the_lock_the_idle_time_and_the_session() -> None:
    class Wts:
        flags = FLAG_LOCKED

        def active_session(self) -> int:
            return 1

        def session_info(self, number: int) -> SessionInfo:
            return SessionInfo(self.flags, 777, 0, 999)

    api = Wts()
    reader = wp.InSession(api, session=lambda: 3, idle=lambda: 42.0)
    assert reader.state() == Presence(True, 42.0, "3:777")
    api.flags = FLAG_UNLOCKED
    assert reader.state().locked is False
    api.flags = 7
    with pytest.raises(OSError):
        reader.state()
