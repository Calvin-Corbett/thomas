"""CAP-020 / CAP-021: scoped hierarchical instruction resolution.

Proves the acceptance lines:
- CAP-020: resolve and merge nearest-directory instruction files with
  deterministic precedence.
- CAP-021: live-read competing instruction formats (CLAUDE.md, AGENTS.md,
  .cursorrules) with lossless precedence.
"""

from pathlib import Path

from thomas.agent.instruction_resolution import (
    INSTRUCTION_FILENAMES,
    OVERRIDE_MARKER,
    find_project_root,
    merge_instruction_sources,
    resolve_instruction_sources,
    resolve_merged_instructions,
)
from thomas.agent.project_instructions import (
    discover_project_instructions,
    instruction_file_path,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# CAP-020: nearest-directory wins, deterministic precedence
# ---------------------------------------------------------------------------


def test_nearest_directory_wins_over_parent(tmp_path: Path) -> None:
    _write(tmp_path / "THOMAS.md", "ROOT-RULE: use tabs")
    nested = tmp_path / "pkg" / "sub"
    _write(nested / "THOMAS.md", "NEAR-RULE: use spaces")

    sources = resolve_instruction_sources(nested, root=tmp_path)

    assert [s.path for s in sources] == [nested / "THOMAS.md", tmp_path / "THOMAS.md"]
    assert sources[0].depth == 0  # nearest directory is highest precedence

    merged = resolve_merged_instructions(nested, root=tmp_path)
    assert merged is not None
    # Highest precedence (nearest) is emitted LAST in the merged block.
    assert merged.index("ROOT-RULE: use tabs") < merged.index("NEAR-RULE: use spaces")


def test_within_directory_format_precedence_is_fixed(tmp_path: Path) -> None:
    _write(tmp_path / "THOMAS.md", "thomas-native")
    _write(tmp_path / ".thomas.md", "thomas-dot")
    _write(tmp_path / "CLAUDE.md", "claude-content")
    _write(tmp_path / "AGENTS.md", "agents-content")
    _write(tmp_path / ".cursorrules", "cursor-content")

    sources = resolve_instruction_sources(tmp_path, root=tmp_path)

    # Exact documented order: THOMAS.md > .thomas.md > CLAUDE.md > AGENTS.md > .cursorrules
    assert [s.path.name for s in sources] == [
        "THOMAS.md",
        ".thomas.md",
        "CLAUDE.md",
        "AGENTS.md",
        ".cursorrules",
    ]
    assert [s.fmt for s in sources] == ["thomas", "thomas", "claude", "agents", "cursor"]
    # Merged output reverses that: lowest precedence first, Thomas-native last.
    merged = merge_instruction_sources(sources)
    positions = [
        merged.index(c) for c in ("cursor-content", "agents-content", "claude-content", "thomas-dot", "thomas-native")
    ]
    assert positions == sorted(positions)


def test_resolution_is_deterministic(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    _write(tmp_path / "CLAUDE.md", "root claude")
    _write(nested / ".cursorrules", "nested cursor")
    _write(nested / "AGENTS.md", "nested agents")

    first = resolve_merged_instructions(nested, root=tmp_path)
    second = resolve_merged_instructions(nested, root=tmp_path)

    assert first == second
    assert first is not None


def test_root_boundary_stops_collection(tmp_path: Path) -> None:
    _write(tmp_path / "THOMAS.md", "OUTSIDE-ROOT")
    project = tmp_path / "project"
    nested = project / "src"
    _write(project / "THOMAS.md", "PROJECT-RULE")
    _write(nested / "THOMAS.md", "SRC-RULE")

    merged = resolve_merged_instructions(nested, root=project)

    assert merged is not None
    assert "OUTSIDE-ROOT" not in merged
    assert "PROJECT-RULE" in merged
    assert "SRC-RULE" in merged


def test_start_as_file_uses_parent_directory(tmp_path: Path) -> None:
    _write(tmp_path / "THOMAS.md", "DIR-RULE")
    work_file = tmp_path / "module.py"
    _write(work_file, "print('hi')")

    merged = resolve_merged_instructions(work_file, root=tmp_path)

    assert merged is not None and "DIR-RULE" in merged


def test_find_project_root_stops_at_git_dir(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    nested = project / "deep" / "er"
    nested.mkdir(parents=True)

    assert find_project_root(nested) == project


# ---------------------------------------------------------------------------
# CAP-021: cross-tool formats, live-read, lossless precedence
# ---------------------------------------------------------------------------


def test_merge_is_lossless_across_formats_and_levels(tmp_path: Path) -> None:
    nested = tmp_path / "app"
    _write(tmp_path / "CLAUDE.md", "SENTINEL-ROOT-CLAUDE")
    _write(tmp_path / ".cursorrules", "SENTINEL-ROOT-CURSOR")
    _write(tmp_path / "AGENTS.md", "SENTINEL-ROOT-AGENTS")
    _write(nested / "THOMAS.md", "SENTINEL-NEAR-THOMAS")
    _write(nested / "CLAUDE.md", "SENTINEL-NEAR-CLAUDE")

    merged = resolve_merged_instructions(nested, root=tmp_path)

    assert merged is not None
    for sentinel in (
        "SENTINEL-ROOT-CLAUDE",
        "SENTINEL-ROOT-CURSOR",
        "SENTINEL-ROOT-AGENTS",
        "SENTINEL-NEAR-THOMAS",
        "SENTINEL-NEAR-CLAUDE",
    ):
        assert sentinel in merged, f"lossless merge missing {sentinel}"
    # Every block is labelled with its origin path and format id.
    assert "app/THOMAS.md (thomas)" in merged
    assert "CLAUDE.md (claude)" in merged
    assert ".cursorrules (cursor)" in merged
    assert "AGENTS.md (agents)" in merged


def test_cross_format_content_is_live_read(tmp_path: Path) -> None:
    rules = tmp_path / ".cursorrules"
    _write(rules, "VERSION-ONE")
    first = resolve_merged_instructions(tmp_path, root=tmp_path)
    _write(rules, "VERSION-TWO")
    second = resolve_merged_instructions(tmp_path, root=tmp_path)

    assert first is not None and "VERSION-ONE" in first
    assert second is not None and "VERSION-TWO" in second
    assert "VERSION-ONE" not in second


def test_explicit_override_suppresses_ancestors(tmp_path: Path) -> None:
    nested = tmp_path / "svc"
    _write(tmp_path / "CLAUDE.md", "ANCESTOR-CONTENT")
    _write(tmp_path / ".cursorrules", "ANCESTOR-CURSOR")
    _write(nested / "CLAUDE.md", f"{OVERRIDE_MARKER}\nNEAR-ONLY-CONTENT")

    merged = resolve_merged_instructions(nested, root=tmp_path)

    assert merged is not None
    assert "NEAR-ONLY-CONTENT" in merged
    assert "ANCESTOR-CONTENT" not in merged
    assert "ANCESTOR-CURSOR" not in merged
    assert OVERRIDE_MARKER not in merged  # marker line is stripped


def test_explicit_override_suppresses_lower_formats_in_same_directory(tmp_path: Path) -> None:
    _write(tmp_path / "THOMAS.md", f"{OVERRIDE_MARKER}\nNATIVE-WINS")
    _write(tmp_path / "CLAUDE.md", "CLAUDE-LOSES")
    _write(tmp_path / ".cursorrules", "CURSOR-LOSES")

    merged = resolve_merged_instructions(tmp_path, root=tmp_path)

    assert merged is not None
    assert "NATIVE-WINS" in merged
    assert "CLAUDE-LOSES" not in merged
    assert "CURSOR-LOSES" not in merged


def test_higher_precedence_override_beats_lower_override(tmp_path: Path) -> None:
    nested = tmp_path / "x"
    _write(tmp_path / "THOMAS.md", f"{OVERRIDE_MARKER}\nROOT-OVERRIDE")
    _write(nested / "CLAUDE.md", f"{OVERRIDE_MARKER}\nNEAR-OVERRIDE")

    sources = resolve_instruction_sources(nested, root=tmp_path)

    assert [s.content for s in sources] == ["NEAR-OVERRIDE"]


def test_merge_truncation_drops_lowest_precedence_first(tmp_path: Path) -> None:
    nested = tmp_path / "n"
    _write(tmp_path / "CLAUDE.md", "FAR-" + ("f" * 400))
    _write(nested / "THOMAS.md", "NEAR-" + ("n" * 100))

    merged = resolve_merged_instructions(nested, root=tmp_path, max_chars=300)

    assert merged is not None
    assert "NEAR-" in merged  # highest precedence survives
    assert "FAR-" not in merged
    assert "[instructions truncated: 1 lowest-precedence file(s) omitted for length]" in merged


def test_single_oversized_block_is_tail_truncated_with_note(tmp_path: Path) -> None:
    _write(tmp_path / "THOMAS.md", "KEEP-HEAD " + ("x" * 2_000))

    merged = resolve_merged_instructions(tmp_path, root=tmp_path, max_chars=500)

    assert merged is not None
    assert "KEEP-HEAD" in merged  # head of highest-precedence content survives
    assert len(merged) <= 500
    assert "[instructions truncated: content cut to fit prompt budget]" in merged


def test_discover_project_instructions_respects_max_chars(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    _write(tmp_path / "CLAUDE.md", "BUDGET-TEST " + ("y" * 3_000))

    text = discover_project_instructions(tmp_path, max_chars=400)

    assert text is not None
    assert len(text) <= 400
    assert "BUDGET-TEST" in text


# ---------------------------------------------------------------------------
# Backward compatibility of the public project_instructions API
# ---------------------------------------------------------------------------


def test_discover_project_instructions_native_only(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    _write(tmp_path / "THOMAS.md", "NATIVE-INSTRUCTIONS")

    text = discover_project_instructions(tmp_path)

    assert text is not None and "NATIVE-INSTRUCTIONS" in text


def test_discover_project_instructions_returns_none_when_empty(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    assert discover_project_instructions(tmp_path) is None


def test_instruction_file_path_finds_competing_formats(tmp_path: Path) -> None:
    _write(tmp_path / "CLAUDE.md", "claude only")

    found = instruction_file_path(tmp_path)

    assert found == tmp_path / "CLAUDE.md"


def test_instruction_file_path_prefers_native_format(tmp_path: Path) -> None:
    _write(tmp_path / "CLAUDE.md", "claude")
    _write(tmp_path / "THOMAS.md", "native")

    found = instruction_file_path(tmp_path)

    assert found == tmp_path / "THOMAS.md"


def test_supported_filenames_contract() -> None:
    names = [name for name, _fmt in INSTRUCTION_FILENAMES]
    assert names == ["THOMAS.md", ".thomas.md", "CLAUDE.md", "AGENTS.md", ".cursorrules"]
