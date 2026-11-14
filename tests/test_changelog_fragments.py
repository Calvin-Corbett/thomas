"""Each agent writes its own changelog fragment; the release folds them in.

Two agents writing one CHANGELOG.md took turns parking each other's words and
once swept the other's entries into a commit by accident. A fragment under
``changelog.d/<agent>-<slug>.md`` belongs to one agent; nobody edits anybody
else's, and the release step compiles them into the version section.
"""

from __future__ import annotations

from pathlib import Path

from scripts.forge.changelog_fragments import check_fragment, compile_fragments

GOOD = """### Changed

- **The evolve module is split along its seam.** One clean cut, every name re-imported.
"""


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [0.19.38] - 2026-09-07\n\n### Changed\n\n- **Older entry.** Stays.\n",
        encoding="utf-8",
    )
    frag_dir = tmp_path / "changelog.d"
    frag_dir.mkdir()
    return changelog, frag_dir


def test_a_fragment_needs_a_known_section_and_one_bullet(tmp_path: Path) -> None:
    good = tmp_path / "claude-evolve-split.md"
    good.write_text(GOOD, encoding="utf-8")
    assert check_fragment(good) == []

    no_section = tmp_path / "claude-no-section.md"
    no_section.write_text("- **A bullet with no section.**\n", encoding="utf-8")
    assert any("section" in problem for problem in check_fragment(no_section))

    no_bullet = tmp_path / "claude-no-bullet.md"
    no_bullet.write_text("### Fixed\n\nprose without a bullet\n", encoding="utf-8")
    assert any("bullet" in problem for problem in check_fragment(no_bullet))

    bad_name = tmp_path / "notes.md"
    bad_name.write_text(GOOD, encoding="utf-8")
    assert any("name" in problem for problem in check_fragment(bad_name))


def test_two_agents_fragments_fold_into_one_version_section(tmp_path: Path) -> None:
    changelog, frag_dir = _repo(tmp_path)
    (frag_dir / "claude-evolve-split.md").write_text(GOOD, encoding="utf-8")
    (frag_dir / "codex-redesign-undo.md").write_text(
        "### Fixed\n\n- **Redesign undo restores exact pre-images.**\n\n### Changed\n\n- **Refresh reloads only the selected tab.**\n",
        encoding="utf-8",
    )

    result = compile_fragments(changelog, frag_dir, version="0.19.39", date="2026-09-07")

    text = changelog.read_text(encoding="utf-8")
    assert result.folded == 2
    assert "## [Unreleased]\n\n## [0.19.39] - 2026-09-07\n" in text
    section = text.split("## [0.19.39] - 2026-09-07\n", 1)[1].split("## [0.19.38]", 1)[0]
    assert section.index("### Changed") < section.index("### Fixed")
    assert section.index("evolve module is split") < section.index("Refresh reloads")
    assert "Redesign undo restores" in section
    assert "- **Older entry.** Stays." in text
    assert list(frag_dir.iterdir()) == []


def test_fragments_join_an_existing_version_section(tmp_path: Path) -> None:
    changelog, frag_dir = _repo(tmp_path)
    (frag_dir / "claude-late.md").write_text("### Changed\n\n- **A late entry for the same version.**\n", encoding="utf-8")

    compile_fragments(changelog, frag_dir, version="0.19.38", date="2026-09-07")

    text = changelog.read_text(encoding="utf-8")
    assert text.count("## [0.19.38]") == 1
    section = text.split("## [0.19.38] - 2026-09-07\n", 1)[1]
    assert section.count("### Changed") == 1
    assert "- **Older entry.** Stays." in section and "A late entry" in section


def test_no_fragments_is_a_no_op_that_says_so(tmp_path: Path) -> None:
    changelog, frag_dir = _repo(tmp_path)
    # The directory explains itself; a README is not a fragment.
    (frag_dir / "README.md").write_text("# how fragments work", encoding="utf-8")
    before = changelog.read_text(encoding="utf-8")

    result = compile_fragments(changelog, frag_dir, version="0.19.39", date="2026-09-07")

    assert result.folded == 0
    assert changelog.read_text(encoding="utf-8") == before
    assert (frag_dir / "README.md").exists()


def test_a_bad_fragment_stops_the_compile_before_it_touches_the_changelog(tmp_path: Path) -> None:
    changelog, frag_dir = _repo(tmp_path)
    (frag_dir / "claude-good.md").write_text(GOOD, encoding="utf-8")
    (frag_dir / "codex-bad.md").write_text("no section, no bullet\n", encoding="utf-8")
    before = changelog.read_text(encoding="utf-8")

    result = compile_fragments(changelog, frag_dir, version="0.19.39", date="2026-09-07")

    assert result.folded == 0
    assert result.problems and "codex-bad.md" in result.problems[0]
    assert changelog.read_text(encoding="utf-8") == before
    assert (frag_dir / "claude-good.md").exists()
