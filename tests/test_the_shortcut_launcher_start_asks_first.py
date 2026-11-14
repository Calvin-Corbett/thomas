"""The Thomas.vbs launcher asks before a first-time setup, and before it starts a second start.

When a connection to Thomas's port is refused the launcher starts Thomas the way launch-thomas.vbs
does. run-ui.ps1 does more than start a server when one of the three files it works from is
missing (.venv\\Scripts\\python.exe, .venv\\pyvenv.cfg, runtime\\setup\\last_setup.txt): it builds
the Python environment again, deleting an incomplete one, and runs setup.ps1, which can install
software and rewrite thomas.toml. A click that could lead there asks first, defaults to No, and
starts nothing on any other answer. When all three are there it is started hidden; run-ui.ps1
can still do several things on that path without asking (install Python, pip install, write the
thomas:// link, start Ollama, and, when the server does not come up healthy, start Boot Doctor),
which the README and changelog say.

It also does not trust a run-ui.ps1 that is still in the process list: run-ui.ps1 normally
starts a detached server, opens your browser and exits, so what lingers is a PowerShell window
left open (run-ui.cmd keeps one). Only a young one is treated as a start under way, and even
then you are asked, not locked out.

The launcher runs with its shell, file system, process list and message boxes replaced by fakes
(tests/launcher_script_host_support.py): nothing is launched, installed or shown.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.launcher_script_host_support import (
    CSCRIPT,
    DESKTOP_PS1,
    ELECTRON,
    EVERYTHING,
    LAUNCH,
    RUN_UI,
    RUNNING,
    SET_UP,
    SETUP_DONE,
    VENV,
    VENV_CFG,
    wrong_scenarios,
)

pytestmark = pytest.mark.skipif(CSCRIPT is None, reason="needs Windows Script Host")

BLOCKED = {"fail": "electron", "server": "refused"}  # the shell is installed and Windows will not run it
NO_SHELL = {"server": "refused"}  # the shell was never installed
NEVER_SET_UP = [ELECTRON, LAUNCH, RUN_UI]
NO_MARKER = [ELECTRON, LAUNCH, RUN_UI, VENV, VENV_CFG]  # a Python environment, but run-ui.ps1 would still run setup
NO_VENV = [ELECTRON, LAUNCH, RUN_UI, SETUP_DONE]  # a setup record, but run-ui.ps1 would create the environment
NO_CFG = [ELECTRON, LAUNCH, RUN_UI, VENV, SETUP_DONE]  # run-ui.ps1 would delete this .venv and build it again
STARTED_HIDDEN = ["electron", "launch-thomas(style=0)", "popup:starting+shell-note", "exit 0"]
ASKED_AND_DECLINED = ["electron", "msgbox:setup(default No)", "popup:declined", "exit 0"]
ASKED_AND_ACCEPTED = ["electron", "msgbox:setup(default No)", "run-ui(style=1, stays open)", "exit 0"]

SCENARIOS: dict[str, tuple[dict, list[str]]] = {
    "set up already, nothing serving: started hidden, announced, no question asked": (
        {**BLOCKED, "exists": EVERYTHING},
        STARTED_HIDDEN,
    ),
    "no shell, install declined, set up already: started hidden": (
        {**NO_SHELL, "exists": [DESKTOP_PS1, *SET_UP]},
        ["msgbox:shell(default No)", "launch-thomas(style=0)", "popup:starting", "exit 0"],
    ),
    "never set up, asked, declined: nothing is installed or started": (
        {**BLOCKED, "exists": NEVER_SET_UP},
        ASKED_AND_DECLINED,
    ),
    "never set up, asked, accepted: the install is shown, and stays if it fails": (
        {**BLOCKED, "exists": NEVER_SET_UP, "answers": {"setup": 6}},
        ASKED_AND_ACCEPTED,
    ),
    "a Python environment but no setup record, declined: run-ui.ps1 would set up, so nothing starts": (
        {**BLOCKED, "exists": NO_MARKER},
        ASKED_AND_DECLINED,
    ),
    "a Python environment but no setup record, accepted: shown, never hidden": (
        {**BLOCKED, "exists": NO_MARKER, "answers": {"setup": 6}},
        ASKED_AND_ACCEPTED,
    ),
    "a setup record but no Python environment, declined: run-ui.ps1 would create one, so nothing starts": (
        {**BLOCKED, "exists": NO_VENV},
        ASKED_AND_DECLINED,
    ),
    "python.exe and a setup record but no pyvenv.cfg, declined: run-ui.ps1 would delete .venv, so nothing starts": (
        {**BLOCKED, "exists": NO_CFG},
        ASKED_AND_DECLINED,
    ),
    "python.exe and a setup record but no pyvenv.cfg, accepted: shown, never hidden": (
        {**BLOCKED, "exists": NO_CFG, "answers": {"setup": 6}},
        ASKED_AND_ACCEPTED,
    ),
    "no shell and install declined, then never set up and declined: both refusals are honoured": (
        {**NO_SHELL, "exists": [DESKTOP_PS1, LAUNCH, RUN_UI]},
        ["msgbox:shell(default No)", "msgbox:setup(default No)", "popup:declined", "exit 0"],
    ),
    "a start began five minutes ago: asked before another, and No starts nothing": (
        {**BLOCKED, "exists": EVERYTHING, "procs": [("cmd /c dir", 1), (RUNNING, 5)]},
        ["electron", "msgbox:again(default No)", "exit 0"],
    ),
    "a start began five minutes ago, Yes: set up already, so it starts hidden": (
        {**BLOCKED, "exists": EVERYTHING, "procs": [(RUNNING, 5)], "answers": {"again": 6}},
        ["electron", "msgbox:again(default No)", "launch-thomas(style=0)", "popup:starting+shell-note", "exit 0"],
    ),
    "a start began five minutes ago, Yes, never set up: the setup question still comes, and No starts nothing": (
        {**BLOCKED, "exists": NEVER_SET_UP, "procs": [(RUNNING, 5)], "answers": {"again": 6}},
        ["electron", "msgbox:again(default No)", "msgbox:setup(default No)", "popup:declined", "exit 0"],
    ),
    "a console left open from two hours ago is not a start under way": (
        {**BLOCKED, "exists": EVERYTHING, "procs": [(RUNNING + " -NoExit", 120)]},
        STARTED_HIDDEN,
    ),
    "a shell that only mentions the script is not a start under way": (
        {
            **BLOCKED,
            "exists": EVERYTHING,
            "procs": [('powershell -Command "Get-Content C:\\fake\\scripts\\run-ui.ps1"', 1)],
        },
        STARTED_HIDDEN,
    ),
    "a run-ui of another checkout is not a start under way": (
        {**BLOCKED, "exists": EVERYTHING, "procs": [(RUNNING.replace("C:\\fake", "C:\\elsewhere"), 1)]},
        STARTED_HIDDEN,
    ),
    "a start time that cannot be read is not a start under way (an unreadable list never blocks a start)": (
        {**BLOCKED, "exists": EVERYTHING, "procs": [(RUNNING, "not a date"), (RUNNING, "")]},
        STARTED_HIDDEN,
    ),
    "a process list that cannot be read is not a start under way either": (
        {**BLOCKED, "fail": "electron,wmi", "exists": EVERYTHING, "procs": [(RUNNING, 1)]},
        STARTED_HIDDEN,
    ),
}


def test_a_click_that_could_install_software_asks_first_and_a_start_under_way_is_not_doubled(tmp_path: Path) -> None:
    wrong = wrong_scenarios(tmp_path, SCENARIOS)

    assert not wrong, "\n" + "\n".join(wrong)


def test_a_start_is_dated_as_the_launcher_runs_not_as_this_file_is_imported() -> None:
    """In a long run this file is imported long before it runs: 26 minutes in, five minutes ago was no longer young."""
    ages = [age for scenario, _ in SCENARIOS.values() for _, age in scenario.get("procs", [])]

    assert [age for age in ages if isinstance(age, int)], "the scenarios still say how long ago"
    assert not [age for age in ages if isinstance(age, str) and age[:4].isdigit()], "a date fixed at import"


def test_the_files_the_launcher_checks_are_the_ones_run_ui_works_from() -> None:
    """The launcher and run-ui.ps1 must agree on what 'set up' means, or one of them changes the machine unasked."""
    root = Path(__file__).resolve().parents[1]
    run_ui = (root / "scripts" / "run-ui.ps1").read_text(encoding="utf-8").replace("\\\\", "\\")
    start = run_ui.index("function Test-VenvValid")
    valid = run_ui[start : run_ui.index("\n}\n", start)]

    assert SETUP_DONE in run_ui, "run-ui.ps1 no longer looks for this setup record"
    first_run = run_ui[run_ui.index("function Invoke-FirstRunQuickSetup") :]
    guard = first_run.index("if (Test-Path $statusPath) {")
    assert "return" in first_run[guard : first_run.index("\n  }\n", guard)], (
        "a setup record no longer ends first-run setup"
    )
    assert '"pyvenv.cfg"' in valid and '"Scripts\\python.exe"' in valid, "run-ui.ps1 judges the environment differently"
    assert "(Test-Path $cfg) -and (Test-Path $py)" in valid
