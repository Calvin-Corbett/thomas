"""Shared pieces of the tray launcher tests.

Copies functions out of scripts/start-tray-agent.ps1 and runs them under Windows
PowerShell 5.1 with the process, socket and Task Scheduler cmdlets replaced by
stand-ins that record what they were asked to do. The launcher itself is never run.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "start-tray-agent.ps1"

needs_powershell = pytest.mark.skipif(
    sys.platform != "win32" or not shutil.which("powershell"), reason="needs Windows PowerShell"
)


def script_source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def script_default_port() -> int:
    """The launcher's own default port. Tests use it so they can name the tray agent's
    default port without a literal, and so the two defaults are checked against each other."""
    match = re.search(r"\[int\]\$Port = (\d+)", script_source())
    assert match, "the launcher must declare a default $Port"
    return int(match.group(1))


def functions(*names: str) -> str:
    """The named top-level functions, copied verbatim out of the launcher."""
    source = script_source()
    found = []
    for name in names:
        match = re.search(rf"^function {re.escape(name)} \{{.*?^\}}\n", source, re.S | re.M)
        assert match, f"{name} must be a top-level function"
        found.append(match.group(0))
    return "\n".join(found)


def run_powershell(tmp_path: Path, script: str) -> list[str]:
    """Run `script` under Windows PowerShell 5.1; return the payloads of its `RESULT:` lines."""
    probe = tmp_path / "probe.ps1"
    probe.write_text(script, encoding="utf-8-sig")
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(probe)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return [line[len("RESULT:") :] for line in done.stdout.splitlines() if line.startswith("RESULT:")]
