"""The oldest Python the launchers accept is the one ``requires-python`` in pyproject.toml asks for.

The launchers decide whether a Python is usable before a venv exists, so they cannot
read the project's metadata; the number is written into them (the version probe, the
``py -3.x`` flags, the winget installs, the messages that name it). A bump in
pyproject.toml with no change there would send a stranger to a Python that pip then
refuses. This reads pyproject.toml (never writes it) and checks every place the
launchers state the floor, so the two cannot drift without a test failing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.launcher_powershell_support import ROOT, RUN_REPL, RUN_UI

PYPROJECT = ROOT / "pyproject.toml"
SHORTCUT = ROOT / "launch-thomas.vbs"


def floor_asked_for(pyproject_text: str) -> tuple[int, int]:
    """The ``>=X.Y`` bound of ``requires-python``; the launchers have no upper bound to keep."""
    declared = re.search(r'(?m)^requires-python\s*=\s*"([^"]+)"', pyproject_text)
    assert declared, "pyproject.toml has no requires-python"
    lower = re.search(r">=\s*(\d+)\.(\d+)", declared.group(1))
    assert lower, f"requires-python {declared.group(1)!r} has no '>=X.Y' bound the launchers can follow"
    return int(lower.group(1)), int(lower.group(2))


def disagreements(floor: tuple[int, int]) -> list[str]:
    """Every place the launchers, or their dialog, state a floor other than *floor*."""
    major, minor = floor
    found: list[str] = []
    for script in (RUN_UI, RUN_REPL):
        text = script.read_text(encoding="utf-8")
        probe = re.search(r"sys\.version_info\[:2\] >= \((\d+), (\d+)\)", text)
        if not probe or (int(probe.group(1)), int(probe.group(2))) != floor:
            found.append(f"{script.name}: the version probe does not ask for {major}.{minor}")
        named = {(int(a), int(b)) for a, b in re.findall(r"Python (\d+)\.(\d+) or newer", text)}
        if named != {floor}:
            found.append(f"{script.name}: messages name {sorted(named)}, not {floor}")
        flags = re.search(r"foreach \(\$flag in @\(([^)]*'-3'[^)]*)\)\)", text)
        versioned = [(int(a), int(b)) for a, b in re.findall(r"'-(\d+)\.(\d+)'", flags.group(1))] if flags else []
        if not versioned or min(versioned) != floor:
            found.append(f"{script.name}: the py launcher is asked for {sorted(versioned)}, the lowest is not {floor}")
    installs = [
        (int(a), int(b)) for a, b in re.findall(r"Python\.Python\.(\d+)\.(\d+)", RUN_UI.read_text(encoding="utf-8"))
    ]
    if not installs or min(installs) < floor:
        found.append(f"run-ui.ps1 installs Python {sorted(installs)} with winget, older than {floor}")
    shortcut = {
        (int(a), int(b)) for a, b in re.findall(r"Python (\d+)\.(\d+) or newer", SHORTCUT.read_text(encoding="utf-8"))
    }
    if shortcut != {floor}:
        found.append(f"launch-thomas.vbs names {sorted(shortcut)}, not {floor}")
    return found


def test_the_launchers_state_the_floor_pyproject_asks_for() -> None:
    floor = floor_asked_for(PYPROJECT.read_text(encoding="utf-8"))

    assert disagreements(floor) == []


@pytest.mark.parametrize(
    ("declared", "floor"),
    [('">=3.10"', (3, 10)), ('">=3.12,<4"', (3, 12)), ('">= 3.11"', (3, 11))],
)
def test_the_floor_is_read_from_the_lower_bound(declared: str, floor: tuple[int, int]) -> None:
    assert floor_asked_for(f"[project]\nrequires-python = {declared}\n") == floor


def test_a_bump_in_pyproject_with_no_change_in_the_launchers_is_caught() -> None:
    """Pretend pyproject.toml had asked for 3.12: the check must find the places that still say 3.10 and 3.11."""
    bumped = floor_asked_for('[project]\nrequires-python = ">=3.12"\n')
    found = "\n".join(disagreements(bumped))

    for where in ("run-ui.ps1: the version probe", "run-repl.ps1: the version probe", "run-ui.ps1: messages name"):
        assert where in found, found
    assert "the lowest is not (3, 12)" in found and "run-ui.ps1 installs Python" in found, found
    assert "launch-thomas.vbs names" in found, found
