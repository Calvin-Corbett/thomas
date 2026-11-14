"""Which tests prove a candidate: its own, the ones that import what it changes, and the architecture test.

Not a search for a file's stem: on 2026-09-24 "config" matched 412 test files and
"thomas.core.config" 153.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.ratchet_support import commit, git, make_repo, on_ref
from thomas.server.ratchet import gitrepo
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.proof_set import (
    ARCHITECTURE_TEST,
    ProofSet,
    import_patterns,
    module_name,
    read_tests,
    select,
)


def _repo(tmp_path: Path) -> tuple[Repo, str]:
    repo = make_repo(tmp_path)
    commit(
        repo,
        {
            "tests/test_other.py": "import thomas.core.widget as w\n\n\ndef test_other():\n    assert w.VALUE\n",
            "tests/test_words.py": 'def test_words():\n    assert "widget" in "a widget"\n',
            "tests/test_nearby.py": "from thomas.core import widgets_extra\n",
            "tests/test_docs.py": 'README = "docs/readme.md"\n\n\ndef test_docs():\n    assert README\n',
            "tests/test_server_csrf_audit.py": "def test_every_route():\n    pass\n",
        },
        "more tests",
    )
    return Repo(repo), git(repo, "rev-parse", "dev")


def test_the_tests_that_import_a_changed_module_are_chosen_by_dotted_name(tmp_path: Path) -> None:
    repo, dev = _repo(tmp_path)

    chosen = select(repo, dev, ["thomas/core/widget.py"])

    assert chosen.files == ("tests/test_other.py", "tests/test_widget.py", ARCHITECTURE_TEST)
    assert chosen.left_out == 0


def test_the_candidates_own_tests_come_first_and_the_cap_is_recorded(tmp_path: Path) -> None:
    repo, dev = _repo(tmp_path)

    chosen = select(repo, dev, ["tests/test_words.py", "thomas/core/widget.py"], limit=3)

    assert chosen.files == ("tests/test_words.py", "tests/test_other.py", ARCHITECTURE_TEST)
    assert chosen.left_out == 1
    assert select(repo, dev, ["tests/test_gone.py"]).files == (ARCHITECTURE_TEST,)
    assert ProofSet(("a", "b", "c")).shards(2) == [["a", "b"], ["c"]]


def test_a_file_that_is_not_a_module_is_proven_by_the_tests_that_name_it(tmp_path: Path) -> None:
    repo, dev = _repo(tmp_path)

    assert select(repo, dev, ["docs/readme.md"]).files == ("tests/test_docs.py", ARCHITECTURE_TEST)
    assert select(repo, dev, ["thomas/server/app.py"]).files == ("tests/test_server_csrf_audit.py", ARCHITECTURE_TEST)


def test_a_test_file_the_change_deletes_is_named_for_the_base_side(tmp_path: Path) -> None:
    repo, dev = _repo(tmp_path)
    dropped = on_ref(repo.path, "refs/heads/drop", dev, {"tests/test_widget.py": None}, "drop")

    chosen = select(repo, dropped, ["tests/test_widget.py"], base=dev)

    assert chosen.gone == ("tests/test_widget.py",)
    assert "tests/test_widget.py" not in chosen.files
    assert select(repo, dropped, ["tests/test_widget.py"]).gone == ()


def test_every_test_file_is_read_in_a_fixed_number_of_git_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One ``git show`` per test file was 1,787 git processes and 130-322 s per selection on dev, which has 1,783
    test files (measured 2026-10-07). The count no longer grows with the number of files."""
    repo, _dev = _repo(tmp_path)
    many = {f"tests/test_many_{n}.py": f"import thomas.core.widget\n\n\ndef test_{n}():\n    pass\n" for n in range(40)}
    tip = commit(repo.path, many, "forty more tests")
    calls: list[list[str]] = []
    real = gitrepo.subprocess.run

    def counting(command: list[str], *args: Any, **kwargs: Any) -> Any:
        calls.append(list(command))
        return real(command, *args, **kwargs)

    monkeypatch.setattr(gitrepo.subprocess, "run", counting)
    chosen = select(repo, tip, ["thomas/core/widget.py"])

    assert len(chosen.files) == 43 and chosen.left_out == 0
    assert len(calls) <= 3, [command[7:9] for command in calls]


def test_a_test_file_reads_as_git_show_reads_it(tmp_path: Path) -> None:
    """Byte for byte through one ``cat-file --batch``, then decoded as ``git show``'s text was: bad bytes replaced,
    every line ending a newline. A file ending without one, an empty file and a nested one come through too."""
    repo, _dev = _repo(tmp_path)
    raw = {
        "tests/test_crlf.py": b"import thomas.core.widget\r\nx = 1\r\n",
        "tests/test_latin.py": b"NAME = '\xe9t\xe9'\n",
        "tests/test_no_newline.py": "LABEL = 'café'".encode(),
        "tests/__init__.py": b"",
        "tests/deep/test_inner.py": b"from thomas.core import widget\n",
        "tests/data/fixture.json": b"{}\n",
    }
    for rel, data in raw.items():
        (repo.path / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo.path / rel).write_bytes(data)
    git(repo.path, "add", "-A")
    git(repo.path, "commit", "-qm", "odd files")
    tree = repo.out("rev-parse", "HEAD^{tree}")

    paths, texts = read_tests(repo, tree)

    assert "tests/data/fixture.json" in paths and "tests/data/fixture.json" not in texts
    for path in [p for p in paths if p.endswith(".py")]:
        assert texts[path] == repo.run("show", f"{tree}:{path}").stdout, path
    assert texts["tests/test_crlf.py"] == "import thomas.core.widget\nx = 1\n"
    with pytest.raises(gitrepo.GitFailed):
        repo.blobs(["0" * 40])


def test_module_names_and_import_patterns() -> None:
    assert module_name("thomas/core/config.py") == "thomas.core.config"
    assert module_name("thomas/server/ratchet/__init__.py") == "thomas.server.ratchet"
    assert module_name("tests/_chat_delegation_support.py") == "tests._chat_delegation_support"
    assert module_name("docs/readme.md") == ""
    assert module_name("web/app.js") == ""
    assert len(import_patterns("thomas")) == 1
    assert len(import_patterns("thomas.core.widget")) == 2
