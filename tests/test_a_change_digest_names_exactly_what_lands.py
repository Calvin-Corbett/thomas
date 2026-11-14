"""A change digest names exactly what a change lands: a second look's verdict counts only for the digest it read
(spec section 8.2, condition 3; 2026-10-14 review, WS-R1).

Its own git repo in tmp.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks
from scripts.cage import window_evidence as we

from tests.green_support import git, make_blue


def _commit(repo: Path, files: dict[str, str], message: str = "c") -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def _patch(repo: Path, a: str, b: str) -> bytes:
    return subprocess.run(["git", "diff", "--binary", "--full-index", a, b], cwd=repo, capture_output=True).stdout


def _digest_on(repo: Path, parent: str, patch: bytes) -> str:
    tree = checks.derive_tree(repo, parent, patch)
    return we.change_digest(repo, parent, tree, checks.tree_changes(repo, parent, tree))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = make_blue(tmp_path)
    _commit(repo, {"thomas/lines.py": "".join(f"L{n} = {n}\n" for n in range(30))})
    return repo


def test_the_same_change_on_another_dev_has_the_same_digest(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "change")
    changed = _commit(repo, {"thomas/fix_me.py": "VALUE = 2\n", "thomas/new.py": "NEW = 1\n"})
    patch = _patch(repo, base, changed)
    git(repo, "checkout", "-q", base)
    moved = _commit(repo, {"README.md": "moved on\n"})

    assert _digest_on(repo, base, patch) == _digest_on(repo, moved, patch)


def test_a_three_way_apply_that_changes_what_lands_changes_the_digest(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "change")
    lines = (repo / "thomas" / "lines.py").read_text(encoding="utf-8").replace("L2 = 2", "L2 = 22")
    changed = _commit(repo, {"thomas/lines.py": lines})
    patch = _patch(repo, base, changed)
    git(repo, "checkout", "-q", base)
    other = (repo / "thomas" / "lines.py").read_text(encoding="utf-8").replace("L27 = 27", "L27 = 72")
    moved = _commit(repo, {"thomas/lines.py": other})

    assert _digest_on(repo, base, patch) != _digest_on(repo, moved, patch)
