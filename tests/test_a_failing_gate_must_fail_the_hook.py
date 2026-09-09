"""Every gate runs through scripts/_gate_python.py — its verdict must survive.

28 pre-commit entries invoke gates as ``python scripts/_gate_python.py <gate.py>``.
The shim re-execs into the repo ``.venv`` interpreter so gates cannot pick up a
stray ``python`` from PATH. It did that with ``os.execv``.

Windows has no exec. ``os.execv`` there is emulated: the CRT spawns a *new*
process and terminates the current one straight away, so the caller — pre-commit —
collects the shim's own exit status (0) rather than the gate's, and the gate's
stdout goes to a process nobody is reading. Both halves of the verdict are lost.

Measured on this machine before the fix: ``monolith_guard.py`` run directly
exited 1 and printed 23 violations; the identical child through the shim exited
0 and printed nothing. Every gate routed through the shim was advisory without
anyone deciding it should be.

These tests assert the property that matters — a failing gate fails the hook,
and a gate's output reaches whoever ran it — rather than which system call is
used to get there.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIM = REPO_ROOT / "scripts" / "_gate_python.py"


def _run_through_shim(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SHIM), str(target), *args],
        capture_output=True,
        text=True,
        timeout=420,
        check=False,
    )


@pytest.mark.parametrize("exit_code", [1, 2, 7])
def test_a_gates_nonzero_exit_reaches_the_caller(exit_code: int, tmp_path: Path) -> None:
    gate = tmp_path / "failing_gate.py"
    gate.write_text(f"import sys\nsys.exit({exit_code})\n", encoding="utf-8")

    result = _run_through_shim(gate)

    assert result.returncode == exit_code, (
        f"the shim reported {result.returncode} for a gate that exited {exit_code}; "
        "pre-commit would treat this failing gate as a pass"
    )


def test_a_passing_gate_still_reports_success(tmp_path: Path) -> None:
    gate = tmp_path / "passing_gate.py"
    gate.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")

    assert _run_through_shim(gate).returncode == 0


def test_the_shim_waits_for_a_slow_gate_instead_of_returning_early(tmp_path: Path) -> None:
    """The observed symptom: a verdict arriving after the hook already passed."""
    gate = tmp_path / "slow_gate.py"
    gate.write_text("import sys, time\ntime.sleep(2)\nsys.exit(7)\n", encoding="utf-8")

    result = _run_through_shim(gate)

    assert result.returncode == 7


def test_a_gates_report_is_not_swallowed(tmp_path: Path) -> None:
    """A gate that cannot say why it failed is nearly as bad as one that cannot fail."""
    gate = tmp_path / "reporting_gate.py"
    gate.write_text(
        "import sys\nprint('VIOLATION: 23 files exceed the hard limit')\nprint('to stderr', file=sys.stderr)\nsys.exit(1)\n",
        encoding="utf-8",
    )

    result = _run_through_shim(gate)

    assert result.returncode == 1
    assert "VIOLATION: 23 files exceed the hard limit" in result.stdout
    assert "to stderr" in result.stderr


def test_arguments_still_reach_the_gate(tmp_path: Path) -> None:
    gate = tmp_path / "arg_gate.py"
    gate.write_text(
        "import sys\nsys.exit(0 if sys.argv[1:] == ['--staged-only', '--json'] else 3)\n",
        encoding="utf-8",
    )

    assert _run_through_shim(gate, "--staged-only", "--json").returncode == 0


def test_a_real_repo_gate_still_fails_through_the_shim(tmp_path: Path) -> None:
    """End-to-end against the real gate whose silence exposed this.

    Pointed at a throwaway tree with one oversized file rather than the whole
    repo: scanning the real checkout twice took over pytest's 300s ceiling and
    the test timed out, and it made the result depend on how much debt the repo
    happens to carry today. A gate that cannot finish is its own kind of silence.
    """
    guard = REPO_ROOT / "scripts" / "forge" / "gates" / "monolith_guard.py"
    if not guard.exists():  # pragma: no cover - guard ships with the repo
        pytest.skip("monolith_guard.py not present")

    (tmp_path / "oversized.py").write_text("x = 1\n" * 1300, encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["."],
                "hard_limits": {"py": 1200},
                "waiver_policy": {"require_metadata": True, "unbaselined_soft_limit_lines": 800},
                "allowed_large_files": {},
            }
        ),
        encoding="utf-8",
    )
    args = ("--repo-root", str(tmp_path), "--baseline", str(baseline))

    direct = subprocess.run(
        [sys.executable, str(guard), *args], capture_output=True, text=True, timeout=120, check=False
    )
    wrapped = _run_through_shim(guard, *args)

    assert direct.returncode != 0, "the fixture must actually violate the limit for this to prove anything"
    assert wrapped.returncode == direct.returncode, (
        f"the shim must report exactly what the gate reported; gate={direct.returncode} shim={wrapped.returncode}"
    )
    assert "oversized.py" in (wrapped.stdout + wrapped.stderr), "the gate's report must survive the shim"
