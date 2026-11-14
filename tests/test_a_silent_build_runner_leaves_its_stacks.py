"""A Build runner that goes silent leaves every thread's stack where the log export finds it.

On 2026-09-27 two Build runs went quiet after their final reply and stayed that way for an hour: no child process,
no network connection, no CPU, and nothing said where they were waiting, so they could only be stopped blind. A
runner now writes all its threads' stacks to ``<logs>/thomas.log.runner-<pid>.stacks`` on a timer; the log export
serves every ``thomas.log*`` file. A runner that exits normally removes its file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from thomas.forge.anvil import forge_code_runner

CHILD = """
import sys, time
from pathlib import Path
from thomas.forge.anvil import forge_code_runner
path = forge_code_runner.record_stacks_while_running(Path(sys.argv[1]), every_s=0.3)
def waiting_for_something_that_never_comes():
    time.sleep(1.2)
waiting_for_something_that_never_comes()
print(path.read_text(encoding="utf-8"))
"""


def test_a_running_runner_writes_its_stacks_and_a_clean_exit_removes_them(tmp_path: Path) -> None:
    logs = tmp_path / "logs"

    done = subprocess.run([sys.executable, "-c", CHILD, str(logs)], capture_output=True, text=True, timeout=60)

    assert done.returncode == 0, done.stderr
    assert "waiting_for_something_that_never_comes" in done.stdout  # the stack names where it waits
    assert list(logs.glob("thomas.log.runner-*.stacks")) == []  # a clean exit leaves nothing behind


def test_the_runner_records_its_stacks_before_any_agent_work(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(forge_code_runner, "handle_console_ctrl_c", lambda: calls.append("ctrl_c") or True)
    monkeypatch.setattr(forge_code_runner, "record_stacks_while_running", lambda: calls.append("stacks"))
    monkeypatch.setattr(forge_code_runner, "python_tools_on_path", lambda: calls.append("path"))
    monkeypatch.setattr("thomas.tools.filesystem.anchor_runtime_protection", lambda _root: None)

    forge_code_runner.prepare_runner_process()

    assert calls[:2] == ["ctrl_c", "stacks"]
