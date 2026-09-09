"""Deterministic 12+ file coherent-rename tests (CAP-002).

Covers a single symbol used across python source (imports + definitions +
usages), test files, and docs (.md); proves discovery, one coherent
all-or-nothing apply, word-boundary safety, determinism, and full rollback on a
mid-apply failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools.coherent_rename import (
    InvalidIdentifierError,
    apply_rename,
    plan_rename,
)

OLD = "widget_factory"
NEW = "component_builder"

# Files that DO contain a whole-token occurrence of OLD. 13 files spanning
# python source (imports + definition + usages), tests, and docs.
SYMBOL_FILES: dict[str, str] = {
    # --- python source: definition, imports, usages ---
    "src/pkg/__init__.py": 'from .core import widget_factory\n\n__all__ = ["widget_factory"]\n',
    "src/pkg/core.py": (
        'def widget_factory(name):\n    """Build a widget."""\n    return {"name": name, "kind": "widget"}\n'
    ),
    "src/pkg/alpha.py": (
        'from pkg.core import widget_factory\n\ndef make_alpha():\n    return widget_factory("alpha")\n'
    ),
    "src/pkg/beta.py": (
        "from pkg.core import widget_factory\n\n"
        'beta = widget_factory("beta")\n'
        'beta_again = widget_factory("beta2")\n'  # two usages in one file
    ),
    "src/pkg/gamma.py": ('import pkg.core as core\n\ndef make_gamma():\n    return core.widget_factory("gamma")\n'),
    "src/pkg/delta.py": "from pkg.core import widget_factory as wf  # widget_factory alias\n",
    "src/pkg/sub/epsilon.py": ('from pkg.core import widget_factory\n\nresult = widget_factory("epsilon")\n'),
    "src/pkg/zeta.py": "from pkg.core import widget_factory\n\nZETA = widget_factory\n",
    # --- tests ---
    "tests/test_alpha.py": (
        "from pkg.core import widget_factory\n\n"
        "def test_widget_factory():\n"
        '    assert widget_factory("x")["name"] == "x"\n'
    ),
    "tests/test_beta.py": (
        "from pkg.beta import beta\n"
        "from pkg.core import widget_factory\n\n"
        "def test_beta():\n"
        '    assert widget_factory("b")\n'
    ),
    # --- docs ---
    "docs/guide.md": ("# Guide\n\nUse `widget_factory` to build widgets.\n\n    from pkg.core import widget_factory\n"),
    "docs/api.md": "# API\n\n## widget_factory\n\nThe `widget_factory` callable returns a widget.\n",
    "README.md": "# Project\n\nThe main entry point is widget_factory.\n",
}

# Files whose text contains OLD only as a SUBSTRING of a larger identifier, or
# in an ignored file type. None of these must appear in the plan, and none may
# be modified by an apply.
DECOY_FILES: dict[str, str] = {
    # substrings on both sides — word boundaries must protect all of these
    "src/pkg/decoy.py": (
        "widget_factory_extra = 1\nmy_widget_factory = 2\nprefix_widget_factory_suffix = 3\nwidgetfactory = 4\n"
    ),
    "docs/decoy.md": "See widget_factory_helper and the_widget_factory_thing.\n",
    # ignored suffix: .txt is not scanned even though it names the symbol
    "notes.txt": "widget_factory appears here but .txt is not renamed.\n",
}


def _build_repo(root: Path) -> None:
    for rel, content in {**SYMBOL_FILES, **DECOY_FILES}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _build_repo(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Discovery: plan finds all 12+ files, spanning imports/tests/docs
# ---------------------------------------------------------------------------


def test_plan_discovers_all_symbol_files(repo: Path) -> None:
    plan = plan_rename(repo, OLD, NEW)

    planned = {f.rel_path for f in plan.files}
    expected = set(SYMBOL_FILES)
    assert planned == expected
    assert plan.file_count == len(SYMBOL_FILES)
    assert plan.file_count >= 12

    # spans python source, tests, and docs
    assert any(p.endswith(".py") and p.startswith("src/") for p in planned)
    assert any(p.startswith("tests/") for p in planned)
    assert any(p.endswith(".md") for p in planned)


def test_plan_excludes_substring_and_ignored_files(repo: Path) -> None:
    plan = plan_rename(repo, OLD, NEW)
    planned = {f.rel_path for f in plan.files}
    for decoy in DECOY_FILES:
        assert decoy not in planned


def test_plan_counts_multiple_occurrences_per_file(repo: Path) -> None:
    plan = plan_rename(repo, OLD, NEW)
    by_path = {f.rel_path: f.occurrences for f in plan.files}
    # beta.py has import + two usages; __init__.py has import + __all__
    assert by_path["src/pkg/beta.py"] == 3
    assert by_path["src/pkg/__init__.py"] == 2
    assert plan.total_occurrences == sum(by_path.values())


# ---------------------------------------------------------------------------
# Coherent apply: one pass rewrites every occurrence; repo stays consistent
# ---------------------------------------------------------------------------


def test_apply_is_coherent_and_word_boundary_safe(repo: Path) -> None:
    plan = plan_rename(repo, OLD, NEW)
    result = apply_rename(plan)

    assert result.ok
    assert result.rolled_back is False
    assert set(result.applied_files) == set(SYMBOL_FILES)
    assert result.total_occurrences == plan.total_occurrences

    # Every symbol file: old name gone, new name present.
    for rel in SYMBOL_FILES:
        text = (repo / rel).read_text(encoding="utf-8")
        assert "widget_factory" not in _tokens_only(text), rel
        assert NEW in text, rel

    # Decoy substrings are untouched (word boundary respected).
    decoy_py = (repo / "src/pkg/decoy.py").read_text(encoding="utf-8")
    assert decoy_py == DECOY_FILES["src/pkg/decoy.py"]
    assert "widget_factory_extra" in decoy_py
    assert "my_widget_factory" in decoy_py
    assert NEW not in decoy_py

    decoy_md = (repo / "docs/decoy.md").read_text(encoding="utf-8")
    assert decoy_md == DECOY_FILES["docs/decoy.md"]

    # Ignored .txt file untouched.
    assert (repo / "notes.txt").read_text(encoding="utf-8") == DECOY_FILES["notes.txt"]

    # Re-planning for OLD now finds nothing — the rename is complete.
    assert plan_rename(repo, OLD, NEW).is_empty


def _tokens_only(text: str) -> set[str]:
    import re

    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))


# ---------------------------------------------------------------------------
# Determinism: identical inputs -> identical ordered plan
# ---------------------------------------------------------------------------


def test_plan_is_deterministic(repo: Path) -> None:
    plan_a = plan_rename(repo, OLD, NEW)
    plan_b = plan_rename(repo, OLD, NEW)

    assert plan_a == plan_b
    assert [f.rel_path for f in plan_a.files] == [f.rel_path for f in plan_b.files]
    # ordered by POSIX-relative path
    paths = [f.rel_path for f in plan_a.files]
    assert paths == sorted(paths)


# ---------------------------------------------------------------------------
# Rollback: a mid-apply write failure restores ALL files byte-for-byte
# ---------------------------------------------------------------------------


def test_mid_apply_failure_rolls_back_all_files(repo: Path) -> None:
    # Capture original bytes of every file (symbol + decoy) before applying.
    originals = {rel: (repo / rel).read_bytes() for rel in {**SYMBOL_FILES, **DECOY_FILES}}

    plan = plan_rename(repo, OLD, NEW)
    fail_on = 5  # inject the write failure on the 5th planned file
    assert plan.file_count > fail_on

    state = {"calls": 0}

    def flaky_writer(path: Path, content: str) -> None:
        state["calls"] += 1
        if state["calls"] == fail_on:
            raise OSError("simulated disk failure")
        path.write_text(content, encoding="utf-8")  # genuinely mutate earlier files

    result = apply_rename(plan, writer=flaky_writer)

    assert result.ok is False
    assert result.rolled_back is True
    assert "simulated disk failure" in (result.error or "")

    # Every file — including the ones written before the failure — is restored
    # byte-identical to its original.
    for rel, original in originals.items():
        assert (repo / rel).read_bytes() == original, rel


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_invalid_identifier_rejected(repo: Path) -> None:
    with pytest.raises(InvalidIdentifierError):
        plan_rename(repo, "pkg.core.widget_factory", NEW)
    with pytest.raises(InvalidIdentifierError):
        plan_rename(repo, OLD, "not an identifier")


def test_empty_plan_applies_cleanly(repo: Path) -> None:
    plan = plan_rename(repo, "nonexistent_symbol_xyz", NEW)
    assert plan.is_empty
    result = apply_rename(plan)
    assert result.ok
    assert result.applied_files == []
    assert result.rolled_back is False
