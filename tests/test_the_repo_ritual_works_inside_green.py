"""The repo's own start-up ritual works inside green.

AGENTS.md tells every agent to run `python scripts/crew/workboard/message.py --list`
at session start, and Thomas's self-development worker obeys it. Inside green it
failed twice over (measured 2026-09-23, exec-94683399cf16):

* the cage account has no agent identity, so `--list` refused ("pass --agent, set
  AGENT_ID/THOMAS_AGENT_ID, or use --all");
* `--list --all` printed "PASS", then crashed on a "→" and exited 1, because a
  caged Python writes its output in cp1252 while the runner reads it as UTF-8.

A failed call that is never repeated successfully counts as unrecovered, so the
completion review rejected a self-fix that had written and verified its change.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
from scripts.cage import shell_runner

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the caged shell is cmd.exe")

REPO = Path(__file__).resolve().parents[1]
_WHO = f"\"{sys.executable}\" -c \"import os; print(os.environ.get('THOMAS_AGENT_ID'), os.environ.get('AGENT_ID'))\""


def _run(command: str, cwd: Path) -> dict:
    return shell_runner.run_command({"id": "ritual", "command": command, "cwd": str(cwd), "timeout_s": 120})


def _green(tmp_path: Path) -> Path:
    work = tmp_path / "green" / "work" / "exec-ritual"
    work.mkdir(parents=True)
    return work


def test_a_caged_python_can_print_any_character(tmp_path: Path) -> None:
    result = _run(f'"{sys.executable}" -c "print(chr(0x2192))"', tmp_path)

    assert result["returncode"] == 0, result
    assert "→" in result["output"]


def test_a_command_in_green_runs_as_a_named_agent(tmp_path: Path, monkeypatch) -> None:
    for key in ("THOMAS_AGENT_ID", "AGENT_ID"):
        monkeypatch.delenv(key, raising=False)

    in_green = _run(_WHO, _green(tmp_path))
    elsewhere = _run(_WHO, tmp_path)

    assert in_green["output"].split() == ["thomas-green", "thomas-green"], in_green
    assert elsewhere["output"].split() == ["None", "None"], elsewhere


def test_the_mandated_inbox_check_passes_in_green(tmp_path: Path, monkeypatch) -> None:
    for key in ("THOMAS_AGENT_ID", "AGENT_ID", "THOMAS_AGENT_SESSION_ID", "AGENT_SESSION_ID"):
        monkeypatch.delenv(key, raising=False)
    work = _green(tmp_path)
    for folder in ("crew", "forge"):
        shutil.copytree(
            REPO / "scripts" / folder, work / "scripts" / folder, ignore=shutil.ignore_patterns("__pycache__")
        )
    monkeypatch.setenv("PYTHONPATH", str(REPO) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    board = work / "plans" / "thomas" / "WORKBOARD.md"
    board.parent.mkdir(parents=True)
    board.write_text("# Workboard\n\n## Agent Message Traffic\n\n- none\n", encoding="utf-8")
    message_tool = work / "scripts" / "crew" / "workboard" / "message.py"

    result = _run(f'"{sys.executable}" "{message_tool}" --list', work)

    assert result["returncode"] == 0, result["output"][-600:]
    assert "Workboard message tool: PASS" in result["output"]
