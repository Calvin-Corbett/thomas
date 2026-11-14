"""The public file list keeps private files out of a release, and catches an exclusion that would break an import.

Proves scripts.forge.publish.public_tree: ``docs/ops/public_exclude.txt`` names the secret canary files, a tree built
from a fixture repo has none of the listed paths, and a kept file that imports a left-out module is found by ``ast``
whether it uses a plain import, a relative import, an import inside a function or ``import_module`` with a literal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.forge.publish import public_tree as pt

from thomas.core.git_process import run_git

REPO_ROOT = Path(__file__).resolve().parents[1]
CANARIES = ("thomas/security/secret_canaries.py", "tests/test_secret_canaries.py")


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "fixture"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    assert run_git(["init", "-q"], cwd=root).ok
    assert run_git(["add", "-A"], cwd=root).ok
    return root


BASE = {
    "README.md": "hello\n",
    "OWNER_STEPS.md": "steps\n",
    "thomas/__init__.py": "",
    "thomas/security/__init__.py": "",
    "thomas/security/secret_canaries.py": "def plant():\n    return 1\n",
    "tests/test_secret_canaries.py": "def test_x():\n    pass\n",
}


def test_the_list_names_both_canary_files_and_gives_every_rule_a_reason() -> None:
    rules = pt.load_exclude_list(REPO_ROOT)

    assert {r.pattern for r in rules} >= set(CANARIES)
    assert all(r.reason for r in rules)


def test_a_rule_with_no_reason_is_refused() -> None:
    with pytest.raises(ValueError, match="needs a path, a bar and a reason"):
        pt.parse_exclude_list("thomas/x.py\n")
    with pytest.raises(ValueError):
        pt.parse_exclude_list("thomas/x.py |   \n")


def test_a_folder_a_pattern_and_a_path_each_match_what_they_name() -> None:
    rules = pt.parse_exclude_list("plans/ | a\n*.pem | b\nOWNER_STEPS.md | c\n# note\n\n")

    kept, removed = pt.split_paths(
        ["plans/a/b.md", "x/y.pem", "OWNER_STEPS.md", "docs/OWNER_STEPS.md", "README.md"], rules
    )

    assert kept == ["README.md", "docs/OWNER_STEPS.md"]
    assert removed == {"OWNER_STEPS.md": "c", "plans/a/b.md": "a", "x/y.pem": "b"}


def test_a_tree_built_from_a_fixture_repo_holds_no_listed_path(tmp_path: Path) -> None:
    root = _repo(tmp_path, BASE)

    report = pt.prune_tree(root, pt.public_rules(REPO_ROOT))

    for rel in (*CANARIES, "OWNER_STEPS.md"):
        assert not (root / rel).exists(), f"{rel} reached the public tree"
        assert rel not in report.kept
        assert rel in report.removed
    assert (root / "thomas/security/__init__.py").is_file()
    assert report.importers == {}
    assert report.problems == []


def test_a_kept_file_that_imports_a_left_out_module_is_named(tmp_path: Path) -> None:
    files = {
        **BASE,
        "thomas/app.py": "from thomas.security import secret_canaries\n",
        "thomas/security/helper.py": "from .secret_canaries import plant\n",
        "thomas/lazy.py": "def go():\n    import thomas.security.secret_canaries as c\n    return c\n",
        "thomas/dynamic.py": "import importlib\nm = importlib.import_module('thomas.security.secret_canaries')\n",
        "thomas/fine.py": "from thomas.security import something_else\n",
    }
    root = _repo(tmp_path, files)

    report = pt.prune_tree(root, pt.public_rules(REPO_ROOT))

    assert sorted(report.importers) == [
        "thomas/app.py",
        "thomas/dynamic.py",
        "thomas/lazy.py",
        "thomas/security/helper.py",
    ]
    assert len(report.problems) == 4
    assert "thomas.security.secret_canaries" in report.problems[0]


def test_pruning_a_folder_that_is_not_a_checkout_removes_nothing(tmp_path: Path) -> None:
    (tmp_path / "OWNER_STEPS.md").write_text("steps\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not a git checkout"):
        pt.prune_tree(tmp_path, pt.public_rules(REPO_ROOT))

    assert (tmp_path / "OWNER_STEPS.md").is_file()


def test_nothing_the_real_tree_keeps_imports_a_file_the_release_leaves_out() -> None:
    tracked = pt.tracked_files(REPO_ROOT)
    kept, removed = pt.split_paths(tracked, pt.public_rules(REPO_ROOT, tracked))

    report = pt.check_tree(REPO_ROOT, removed, kept)

    assert report.problems == []
    assert set(CANARIES) <= set(removed)


def test_the_public_root_holds_only_files_the_hygiene_baseline_allows() -> None:
    tracked = pt.tracked_files(REPO_ROOT)
    baseline = json.loads((REPO_ROOT / pt.HYGIENE_BASELINE).read_text(encoding="utf-8"))
    kept, removed = pt.split_paths(tracked, pt.public_rules(REPO_ROOT, tracked))

    at_root = [p for p in kept if "/" not in p]

    assert set(at_root) <= set(baseline["allowed_tracked_root_files"])
    assert len(at_root) <= baseline["max_tracked_root_files"]
    assert "not on the hygiene baseline" in removed.get("thomas.cmd", "")
