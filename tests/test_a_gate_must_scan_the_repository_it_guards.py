"""The monolith guard has to look at the repository, not at its own folder.

``monolith_guard.py`` lives at ``scripts/forge/gates/``. Its module-level
constants resolve the repo with ``parents[3]``, like every other gate in that
directory — but the CLI fell back to ``parents[1]``, which is ``scripts/forge``.

So the form pre-commit actually runs, ``--staged-only`` with no ``--repo-root``,
resolved staged paths like ``thomas/server/app.py`` against ``scripts/forge``,
found nothing there, and reported success. Measured before the fix: staging a
1,471-line file that exceeds the hard limit printed "Monolith guard OK. Scanned
0 files under .." and exited 0, while naming "1 changed files" in the same line.

Paired with the shim that swallowed exit codes on Windows, that is how 23
unbaselined violations accumulated while every commit reported clean. Two
defects had to hold at once, and each one alone still printed a success line.

These tests assert the gate looks at the tree it guards and still counts what
it finds — a gate that scans zero files is not passing, it is absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD = REPO_ROOT / "scripts" / "forge" / "gates" / "monolith_guard.py"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), *args],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        cwd=str(cwd or REPO_ROOT),
    )


def test_the_default_repo_root_is_the_repository() -> None:
    """With no --repo-root, the gate must resolve this checkout.

    Uses --staged-only so the assertion costs a root resolution rather than a
    full-tree walk: now that the root is correct, scanning the whole repository
    takes minutes, and a test nobody will wait for is a test that gets skipped.
    """
    result = _run("--staged-only", "--json")
    payload = json.loads(result.stdout)

    assert Path(payload["repo_root"]).resolve() == REPO_ROOT, (
        "the gate resolved its own subdirectory as the repository; every staged path "
        "would fail to exist there and be silently skipped"
    )


def test_it_measures_real_files_under_the_root_it_was_given() -> None:
    """A run that measured nothing must never be reported as a pass.

    Scoped to one real package so this stays seconds rather than minutes while
    still proving the walk reaches actual source files.
    """
    result = _run("--repo-root", str(REPO_ROOT / "thomas" / "cli"), "--json")
    payload = json.loads(result.stdout)

    assert int(payload["measured_count"]) > 10, (
        f"only {payload['measured_count']} files measured under thomas/cli; a gate "
        "scanning near-zero files reports success because it looked at nothing"
    )


def test_an_oversized_staged_file_is_actually_caught(tmp_path: Path) -> None:
    """The end-to-end property: put a violation in front of it, it must object."""
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

    result = _run("--repo-root", str(tmp_path), "--baseline", str(baseline))

    assert result.returncode != 0, "an unbaselined 1300-line file must fail the guard"
    assert "oversized.py" in (result.stdout + result.stderr)
