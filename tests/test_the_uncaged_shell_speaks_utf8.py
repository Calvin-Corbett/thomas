"""Outside the cage, the shell hands a Python child UTF-8, as the caged runner does.

``shell_spool`` decodes what a command prints as UTF-8, but a Python child writing
to a pipe on Windows writes the locale's cp1252: "é" came back as a replacement
character and "→" killed the child with ``UnicodeEncodeError``. The caged runner
(``scripts/cage/shell_runner.py``) has set ``PYTHONIOENCODING=utf-8`` since the
cage landed; the path taken when the cage is off now matches it.
"""

from __future__ import annotations

import asyncio
import shlex
import sys
from pathlib import Path

import pytest

from thomas.tools import shell as shell_tool


def test_a_python_child_prints_an_arrow_when_the_cage_is_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Posture straight from the module: this machine pins "required" for real.
    monkeypatch.setattr(shell_tool, "cage_posture", lambda: "off")
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    code = "print(chr(233)+chr(8594))"
    if sys.platform == "win32":
        if " " in sys.executable:
            pytest.skip("cmd.exe strips the outer quotes of a quoted interpreter path")
        command = f"{sys.executable} -c {code}"
    else:
        command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"

    result = asyncio.run(shell_tool.ShellTool(tmp_path).execute({"command": command}))

    assert result.ok, (result.error, result.data)
    assert "é→" in str(result.data)
