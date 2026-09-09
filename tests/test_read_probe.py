"""CAP-001 L2: repo-wide read & navigation with a bounded read rationale.

Proves the exact acceptance line -- "Add a runtime probe with an unhinted
symbol three directories deep and require a bounded read rationale":

- A symbol defined three directories deep (``a/b/c/target.py``) is located with
  NO location hint supplied to the probe.
- The result carries a read rationale that is present, bounded (at most
  ``budget.max_files`` entries and at most ``budget.max_bytes`` bytes), and every
  entry has a non-empty one-line reason.
- A symbol that does not exist yields empty locations but a rationale recording
  what was searched (still bounded).
- ``budget_used`` never exceeds the budget on either dimension.
- The probe is deterministic across repeated runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools.read_navigation import (
    BudgetUsage,
    ReadBudget,
    ReadProbeResult,
    RepoReadProbe,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """A hermetic repo with the target defined exactly three directories deep."""
    root = tmp_path / "repo"
    # Noise at shallower depths, none of which define the target.
    _write(root / "top.py", "X = 1\n\n\ndef helper():\n    return X\n")
    _write(root / "pkg" / "mod.py", "class Other:\n    pass\n")
    _write(root / "a" / "shim.py", "VALUE = 42\n")
    _write(root / "a" / "b" / "adapter.py", "def unrelated():\n    return None\n")
    # The target: three directories deep -> a/b/c/target.py.
    _write(
        root / "a" / "b" / "c" / "target.py",
        "import os\n\n\ndef find_me(needle):\n    return os.path.exists(needle)\n",
    )
    # A __pycache__ dir that must be ignored (would otherwise burn budget).
    _write(root / "a" / "b" / "c" / "__pycache__" / "target.cpython.py", "def find_me():\n    pass\n")
    return root


def test_unhinted_symbol_three_dirs_deep_is_located(fixture_repo: Path) -> None:
    probe = RepoReadProbe()
    budget = ReadBudget(max_files=50, max_bytes=100_000)

    # No hint of any kind -- just the bare symbol name.
    result = probe.probe(fixture_repo, "find_me", budget)

    assert isinstance(result, ReadProbeResult)
    assert [loc.path for loc in result.locations] == ["a/b/c/target.py"]
    loc = result.locations[0]
    assert loc.line == 4
    assert loc.kind == "function"
    # The definition lives three directories deep under the root.
    assert Path(loc.path).parts[:3] == ("a", "b", "c")
    # The ignored __pycache__ copy was never counted as a location.
    assert all("__pycache__" not in loc.path for loc in result.locations)


def test_read_rationale_present_bounded_and_reasoned(fixture_repo: Path) -> None:
    probe = RepoReadProbe()
    budget = ReadBudget(max_files=3, max_bytes=100_000)

    result = probe.probe(fixture_repo, "find_me", budget)

    # Rationale is present and each entry carries a one-line reason.
    assert result.rationale, "rationale must be present"
    for entry in result.rationale:
        assert entry.reason.strip(), "every read must have a reason"
        assert "\n" not in entry.reason, "reason must be a single line"
        assert entry.path

    # Bounded: at most max_files entries, and total bytes within max_bytes.
    assert len(result.rationale) <= budget.max_files
    assert sum(e.bytes_read for e in result.rationale) <= budget.max_bytes


def test_missing_symbol_returns_empty_locations_with_bounded_rationale(fixture_repo: Path) -> None:
    probe = RepoReadProbe()
    budget = ReadBudget(max_files=50, max_bytes=100_000)

    result = probe.probe(fixture_repo, "does_not_exist_anywhere", budget)

    assert result.locations == []
    # Still accountable: we recorded which files were searched.
    assert result.rationale, "a miss must still record what was searched"
    assert all("no definition here" in e.reason for e in result.rationale)
    assert len(result.rationale) <= budget.max_files


def test_probe_never_exceeds_budget(fixture_repo: Path) -> None:
    probe = RepoReadProbe()
    # Deliberately tiny budget: fewer files than the repo contains, small bytes.
    budget = ReadBudget(max_files=2, max_bytes=40)

    result = probe.probe(fixture_repo, "find_me", budget)

    used: BudgetUsage = result.budget_used
    assert used.files_read <= budget.max_files
    assert used.bytes_read <= budget.max_bytes
    assert used.fits_within(budget)
    assert result.within_budget is True
    # The rationale never enumerates more reads than the budget allows.
    assert len(result.rationale) <= budget.max_files
    # A tiny budget cannot cover the whole repo -> the walk reports it capped.
    assert result.exhausted_budget is True


def test_byte_budget_causes_partial_read_without_overrun(fixture_repo: Path) -> None:
    probe = RepoReadProbe()
    # Enough files, but a byte cap smaller than the combined file sizes.
    budget = ReadBudget(max_files=50, max_bytes=30)

    result = probe.probe(fixture_repo, "find_me", budget)

    assert result.budget_used.bytes_read <= 30
    # At least one read was truncated to respect the byte budget.
    assert any(e.truncated for e in result.rationale)
    assert all("partial read (byte budget)" in e.reason for e in result.rationale if e.truncated)


def test_determinism(fixture_repo: Path) -> None:
    probe = RepoReadProbe()
    budget = ReadBudget(max_files=50, max_bytes=100_000)

    first = probe.probe(fixture_repo, "find_me", budget)
    second = probe.probe(fixture_repo, "find_me", budget)

    assert [(loc.path, loc.line, loc.kind) for loc in first.locations] == [
        (loc.path, loc.line, loc.kind) for loc in second.locations
    ]
    assert [(e.path, e.bytes_read, e.reason) for e in first.rationale] == [
        (e.path, e.bytes_read, e.reason) for e in second.rationale
    ]
    assert first.budget_used == second.budget_used


def test_locates_class_and_assignment_kinds(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _write(root / "x" / "y" / "z" / "defs.py", "class Widget:\n    pass\n")
    _write(root / "cfg.py", "Widget = None\n")
    probe = RepoReadProbe()
    result = probe.probe(root, "Widget", ReadBudget(max_files=10, max_bytes=100_000))

    kinds = {(loc.path, loc.kind) for loc in result.locations}
    assert ("x/y/z/defs.py", "class") in kinds
    assert ("cfg.py", "assignment") in kinds
