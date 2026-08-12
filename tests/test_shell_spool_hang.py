"""CAP-003 L2: spool complete output + streaming hang detection with kill-and-retry.

Proves:
- A process that goes output-idle while still running is detected as hung,
  its process tree is killed (evidence: recorded killed pid + the run returns
  promptly instead of waiting out the child's sleep), and it is retried
  automatically with per-attempt hang accounting.
- A retry that succeeds on the second attempt yields a completed result while
  keeping the first hang on record.
- Output larger than the 100k inline truncation cap is fully present in the
  on-disk spool file, whose path is included in the tool result payload.
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
from pathlib import Path

from thomas.tools.shell import ShellTool
from thomas.tools.shell_spool import (
    OUTCOME_COMPLETED,
    OUTCOME_HUNG,
    run_spooled_command,
)

HANG_SCRIPT = "import time\nprint('started', flush=True)\ntime.sleep(60)\n"

# Hangs on the first run (no flag file yet), succeeds on the second.
FLAKY_SCRIPT = (
    "import sys, time\n"
    "from pathlib import Path\n"
    "flag = Path(sys.argv[1])\n"
    "if flag.exists():\n"
    "    print('second-run-ok', flush=True)\n"
    "else:\n"
    "    flag.write_text('x')\n"
    "    print('first-run-hangs', flush=True)\n"
    "    time.sleep(60)\n"
)

BIG_OUTPUT_SCRIPT = "for _ in range(3000):\n    print('A' * 50)\n"


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_hang_detected_killed_and_retried(tmp_path: Path) -> None:
    script = _script(tmp_path, "hang.py", HANG_SCRIPT)

    started = time.monotonic()
    result = run_spooled_command(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        timeout=30.0,
        idle_timeout=1.0,
        hang_retries=1,
        spool_dir=tmp_path / "spool",
    )
    elapsed = time.monotonic() - started

    assert result.outcome == OUTCOME_HUNG
    assert result.attempts == 2, "one automatic retry after the first hang"
    assert len(result.hang_events) == 2, "each hung attempt records evidence"
    for event in result.hang_events:
        assert event.idle_seconds >= 1.0, "idle window elapsed before the kill"
        assert event.killed_pid > 0, "killed pid recorded"
    assert result.hang_events[0].attempt == 1
    assert result.hang_events[1].attempt == 2
    # Streaming worked: the pre-hang output was captured before the kill.
    assert "started" in result.stdout
    # Kill actually happened: without it, each attempt sleeps 60s.
    assert elapsed < 20, f"process tree not killed promptly (took {elapsed:.1f}s)"
    # Spool file kept everything, including the retry marker between attempts.
    spool_text = Path(result.spool_path).read_text(encoding="utf-8")
    assert spool_text.count("started") == 2
    assert "retry attempt 2 after hang" in spool_text


def test_hang_retry_succeeds_on_second_attempt(tmp_path: Path) -> None:
    script = _script(tmp_path, "flaky.py", FLAKY_SCRIPT)
    flag = tmp_path / "ran-once.flag"

    result = run_spooled_command(
        [sys.executable, str(script), str(flag)],
        cwd=str(tmp_path),
        timeout=30.0,
        idle_timeout=1.0,
        hang_retries=1,
        spool_dir=tmp_path / "spool",
    )

    assert result.outcome == OUTCOME_COMPLETED
    assert result.exit_code == 0
    assert result.attempts == 2
    assert len(result.hang_events) == 1, "first attempt's hang stays on record"
    assert result.hang_events[0].attempt == 1
    assert "second-run-ok" in result.stdout


def test_shell_tool_reports_hang_evidence(tmp_path: Path) -> None:
    """End-to-end through ShellTool (cmd/bash wrapper => real tree kill)."""
    script = _script(tmp_path, "hang.py", HANG_SCRIPT)
    tool = ShellTool(tmp_path, idle_timeout=1.0, hang_retries=1)

    result = asyncio.run(tool.execute({"command": f"{sys.executable} {script}"}))

    assert result.ok is False
    assert result.error is not None
    assert "hung" in result.error.lower()
    assert "killed pid" in result.error
    assert "attempts 2" in result.error
    assert result.data is not None
    assert "[spool: " in result.data
    assert re.search(r"\[hang-retry: attempts=2, last_idle=[\d.]+s, killed_pid=\d+\]", result.data)


def test_spool_file_holds_complete_output_beyond_inline_cap(tmp_path: Path) -> None:
    """Output above the 100k inline cap is truncated inline but complete on disk."""
    script = _script(tmp_path, "big.py", BIG_OUTPUT_SCRIPT)
    tool = ShellTool(tmp_path)

    result = asyncio.run(tool.execute({"command": f"{sys.executable} {script}"}))

    assert result.ok, result.error
    assert "truncated" in result.data, "inline output should be capped"

    match = re.search(r"\[spool: (.+?)\]", result.data)
    assert match, "spool path must be included in the result payload"
    spool_path = Path(match.group(1))
    assert spool_path.is_file()
    spool_text = spool_path.read_text(encoding="utf-8", errors="replace")
    assert spool_text.count("A" * 50) == 3000, "spool must hold ALL output lines"
    assert len(spool_text) > 100_000
