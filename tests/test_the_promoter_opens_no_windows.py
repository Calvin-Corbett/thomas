"""The self-change promoter opens no windows on your screen.

The promoter runs as you, under pythonw.exe, which has no console, so every console
program it starts without CREATE_NO_WINDOW gets a console window of its own. On
2026-09-23 the first live promotion ran its git and PowerShell checks for about
thirty seconds, and you reported your screen "being spammed with ghost windows
from thomas".
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from scripts.cage import writer_audit

from tests.test_a_self_fix_lands_only_when_you_approve import Asker, _promoter, _submit, blue, pins  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != "nt", reason="console windows are a Windows matter")

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REPO = Path(__file__).resolve().parents[1]


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    calls: list[tuple[str, int]] = []
    real = subprocess.run

    def run(args, *rest, **kwargs):
        calls.append((str(args[0] if isinstance(args, list) else args), int(kwargs.get("creationflags", 0))))
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_a_whole_promotion_starts_nothing_with_a_window(blue: Path, pins: Path, monkeypatch) -> None:  # noqa: F811
    sub = _submit(blue, "exec-quiet", {"thomas/fix_me.py": "VALUE = 2\n"})
    calls = _spy(monkeypatch)

    outcome = _promoter(blue, pins, Asker(True)).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert calls, "the promotion ran no commands, so this test proves nothing"
    windowed = [program for program, flags in calls if not flags & NO_WINDOW]
    assert not windowed, f"{len(windowed)} of {len(calls)} commands would open a window: {windowed[:5]}"


def test_the_writer_audit_starts_powershell_without_a_window(monkeypatch) -> None:
    calls = _spy(monkeypatch)

    writer_audit.current_writers(REPO)

    assert calls and all(flags & NO_WINDOW for _program, flags in calls), calls
