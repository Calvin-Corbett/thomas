"""No file crosses the soft code line unrecorded, and the record only goes down.

Proves the dotted modules ``scripts.forge.code_size`` and ``scripts.forge.gates.monolith_guard`` (the physical-line cap
this line sits under). The physical-line cap is unchanged. This is the softer line beside it: a ``.py`` file with more
than ``SOFT_REAL_CODE_LINES`` real code lines (no blank lines, comment-only lines, docstrings or multi-line data
tables; the rule is in ``scripts/forge/code_size.py``) that is not already over the physical cap.

``docs/monolith_soft_recorded.txt`` lists those files, one ``path real_lines`` per line, copied from the shape of
``tests/shell_routes_recorded.txt``. A file that crosses the line without being in it fails here and is split by
responsibility. A file in it that grew fails, and one that shrank or fell under the line fails until its line is
lowered, so the list can only go down. ``git ls-files "*.py" | python -m scripts.forge.code_size --lower`` does the
lowering and refuses to add or raise anything.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.forge import code_size as cs

ROOT = Path(__file__).resolve().parents[1]
SKIPPED = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "build",
    "dist",
    "generated",
    "runtime",
    "output",
    "pack",
    "patches",
    "tasks",
}


def _tracked_python() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.split("\0") if p and not SKIPPED.intersection(Path(p).parts)]


def test_the_record_is_exact_so_nothing_crosses_unrecorded_and_nothing_stays_that_shrank() -> None:
    measured = cs.measure(ROOT, _tracked_python())
    problems = cs.judge(measured, cs.read_record(ROOT / cs.RECORD_NAME), cs.hard_cap(ROOT))
    assert problems == [], "\n".join(problems)


def test_the_physical_cap_is_read_from_the_guards_baseline_and_sits_above_the_soft_line() -> None:
    assert cs.hard_cap(ROOT) > cs.SOFT_REAL_CODE_LINES


def test_a_new_file_over_the_soft_line_fails_the_same_check_the_repository_runs(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "monolith_guard_baseline.json").write_text(
        '{"waiver_policy": {"unbaselined_soft_limit_lines": 800}}', encoding="utf-8"
    )
    (tmp_path / "big.py").write_text("x = 1\n" * 750, encoding="utf-8")
    measured = cs.measure(tmp_path, ["big.py"])
    assert measured == {"big.py": 750}
    assert cs.judge(measured, {}, cs.hard_cap(tmp_path)) != []
    assert cs.judge(measured, {"big.py": 750}, cs.hard_cap(tmp_path)) == []
