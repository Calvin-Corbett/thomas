"""check.run takes a per-test timeout, so a hanging test fails fast with its stack (2026-10-27).

On 2026-10-26 a Build team's check.run hit the 10-minute tool limit twice on files that held hanging tests, and
nothing said which test hung; told to pass --timeout=90, it was refused and fell back to the shell.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from thomas.tools import check_run
from thomas.tools.check_run import CheckRefused, CheckRunTool

_HANGS = "import time\n\ndef test_hangs():\n    time.sleep(120)\n"


@pytest.mark.parametrize("value", ["1", "90", "600"])
def test_a_per_test_timeout_up_to_the_tools_own_limit_is_taken(tmp_path: Path, value: str) -> None:
    (tmp_path / "test_x.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    argv = check_run.build_argv("pytest", ["test_x.py", f"--timeout={value}"], tmp_path)
    assert f"--timeout={value}" in argv


@pytest.mark.parametrize("value", ["0", "601", "6000", "abc", "90s", "-5", ""])
def test_a_timeout_past_the_limit_or_not_a_number_is_refused(tmp_path: Path, value: str) -> None:
    (tmp_path / "test_x.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    with pytest.raises(CheckRefused, match="--timeout=N"):
        check_run.build_argv("pytest", ["test_x.py", f"--timeout={value}"], tmp_path)


def test_a_hanging_test_fails_in_seconds_and_names_itself(tmp_path: Path) -> None:
    (tmp_path / "test_hang.py").write_text(_HANGS, encoding="utf-8")
    started = time.monotonic()
    result = asyncio.run(
        CheckRunTool(tmp_path).safe_execute(
            {"check": "pytest", "args": ["-q", "-p", "no:cacheprovider", "test_hang.py", "--timeout=2"]}
        )
    )
    assert time.monotonic() - started < 60
    text = str(result.data)
    assert "test_hangs" in text and "Timeout" in text
