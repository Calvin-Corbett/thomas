"""The monolith guard prints the soft-line warning for a commit that touches a file over 700 real code lines.

Proves the dotted modules ``scripts.forge.gates.monolith_guard`` and ``scripts.forge.code_size``. The physical-line cap
still decides the exit code: a warning never fails the guard, and a file the commit does not touch is not listed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "forge" / "gates" / "monolith_guard.py"
BASELINE = {
    "version": 1,
    "scan_roots": ["."],
    "hard_limits": {"py": 1200},
    "waiver_policy": {"unbaselined_soft_limit_lines": 800, "default_owner": "qa", "default_expires_on": "2099-12-31"},
    "allowed_large_files": {},
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "monolith_guard_baseline.json").write_text(json.dumps(BASELINE), encoding="utf-8")
    _git(repo, "init")
    (repo / "big.py").write_text("x = 1\n" * 750, encoding="utf-8")
    (repo / "small.py").write_text("x = 1\n" * 20, encoding="utf-8")
    (repo / "padded.py").write_text('"""Docs."""\n' + "# note\n\n" * 380 + "x = 1\n" * 10, encoding="utf-8")
    _git(repo, "add", "-A")
    return repo


def _run_guard(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), "--repo-root", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_staged_file_over_the_soft_line_is_listed_as_a_warning_and_the_guard_still_passes(tmp_path: Path) -> None:
    done = _run_guard(_repo(tmp_path), "--staged-only")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Monolith guard OK" in done.stdout
    assert "big.py: 750 real code lines (NOT recorded" in done.stdout
    assert "hard cap 800" in done.stdout
    assert "small.py" not in done.stdout.split("Monolith soft line")[1]


def test_a_file_padded_with_comments_and_blank_lines_is_not_listed(tmp_path: Path) -> None:
    done = _run_guard(_repo(tmp_path), "--staged-only")
    assert "padded.py" not in done.stdout


def test_a_commit_that_touches_no_file_over_the_soft_line_prints_no_warning(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "reset", "-q", "big.py")
    done = _run_guard(repo, "--staged-only")
    assert done.returncode == 0
    assert "soft line" not in done.stdout


def test_the_json_report_carries_the_warnings_and_stays_valid_json(tmp_path: Path) -> None:
    done = _run_guard(_repo(tmp_path), "--staged-only", "--json")
    report = json.loads(done.stdout)
    assert report["ok"] is True
    assert any("big.py" in line for line in report["soft_warnings"])
