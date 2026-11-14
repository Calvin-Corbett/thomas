"""No caged process outlives the green it ran in, or the command that timed out.

Measured live 2026-09-22 (exec-8ef69b69fb68): the self-fix run ended, but a
Python process it had started in the caged shell was still running as
thomas-agent with green as its working folder -- so green could not be removed
("being used by another process"), and a process running agent code had simply
outlived its task. Killing a command's cmd.exe does not kill what cmd.exe
started. Now every caged command runs in a Windows job: a green's commands share
that green's job, ended when the green is settled, and a command that times out
takes its whole job with it.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from scripts.cage import shell_runner

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows job objects")

_SLEEPER = f'"{sys.executable}" -c "import time; time.sleep(60)"'


def _removable(folder: Path, *, within_s: float = 5.0) -> bool:
    deadline = time.time() + within_s
    while time.time() < deadline:
        try:
            shutil.rmtree(folder)
            return True
        except OSError:
            time.sleep(0.2)
    return False


def test_ending_a_green_ends_everything_it_left_running(tmp_path: Path) -> None:
    work = tmp_path / "green" / "work" / "exec-left"
    work.mkdir(parents=True)

    # `start ""`: start reads the first quoted word as a window title.
    started = shell_runner.run_command({"id": "a", "command": f'start "" /b {_SLEEPER}', "cwd": str(work)})
    assert started["outcome"] == "ok"
    assert not _removable(work, within_s=1.0), "the ruler: a process left in green holds it"

    ended = shell_runner.run_command({"id": "b", "action": "end_green", "green": "exec-left"})

    assert ended["outcome"] == "ok"
    assert _removable(work)


def test_a_timed_out_command_takes_what_it_started_with_it(tmp_path: Path) -> None:
    work = tmp_path / "somewhere"
    work.mkdir()
    spawner = (
        f'"{sys.executable}" -c "import subprocess, sys, time; '
        f"subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)\""
    )

    began = time.monotonic()
    result = shell_runner.run_command({"id": "c", "command": spawner, "cwd": str(work), "timeout_s": 2})

    assert result["outcome"] == "timeout"
    # The ruler: before jobs, the runner killed cmd.exe and then waited on the
    # output pipe the surviving grandchild still held -- the full 60 seconds.
    assert time.monotonic() - began < 15
    assert _removable(work, within_s=2.0)


def test_a_request_that_fails_is_answered_and_not_retried_forever(tmp_path: Path, monkeypatch) -> None:
    inbox, outbox = tmp_path / "inbox", tmp_path / "outbox"
    inbox.mkdir()
    outbox.mkdir()
    (inbox / "r1.json").write_text('{"id": "r1", "command": "echo hi", "cwd": "x"}', encoding="utf-8")

    def boom(_request: dict) -> dict:
        raise PermissionError("Access is denied")

    monkeypatch.setattr(shell_runner, "run_command", boom)

    shell_runner.serve_once(inbox, outbox)

    assert not (inbox / "r1.json").exists()
    assert "Access is denied" in (outbox / "r1.json").read_text(encoding="utf-8")
