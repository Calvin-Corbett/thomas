"""The pipeline canary starts nothing that opens a window over your desktop.

You wrote on 2026-11-04 that console windows kept popping up and interrupting your games. The canary runs
from pythonw every five minutes; four of its git and python calls started without CREATE_NO_WINDOW, and a
console program started from pythonw gets a console window of its own. Every call it makes now says no window.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CANARY = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_canary"
LAUNCHERS = {"run", "Popen", "call", "check_call", "check_output"}


def _launches(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in LAUNCHERS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]


@pytest.mark.parametrize("path", sorted(CANARY.glob("*.py")), ids=lambda p: p.name)
def test_every_program_the_canary_starts_opens_no_window(path: Path) -> None:
    bare = [call.lineno for call in _launches(path) if not any(k.arg == "creationflags" for k in call.keywords)]
    assert bare == [], f"{path.name} starts a program that can open a console window, at line(s) {bare}"
