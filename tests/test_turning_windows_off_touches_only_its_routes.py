"""The windows row, off: ``GET /api/self/windows`` answers 404, a server started that way never loads it, nothing else moves.

The route lists what your windows landed, read from the folder the promoter writes. No page calls it. The words of the
row live in ``thomas/server/rows/default.toml``, and each sentence of them names the test below that shows it.

The row is ``thomas.server.rows.windows`` and its code is ``thomas.server.window_records``, and those names are how a
check finds this file when either changes.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import tomllib

from tests.row_off_fixture import ask_as_a_remote_caller, ask_from_another_machine, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

ROW = "windows"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {"GET /api/self/windows": "GET /api/self/windows"}
OWN_CODE = ("thomas.server.rows.windows", "thomas.server.window_records")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/self/windows"}

# The folder the promoter writes is a real one on this machine, and this test must not read it. A source that runs before
# the server starts makes a folder of that name look absent, so the route answers with an empty list.
NOT_THE_REAL_RECORD = """\
import pathlib

_is_dir = pathlib.Path.is_dir
pathlib.Path.is_dir = lambda self, *a, **k: False if "thomaswindow" in str(self).lower() else _is_dir(self, *a, **k)


def reading():
    return None


"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("windows-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder, reading=NOT_THE_REAL_RECORD)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("windows-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder, ahead=NOT_THE_REAL_RECORD)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def elsewhere(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("windows-elsewhere")
    started, found = ask_from_another_machine(ROW, list(ROUTES.values()), folder, ahead=NOT_THE_REAL_RECORD)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_the_route_answers_404_and_is_not_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_the_route_back_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == dict.fromkeys(ROUTES.values(), 200)


def test_turned_off_on_a_running_server_the_route_goes_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its route goes and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_the_route_asks_for_this_machine_and_not_for_the_token(remote: dict[str, Any]) -> None:
    """It was guarded by the machine alone and still is, so a caller on this machine is let in with no token at all.

    The test client is on this machine. The caller on another one is the next test, and it is refused with the token.
    """
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 200)
    assert remote["with_token"] == dict.fromkeys(ROUTES.values(), 200)


def test_a_caller_on_another_machine_is_refused_even_with_the_token(elsewhere: dict[str, Any]) -> None:
    """The route asks for a caller on this machine. The token is sent each time, so a 403 can only be that guard."""
    assert elsewhere["row"]["state"] == "active", elsewhere["row"]
    assert elsewhere["elsewhere"] == dict.fromkeys(ROUTES.values(), 403)
    assert elsewhere["here"] == dict.fromkeys(ROUTES.values(), 200)


def test_a_change_to_the_row_or_its_code_runs_its_proofs() -> None:
    for changed in ("thomas/server/rows/windows.py", "thomas/server/window_records.py"):
        chosen = select(ROOT, [changed]).files
        assert "tests/test_turning_windows_off_touches_only_its_routes.py" in chosen, changed
        assert "tests/test_thomas_shows_what_your_window_landed.py" in chosen, changed


def test_no_page_in_thomas_asks_for_the_list() -> None:
    """Nothing in the web layer, the extensions or the desktop shell names the address."""
    asked = [
        str(path.relative_to(ROOT))
        for folder in ("thomas/server/web", "extensions", "desktop", "apps")
        if (ROOT / folder).is_dir()
        for path in (ROOT / folder).rglob("*")
        if path.is_file()
        and path.suffix in {".js", ".html", ".mjs", ".ts", ".tsx"}
        and "api/self/windows" in _text(path)
    ]
    assert asked == []


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# The words, a sentence at a time. Each is shown by the test named beside it, in this file or in the one the row's code
# already had. A new, changed or dropped sentence fails here until the list has it with a test that shows it.
WORDS = {
    "about": {
        "Lets other programs read what each of your windows landed, newest first, up to the last 20: when it opened, "
        "how many minutes it was given, its pairing code, why it ended and every change it landed or undid.": (
            "test_the_windows_are_read_newest_first_with_what_each_landed",
            "test_turning_it_on_brings_the_route_back_without_a_restart",
        ),
        "It reads the records your windows keep and never writes to them.": (
            "test_the_windows_are_read_newest_first_with_what_each_landed",
        ),
        "Only a program on this computer can ask.": (
            "test_a_caller_on_another_machine_is_refused_even_with_the_token",
        ),
        "No page in Thomas shows this list.": ("test_no_page_in_thomas_asks_for_the_list",),
    },
    "off_means": {
        "While this is off, nothing you use changes, because no page in Thomas reads this list.": (
            "test_no_page_in_thomas_asks_for_the_list",
        ),
        "Other programs that ask for it are told there is no such address.": (
            "test_with_the_row_off_the_route_answers_404_and_is_not_listed",
        ),
        "The records of your windows are not touched, so the list is complete again as soon as this is turned on.": (
            "test_turning_it_on_brings_the_route_back_without_a_restart",
            "test_the_windows_are_read_newest_first_with_what_each_landed",
        ),
        "The Landed in line on a change's card in Chat comes from the change itself, not from this list, and carries on.": (
            "test_a_change_that_landed_in_your_window_says_so_and_names_no_card",
        ),
    },
    "stop_now": {
        "A request for the list that is still being answered will fail and may need sending again.": (
            "test_turned_off_on_a_running_server_the_route_goes_and_the_code_stays_loaded",
        ),
    },
}
FILES = (
    "test_turning_windows_off_touches_only_its_routes.py",
    "test_thomas_shows_what_your_window_landed.py",
)


def _row() -> dict[str, Any]:
    rows = tomllib.loads((ROOT / "thomas/server/rows/default.toml").read_text("utf-8"))["row"]
    return next(row for row in rows if row["id"] == ROW)


@pytest.mark.parametrize("field", ["about", "off_means", "stop_now"])
def test_every_sentence_of_the_words_names_the_test_that_shows_it(field: str) -> None:
    text = "".join((ROOT / "tests" / name).read_text("utf-8") for name in FILES)
    assert re.split(r"(?<=\.)\s+", _row()[field]) == list(WORDS[field])
    named = {name for names in WORDS[field].values() for name in names}
    assert {name for name in named if f"def {name}(" not in text} == set()
