"""Every caller of the task manager passes only arguments it accepts.

From 2026-09-09 chat's ``_send_task`` passed ``output_format=`` and
``required_tools=`` to ``start_background_delegation``, whose signature has
neither and no ``**kwargs``. Every hand-off raised ``TypeError`` and the
reasoning specialist reported "Task hand-off failed", so no task from chat
reached the task manager. No test called the real function: the callers and the
function drifted apart silently.

This reads every call site in ``thomas/`` and binds its keywords against the
real signature, so the next half-applied change fails here instead.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from thomas.server.chat_delegation import start_background_delegation

_REPO = Path(__file__).resolve().parents[1]
_TARGET = "start_background_delegation"


def _call_sites() -> list[tuple[Path, ast.Call]]:
    sites: list[tuple[Path, ast.Call]] = []
    for path in sorted((_REPO / "thomas").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if _TARGET not in source:
            continue
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == _TARGET:
                sites.append((path, node))
    return sites


def test_the_live_chat_route_is_among_the_call_sites() -> None:
    files = {path.relative_to(_REPO).as_posix() for path, _ in _call_sites()}
    assert "thomas/server/routes/chat_v2.py" in files


def test_every_call_passes_only_keywords_the_task_manager_accepts() -> None:
    accepted = set(inspect.signature(start_background_delegation).parameters)
    problems = []
    for path, call in _call_sites():
        for keyword in call.keywords:
            if keyword.arg is not None and keyword.arg not in accepted:
                problems.append(f"{path.relative_to(_REPO).as_posix()}:{call.lineno} passes {keyword.arg}=")
    assert problems == [], "start_background_delegation() does not accept: " + "; ".join(problems)
