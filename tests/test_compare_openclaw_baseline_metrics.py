from __future__ import annotations

from pathlib import Path

import scripts.compare_openclaw_baseline as compare


def test_metric_row_higher_is_better_marks_expected_winner() -> None:
    row = compare._metric_row(
        metric="x",
        thomas=12,
        openclaw=9,
        preference="higher_is_better",
        rationale="demo",
    )
    assert row["winner"] == "thomas"
    assert row["delta_thomas_minus_openclaw"] == 3


def test_metric_row_lower_is_better_marks_expected_winner() -> None:
    row = compare._metric_row(
        metric="x",
        thomas=8,
        openclaw=10,
        preference="lower_is_better",
        rationale="demo",
    )
    assert row["winner"] == "thomas"
    assert row["delta_thomas_minus_openclaw"] == -2


def test_is_test_file_detects_common_test_naming_patterns(tmp_path: Path) -> None:
    assert compare._is_test_file(tmp_path / "tests" / "test_alpha.py") is True
    assert compare._is_test_file(tmp_path / "src" / "alpha.spec.ts") is True
    assert compare._is_test_file(tmp_path / "src" / "alpha.test.ts") is True
    assert compare._is_test_file(tmp_path / "src" / "alpha.py") is False


def test_count_mobile_surface_dirs_counts_root_and_apps(tmp_path: Path) -> None:
    (tmp_path / "android").mkdir(parents=True, exist_ok=True)
    (tmp_path / "apps" / "ios").mkdir(parents=True, exist_ok=True)
    (tmp_path / "apps" / "macos").mkdir(parents=True, exist_ok=True)
    assert compare._count_mobile_surface_dirs(tmp_path) == 3
