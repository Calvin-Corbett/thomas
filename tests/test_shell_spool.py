"""CAP-003 L2 core (shell.py-independent): spool complete output + streaming
hang detection with kill-and-retry evidence.

These tests exercise ``thomas.tools.shell_spool.run_spooled_command`` DIRECTLY
(no ShellTool / no protected files), proving the full Level-2 acceptance line
against real child processes:

- a completed run streams and captures stdout/stderr + exit code;
- output larger than any inline cap is preserved COMPLETE in the on-disk spool;
- a process that goes output-idle while still running is detected as hung, its
  process tree is killed promptly (recorded killed pid), and it is retried
  automatically with per-attempt hang evidence;
- a retry that succeeds on the second attempt keeps the first hang on record;
- a missing executable is reported as ``not_found`` rather than raising.

The ShellTool wiring (thomas/tools/shell.py, integrity-protected) is covered
separately in test_shell_spool_hang.py and lands with that file.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from thomas.tools.shell_spool import (
    OUTCOME_COMPLETED,
    OUTCOME_HUNG,
    OUTCOME_NOT_FOUND,
    run_spooled_command,
)

# Prints, then goes output-idle while still running -> should be detected hung.
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

# Emits far more than any inline cap so the spool-completeness check is meaningful.
BIG_OUTPUT_SCRIPT = "for _ in range(3000):\n    print('A' * 50)\n"


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_spool_streams_and_captures_completed_output(tmp_path: Path) -> None:
    script = _script(tmp_path, "ok.py", "print('hello-out')\nimport sys\nsys.stderr.write('warn-err\\n')\n")

    result = run_spooled_command(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        timeout=30.0,
        idle_timeout=5.0,
        spool_dir=tmp_path / "spool",
    )

    assert result.outcome == OUTCOME_COMPLETED
    assert result.exit_code == 0
    assert result.attempts == 1
    assert result.hang_events == []
    assert "hello-out" in result.stdout
    assert "warn-err" in result.stderr
    # The complete output is always on disk too.
    assert Path(result.spool_path).is_file()
    assert "hello-out" in Path(result.spool_path).read_text(encoding="utf-8")


def test_spool_holds_complete_output(tmp_path: Path) -> None:
    script = _script(tmp_path, "big.py", BIG_OUTPUT_SCRIPT)

    result = run_spooled_command(
        [sys.executable, str(script)],
        cwd=str(tmp_path),
        timeout=30.0,
        idle_timeout=5.0,
        spool_dir=tmp_path / "spool",
    )

    assert result.outcome == OUTCOME_COMPLETED
    spool_text = Path(result.spool_path).read_text(encoding="utf-8", errors="replace")
    assert spool_text.count("A" * 50) == 3000, "spool must hold ALL output lines"
    assert len(spool_text) > 100_000


def test_spool_detects_hang_kills_tree_and_records_evidence(tmp_path: Path) -> None:
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
    # Streaming worked: pre-hang output was captured before the kill.
    assert "started" in result.stdout
    # Kill actually happened: without it each attempt would sleep 60s.
    assert elapsed < 20, f"process tree not killed promptly (took {elapsed:.1f}s)"
    # Spool kept everything, including the retry marker between attempts.
    spool_text = Path(result.spool_path).read_text(encoding="utf-8")
    assert spool_text.count("started") == 2
    assert "retry attempt 2 after hang" in spool_text


def test_spool_kill_and_retry_succeeds_on_second_attempt(tmp_path: Path) -> None:
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


def test_spool_missing_executable_is_not_found(tmp_path: Path) -> None:
    result = run_spooled_command(
        ["this-executable-does-not-exist-cap003"],
        cwd=str(tmp_path),
        timeout=5.0,
        idle_timeout=5.0,
        spool_dir=tmp_path / "spool",
    )

    assert result.outcome == OUTCOME_NOT_FOUND
    assert result.exit_code is None
    assert result.stdout == ""
