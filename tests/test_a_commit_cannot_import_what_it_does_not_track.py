"""A commit cannot import a module it does not track (2026-09-07).

Four modules under ``thomas/`` were imported by committed files and never
added to git: two identity modules behind every board tool, the delegation
tool receipts, and the work execution adapter. Every working tree that had
the files kept passing; a clean clone of ``dev`` failed with an ImportError on
the server and on every board command. Pre-commit hooks run on the working
tree and cannot see this; only a clean clone could, and nobody makes one.

The gate reads the imports of every staged Python file and refuses the commit
when one resolves to a module that exists in the tree but is not tracked and
not staged. ``--all`` walks every tracked file instead, which is the scan that
found the four.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from scripts.forge.gates import untracked_import_gate as gate


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "thomas" / "core").mkdir(parents=True)
    (tmp_path / "thomas" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "thomas" / "core" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "thomas" / "core" / "config.py").write_text("SETTING = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def test_a_staged_file_that_imports_an_untracked_module_is_refused(repo: Path) -> None:
    (repo / "thomas" / "core" / "identity.py").write_text("def who():\n    return 'x'\n", encoding="utf-8")
    (repo / "thomas" / "core" / "board.py").write_text(
        "from thomas.core import identity\nfrom thomas.core.config import SETTING\n", encoding="utf-8"
    )
    _git(repo, "add", "thomas/core/board.py")

    findings = gate.check_staged(repo)
    assert findings == [("thomas/core/board.py", "thomas.core.identity", "thomas/core/identity.py")]
    assert gate.main(["--repo", str(repo)]) == 1


def test_staging_the_module_too_lets_the_commit_through(repo: Path) -> None:
    (repo / "thomas" / "core" / "identity.py").write_text("def who():\n    return 'x'\n", encoding="utf-8")
    (repo / "thomas" / "core" / "board.py").write_text("import thomas.core.identity as ident\n", encoding="utf-8")
    _git(repo, "add", "thomas/core/board.py", "thomas/core/identity.py")

    assert gate.check_staged(repo) == []
    assert gate.main(["--repo", str(repo)]) == 0


def test_imports_of_tracked_modules_and_the_standard_library_are_not_findings(repo: Path) -> None:
    (repo / "thomas" / "core" / "board.py").write_text(
        "import json\nfrom pathlib import Path\nfrom thomas.core.config import SETTING\nimport importlib\n"
        "importlib.import_module('thomas.core.config')\n",
        encoding="utf-8",
    )
    _git(repo, "add", "thomas/core/board.py")
    assert gate.check_staged(repo) == []


def test_the_whole_tree_scan_finds_a_committed_importer_of_an_untracked_module(repo: Path) -> None:
    """The scan that found tonight's four: the importer is already in HEAD."""
    (repo / "thomas" / "core" / "board.py").write_text("from thomas.core import identity\n", encoding="utf-8")
    _git(repo, "add", "thomas/core/board.py")
    _git(repo, "commit", "-q", "-m", "importer without its module")
    (repo / "thomas" / "core" / "identity.py").write_text("def who():\n    return 'x'\n", encoding="utf-8")

    assert gate.check_staged(repo) == []  # nothing staged: the staged gate is silent
    assert gate.check_all(repo) == [("thomas/core/board.py", "thomas.core.identity", "thomas/core/identity.py")]
    assert gate.main(["--repo", str(repo), "--all"]) == 1


def test_the_gate_names_both_files_in_its_verdict(repo: Path, capsys) -> None:
    (repo / "thomas" / "core" / "identity.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "thomas" / "core" / "board.py").write_text("from thomas.core.identity import x\n", encoding="utf-8")
    _git(repo, "add", "thomas/core/board.py")
    assert gate.main(["--repo", str(repo)]) == 1
    out = capsys.readouterr().out
    assert "thomas/core/board.py" in out and "thomas/core/identity.py" in out and "git add" in out


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__]))
