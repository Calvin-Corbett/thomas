"""Your window choices reach the card you sign, its status and its record, and only your elevated setup turns the away
option on (your decision, 2026-10-22; the rules themselves are in
tests/test_your_window_can_last_a_day_land_any_number_or_keep_on_while_you_are_away.py).

Stand-ins for the lane, the checker and the sign-in (tests/test_the_window_loop_runs_beside_the_cards.py) and for the
elevated setting's check; no Windows prompt is shown, and nothing is written outside tmp.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from scripts.cage import window_control as wc
from scripts.cage import window_loop as wl
from scripts.cage import window_state as ws

from tests.test_the_window_loop_runs_beside_the_cards import Rig
from thomas.tools import trusted_card

REPO = Path(__file__).resolve().parents[1]


class Setting:
    """Stands in for window_state.away_allowed: what the elevated setup left in the pin folder."""

    def __init__(self, on: bool) -> None:
        self.on = on

    def __call__(self, flag: Path | None) -> str:
        return "" if self.on else "keeping a window open while you are away is off on this PC"


# -- who can turn away on ----------------------------------------------------------------------------------------------
def test_a_window_away_file_anyone_but_system_and_administrators_could_write_does_not_count(tmp_path: Path) -> None:
    """What the Build teams' account (or any process of yours not elevated) could write is never the setting: this
    test's own tmp folder is such a place, and its window.away reading "on" is still refused."""
    flag = tmp_path / ws.AWAY_NAME
    flag.write_text("on", encoding="utf-8")
    why = ws.away_allowed(flag)
    assert why, "a window.away in a folder this account can write must not turn the away option on"
    assert ws.away_allowed(None) and ws.away_allowed(tmp_path / "missing")
    off = tmp_path / "off"
    off.mkdir()
    (off / ws.AWAY_NAME).write_text("yes please", encoding="utf-8")
    assert "off on this PC" in ws.away_allowed(off / ws.AWAY_NAME)


def test_the_away_setting_is_read_from_the_pin_folder_only_and_written_only_by_the_elevated_setup() -> None:
    start = (REPO / "scripts" / "cage" / "window_start.py").read_text(encoding="utf-8")
    assert "away_flag=pins / AWAY_NAME" in start and "pins = Path(pin_root or cage_shell.DEFAULT_PIN_ROOT)" in start
    setup = (REPO / "scripts" / "cage" / "enable_window.ps1").read_text(encoding="utf-8")
    assert '[ValidateSet("keep", "on", "off")][string]$AwayWindows = "keep"' in setup, "off unless you turn it on"
    assert 'Write-PinFile -PinRoot $PinRoot -Name "window.away" -Value "on"' in setup
    assert '/setowner "*S-1-5-32-544"' in setup and "Initialize-PinFolder -PinRoot $PinRoot" in setup
    naming = {
        path.relative_to(REPO).as_posix(): path.read_text(encoding="utf-8", errors="replace")
        for root in ("scripts", "thomas")
        for path in (REPO / root).rglob("*.py")
        if "window.away" in path.read_text(encoding="utf-8", errors="replace")
        or "AWAY_NAME" in path.read_text(encoding="utf-8", errors="replace")
    }
    assert sorted(naming) == [
        "scripts/cage/card_catalogue.py",
        "scripts/cage/window_control.py",
        "scripts/cage/window_loop.py",
        "scripts/cage/window_start.py",
        "scripts/cage/window_state.py",
    ]
    for rel, text in naming.items():
        for line in text.splitlines():
            if "window.away" in line or "AWAY_NAME" in line:
                assert "write" not in line.lower() or "only" in line.lower(), f"{rel} must never write it: {line}"
    assert "AWAY_NAME" not in naming["scripts/cage/window_control.py"], "your control asks; it never sets the option"


# -- the card and the record -------------------------------------------------------------------------------------------
def test_the_away_card_says_it_keeps_landing_and_how_it_still_ends() -> None:
    catalogue = trusted_card.load_catalogue()
    title, body = catalogue.render(
        "open_window_away",
        {"minutes": "1440", "ends": "Thu 10:15", "waiting": "3", "cap": catalogue.window_cap_words(None)},
    )
    assert title == "Let Thomas land checked changes while you are away"
    for words in (
        "1440 minute(s)",
        "until Thu 10:15",
        "with no limit on how many",
        "KEEPS LANDING while your PC is locked or you are away",
        "ends at that time",
        "off switch",
        "check after a landing fails",
        "Cancel opens nothing",
    ):
        assert words in body
    assert catalogue.window_cap_words(25) == "at most 25"
    with pytest.raises(ValueError):
        catalogue.window_cap_words(0)


def _rig(tmp_path: Path, on: bool, ceiling: int = 1440) -> Rig:
    rig = Rig(tmp_path)
    rig.window = ws.Window(presence=rig.window._presence, off_markers=[rig.home / wl.OFF], ceiling_minutes=ceiling,
                           max_landings=25, idle_minutes=15, clock=rig.window._clock,
                           away_flag=tmp_path / "pins" / ws.AWAY_NAME, away_check=Setting(on))  # fmt: skip
    rig.loop = wl.WindowLoop(card=rig.card, lane=rig.lane, undoer=rig.undoer, window=rig.window, link=rig.link,
                             record=rig.record, home=rig.home, ask=rig.ask)  # fmt: skip
    return rig


def test_an_until_off_window_card_names_the_date_it_would_end_and_fits(tmp_path: Path) -> None:
    """A window that lasts until you turn it off (2026-10-27) would end a year away; a weekday and time would read as
    this week on the card you sign, so the card names the date."""
    catalogue = trusted_card.load_catalogue()
    rig = _rig(tmp_path, on=True, ceiling=catalogue.WINDOW_CEILING_MINUTES)
    wc.main(["open", "--until-off", "--no-landing-cap", "--away"], folder=rig.home)
    rig.loop.tick()
    kind, details = rig.ask.asked[0]
    assert kind == "open_window_away" and details["minutes"] == wc.UNTIL_OFF_MINUTES
    assert re.fullmatch(r"[A-Z][a-z]{2} \d{4}-\d{2}-\d{2}", details["ends"]), details["ends"]
    _title, body = catalogue.render(kind, {name: str(value) for name, value in details.items()})
    assert f"{wc.UNTIL_OFF_MINUTES} minute(s), until {details['ends']}" in body
    opened = rig.window.opened
    assert opened is not None and opened.minutes == wc.UNTIL_OFF_MINUTES and opened.away


def test_your_away_request_shows_the_away_card_and_is_recorded_as_away(tmp_path: Path) -> None:
    rig = _rig(tmp_path, on=True)
    wc.main(["open", "--minutes", "1440", "--no-landing-cap", "--away"], folder=rig.home)
    rig.loop.tick()
    kind, details = rig.ask.asked[0]
    assert kind == "open_window_away" and details["minutes"] == 1440 and details["cap"] == "with no limit on how many"
    opened = rig.window.opened
    assert opened is not None and opened.away and opened.max_landings is None and opened.minutes == 1440
    first = rig.record.events()[0]
    assert first["name"] == "window_opened" and first["away"] is True and first["max_landings"] is None
    assert rig.status()["window"]["away"] is True
    assert "KEEPS LANDING while your PC is locked or you are away" in wc.status_text(rig.home)
    assert "landed (no limit)" in wc.status_text(rig.home)


def test_an_away_request_on_a_pc_that_did_not_turn_it_on_asks_nothing(tmp_path: Path) -> None:
    rig = _rig(tmp_path, on=False)
    wc.main(["open", "--minutes", "600", "--away"], folder=rig.home)
    rig.loop.tick()
    assert rig.ask.asked == [] and rig.window.opened is None
    assert any("off on this PC" in note for note in rig.loop.notes)


def test_a_chosen_number_is_on_the_card_and_holds(tmp_path: Path) -> None:
    rig = _rig(tmp_path, on=False)
    wc.main(["open", "--minutes", "240", "--max-landings", "5"], folder=rig.home)
    rig.loop.tick()
    kind, details = rig.ask.asked[0]
    assert kind == "open_window" and details["cap"] == "at most 5" and details["minutes"] == 240
    assert rig.window.opened is not None and rig.window.opened.max_landings == 5 and not rig.window.opened.away


@pytest.mark.parametrize("garbled", [{"max_landings": "5"}, {"max_landings": 2.0}, {"away": "yes"}, {"away": 1}])
def test_a_garbled_choice_is_removed_unasked(tmp_path: Path, garbled: dict) -> None:
    rig = _rig(tmp_path, on=True)
    wc.request(rig.home, "open", minutes=60, **garbled)
    rig.loop.tick()
    assert rig.ask.asked == [] and rig.window.opened is None


@pytest.mark.parametrize("minutes", [0, -1, wc.UNTIL_OFF_MINUTES + 1])
def test_the_control_rejects_invalid_minutes_before_asking(tmp_path: Path, capsys, minutes: int) -> None:
    with pytest.raises(SystemExit) as error:
        wc.main(["open", "--minutes", str(minutes)], folder=tmp_path)
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert f"--minutes takes a number from 1 to {wc.UNTIL_OFF_MINUTES}" in captured.err
    assert "Asked." not in captured.out
    assert not (tmp_path / "requests").exists()


@pytest.mark.parametrize("minutes", [1, wc.UNTIL_OFF_MINUTES])
def test_the_control_accepts_both_duration_boundaries(tmp_path: Path, minutes: int) -> None:
    assert wc.main(["open", "--minutes", str(minutes)], folder=tmp_path) == 0
    requests = list((tmp_path / "requests").glob("*.json"))
    assert len(requests) == 1
    assert json.loads(requests[0].read_text(encoding="utf-8"))["minutes"] == minutes


def test_the_control_takes_a_number_or_no_cap_never_both(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        wc.main(["open", "--max-landings", "5", "--no-landing-cap"], folder=tmp_path)
    with pytest.raises(SystemExit):
        wc.main(["open", "--max-landings", "0"], folder=tmp_path)
    assert not (tmp_path / "requests").exists() or not list((tmp_path / "requests").glob("*.json"))
