"""Your window's length, its number of landings and whether it keeps landing while you are away (your decision,
2026-10-22): each chosen when you open it, each on the card you sign, each kept to the end.

Defaults stay what they were: 120 minutes, at most 25 landings, paused while your PC is locked and ended after 15
minutes locked or idle. You may choose up to 1440 minutes, another number of landings or none, and -- only on a PC whose
elevated setup turned it on -- a window that keeps landing while your PC is locked or you are away. Such a window still
ends at its time, at its number, with an off switch, on a sign-out, or when the setting goes; protected and cage files
keep their cards and the check after each landing stays as it is (those are tested in their own files).

A fake clock, a fake presence and a stand-in for the elevated setting's check; no Windows prompt is shown, and nothing
is written outside tmp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.cage import window_control as wc
from scripts.cage import window_state as ws
from scripts.cage.referee.presence import Presence

from thomas.tools import trusted_card


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

    def state(self) -> Presence:
        return Presence(self.locked, self.idle_seconds, self.logon_session)


class Setting:
    """Stands in for window_state.away_allowed: what the elevated setup left in the pin folder."""

    def __init__(self, on: bool) -> None:
        self.on = on
        self.read: list[Path | None] = []

    def __call__(self, flag: Path | None) -> str:
        self.read.append(flag)
        return "" if self.on else "keeping a window open while you are away is off on this PC"


def _window(tmp_path: Path, clock: Clock, seen: Seen, setting: Setting | None = None) -> ws.Window:
    return ws.Window(
        presence=seen,
        off_markers=[tmp_path / "pins" / ws.OFF_NAME],
        ceiling_minutes=trusted_card.load_catalogue().WINDOW_CEILING_MINUTES,
        max_landings=trusted_card.load_catalogue().WINDOW_MAX_LANDINGS,
        idle_minutes=15,
        clock=clock,
        away_flag=tmp_path / "pins" / ws.AWAY_NAME,
        away_check=setting or Setting(False),
    )


def _open(window: ws.Window, minutes: int = 120, **chosen: object) -> ws.Opened:
    why, before = window.may_open()
    assert why == "" and before is not None
    return window.open(minutes, "ABC-DEF", "0123456789abcdef", before=before, **chosen)  # type: ignore[arg-type]


# -- the defaults ------------------------------------------------------------------------------------------------------
def test_the_defaults_stay_120_minutes_25_landings_and_present(tmp_path: Path) -> None:
    catalogue = trusted_card.load_catalogue()
    assert (catalogue.WINDOW_DEFAULT_MINUTES, catalogue.WINDOW_MAX_LANDINGS, catalogue.WINDOW_IDLE_MINUTES) == (
        120,
        25,
        15,
    )
    wc.main(["open"], folder=tmp_path)
    (sent,) = (json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "requests").glob("*.json"))
    assert sent["minutes"] == catalogue.WINDOW_DEFAULT_MINUTES and sent["away"] is False and "max_landings" not in sent
    window = _window(tmp_path, Clock(), Seen())
    opened = _open(window)
    assert (opened.minutes, opened.max_landings, opened.away) == (120, 25, False)
    assert window.status()["away"] is False and window.status()["max_landings"] == 25


# -- how long ----------------------------------------------------------------------------------------------------------
def test_a_window_may_last_until_you_turn_it_off_and_no_longer_than_a_year(tmp_path: Path) -> None:
    """You chose on 2026-10-27 that a window lasts until you turn it off; a year is the most a window can last."""
    clock = Clock()
    window = _window(tmp_path, clock, Seen())
    year = trusted_card.load_catalogue().WINDOW_CEILING_MINUTES
    assert year == 525600 == wc.UNTIL_OFF_MINUTES
    with pytest.raises(ws.WindowRefused):
        window.open(year + 1, "ABC-DEF", "0123456789abcdef", before=Presence(False, 1.0, "1:1234"))
    _open(window, year)
    assert window.status()["ends_at"] == ws._iso(clock.wall + year * 60)
    clock.advance(year * 60 - 1)
    assert window.why_not() == ""
    clock.advance(2)
    assert window.why_not() == "its time is up" and window.opened is None


def test_until_off_asks_for_the_longest_window(tmp_path: Path) -> None:
    wc.main(["open", "--until-off", "--no-landing-cap", "--away"], folder=tmp_path)
    (sent,) = (json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "requests").glob("*.json"))
    assert sent["minutes"] == wc.UNTIL_OFF_MINUTES and sent["away"] is True and sent["max_landings"] is None
    with pytest.raises(SystemExit):
        wc.main(["open", "--until-off", "--minutes", "60"], folder=tmp_path)


# -- how many ----------------------------------------------------------------------------------------------------------
def test_a_chosen_number_of_landings_ends_it_there(tmp_path: Path) -> None:
    window = _window(tmp_path, Clock(), Seen())
    _open(window, max_landings=3)
    for _ in range(3):
        assert window.why_not() == ""
        window.landed()
    assert "landed 3 changes" in window.why_not() and window.opened is None


def test_no_limit_on_landings_lands_on_until_its_time_is_up(tmp_path: Path) -> None:
    clock = Clock()
    window = _window(tmp_path, clock, Seen())
    _open(window, 60, max_landings=None)
    for _ in range(200):
        assert window.why_not() == ""
        window.landed()
    assert window.status()["max_landings"] is None
    clock.advance(60 * 60 + 1)
    assert window.why_not() == "its time is up"


@pytest.mark.parametrize("bad", [0, -1, True, "25", 2.5])
def test_a_number_of_landings_is_a_whole_number_of_one_or_more(tmp_path: Path, bad: object) -> None:
    with pytest.raises(ws.WindowRefused):
        _open(_window(tmp_path, Clock(), Seen()), max_landings=bad)


# -- away --------------------------------------------------------------------------------------------------------------
def test_an_away_window_keeps_landing_while_your_pc_is_locked_or_idle(tmp_path: Path) -> None:
    clock, seen = Clock(), Seen()
    window = _window(tmp_path, clock, seen, Setting(True))
    opened = _open(window, 1440, away=True, max_landings=None)
    assert opened.away and window.status()["away"] is True
    seen.locked = True
    clock.advance(16 * 60)
    assert window.why_not() == "", "locked for more than 15 minutes: it keeps landing"
    seen.locked, seen.idle_seconds = False, 8 * 3600.0
    assert window.why_not() == "", "idle for hours: it keeps landing"


@pytest.mark.parametrize("end", ["time", "number", "off", "sign-out", "setting"])
def test_an_away_window_still_ends_at_every_other_limit(tmp_path: Path, end: str) -> None:
    clock, seen, setting = Clock(), Seen(), Setting(True)
    window = _window(tmp_path, clock, seen, setting)
    _open(window, 30, away=True, max_landings=2)
    seen.locked = True
    if end == "time":
        clock.advance(30 * 60 + 1)
    elif end == "number":
        window.landed()
        window.landed()
    elif end == "off":
        (tmp_path / "pins").mkdir()
        (tmp_path / "pins" / ws.OFF_NAME).write_text("off", encoding="utf-8")
    elif end == "sign-out":
        seen.logon_session = "1:9999"
    else:
        setting.on = False
    assert window.why_not() and window.opened is None, f"an away window ends on {end}"


def test_a_check_after_landing_that_fails_still_closes_an_away_window(tmp_path: Path) -> None:
    window = _window(tmp_path, Clock(), Seen(), Setting(True))
    _open(window, away=True)
    assert window.close("the check after the last landing failed") is not None and window.opened is None


def test_away_is_refused_unless_this_pc_turned_it_on(tmp_path: Path) -> None:
    window = _window(tmp_path, Clock(), Seen(), Setting(False))
    with pytest.raises(ws.WindowRefused, match="off on this PC"):
        _open(window, away=True)
    assert window.opened is None


def test_an_away_window_is_still_opened_only_with_you_at_this_pc(tmp_path: Path) -> None:
    seen = Seen()
    seen.locked = True
    why, before = _window(tmp_path, Clock(), seen, Setting(True)).may_open()
    assert why and before is None
