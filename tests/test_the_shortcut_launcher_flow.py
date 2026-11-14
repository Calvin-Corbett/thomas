"""What the Thomas.vbs launcher does, in which order, when the shell or the browser window is the question.

The generated launcher runs with its shell, file system, process list and message boxes replaced
by fakes (tests/launcher_script_host_support.py), so nothing is launched, installed or shown.
What it does before it starts a server, and what it asks first, is in
test_the_shortcut_launcher_start_asks_first.py.

The orders that matter here: a shell Windows refuses falls through to the browser window and
says why; nothing is started over a Thomas that is merely busy (run-ui.ps1 stops a Thomas on its
port); the caged launcher does not start a server as you, and a port the everyday launcher does
not serve gets no automatic start.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import thomas_app

from tests.launcher_script_host_support import (
    CSCRIPT,
    DESKTOP_PS1,
    EVERYTHING,
    LAUNCH,
    RUN_UI,
    SET_UP,
    wrong_scenarios,
)

pytestmark = pytest.mark.skipif(CSCRIPT is None, reason="needs Windows Script Host")

ELECTRON_BLOCKED = {"fail": "electron", "exists": EVERYTHING}
SCENARIOS: dict[str, tuple[dict, list[str]]] = {
    "the shell starts: nothing else happens": (
        {"server": "refused", "exists": EVERYTHING},
        ["electron", "exit 0"],
    ),
    "a shell Windows refuses, Thomas answering: the app window opens and says why": (
        {**ELECTRON_BLOCKED, "server": "up"},
        ["electron", "msedge", "popup:shell-note", "END", "exit 0"],
    ),
    "a shell Windows refuses, Thomas too busy to answer: nothing is started over it": (
        {**ELECTRON_BLOCKED, "server": "busy"},
        ["electron", "msedge", "popup:shell-note", "END", "exit 0"],
    ),
    "no shell installed, install accepted: the shell installer runs and nothing else": (
        {"exists": [DESKTOP_PS1, *SET_UP], "server": "refused", "answers": {"shell": 6}},
        ["msgbox:shell(default No)", "install-shell", "exit 0"],
    ),
    "nothing installed, Thomas answering: the app window opens, with no note about a shell": (
        {"exists": [], "server": "up"},
        ["msedge", "END", "exit 0"],
    ),
    "launch-thomas.vbs missing: no start is possible, the window opens": (
        {"exists": [DESKTOP_PS1, RUN_UI, *SET_UP[2:]], "server": "refused"},
        ["msgbox:shell(default No)", "msedge", "END", "exit 0"],
    ),
    "run-ui.ps1 missing: no start is possible, the window opens": (
        {"exists": [DESKTOP_PS1, LAUNCH, *SET_UP[2:]], "server": "refused"},
        ["msgbox:shell(default No)", "msedge", "END", "exit 0"],
    ),
    "neither Edge nor Chrome: the default browser gets the address": (
        {"fail": "msedge,chrome", "exists": [], "server": "up"},
        ["msedge", "chrome", "url", "END", "exit 0"],
    ),
    "caged, shell refused: its task is run, never a server as you": (
        {**ELECTRON_BLOCKED, "caged": True, "port": thomas_app.CAGED_PORT, "server": "refused"},
        ["electron", "schtasks", "msedge", "popup:shell-note", "END", "exit 0"],
    ),
    "caged on the everyday port, shell refused: still never a server as you": (
        {**ELECTRON_BLOCKED, "caged": True, "server": "refused"},
        ["electron", "schtasks", "msedge", "popup:shell-note", "END", "exit 0"],
    ),
    "a port the everyday launcher does not serve gets no automatic start": (
        {**ELECTRON_BLOCKED, "port": 9001, "server": "refused"},
        ["electron", "msedge", "popup:shell-note", "END", "exit 0"],
    ),
}


def test_the_launcher_acts_in_the_right_order_for_every_state_of_the_machine(tmp_path: Path) -> None:
    wrong = wrong_scenarios(tmp_path, SCENARIOS)

    assert not wrong, "\n" + "\n".join(wrong)
