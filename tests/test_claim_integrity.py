from __future__ import annotations

from pathlib import Path

import scripts.forge.gates.claim_integrity as mod


def test_extract_path_refs_dedupes_and_filters() -> None:
    text = """
## [0.1.0] - 2026-03-05
- Added `thomas/core/foo.py`
- Reused `thomas/core/foo.py`
- Mentioned `not/a/repo/path.txt`
"""
    assert mod._extract_path_refs(text) == ["thomas/core/foo.py"]


def test_evaluate_claim_paths_flags_untracked_and_placeholder(tmp_path: Path) -> None:
    tracked_file = tmp_path / "thomas" / "core" / "tracked.py"
    tracked_file.parent.mkdir(parents=True, exist_ok=True)
    tracked_file.write_text("# Source placeholder for tracked.py\n", encoding="utf-8")

    untracked_file = tmp_path / "thomas" / "core" / "untracked.py"
    untracked_file.write_text("x = 1\n", encoding="utf-8")

    issues = mod._evaluate_claim_paths(
        refs=["thomas/core/tracked.py", "thomas/core/untracked.py", "thomas/core/missing.py"],
        repo_root=tmp_path,
        tracked={"thomas/core/tracked.py"},
    )

    assert {"path": "thomas/core/tracked.py", "issue": "placeholder_backed"} in issues
    assert {"path": "thomas/core/untracked.py", "issue": "untracked"} in issues
    assert {"path": "thomas/core/missing.py", "issue": "missing"} in issues


def test_latest_changelog_section_returns_first_release_block(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "## [0.2.0] - 2026-03-05\n- Added `thomas/core/a.py`\n\n## [0.1.0] - 2026-03-04\n- Added `thomas/core/b.py`\n",
        encoding="utf-8",
    )

    section = mod._latest_changelog_section(changelog)

    assert "`thomas/core/a.py`" in section
    assert "`thomas/core/b.py`" not in section
