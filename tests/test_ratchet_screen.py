"""What merging a candidate onto dev would do, known before a green, a proof or a model is spent.

Measured 2026-09-24: every one of the 11 distinct commits the spec's sources name
conflicts with dev, fcb5f06 in exactly two test files. merge-tree writes objects,
so the screen runs it against a temporary store, never the running copy's.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.cage import self_change_checks as checks

from tests.ratchet_support import candidate, commit, dev_moves, git, make_repo, on_ref
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.screen import final_refusal, screen

THREE = "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n\n\ndef test_three():\n    pass\n"


def _objects(repo: Path) -> int:
    return sum(1 for p in (repo / ".git" / "objects").rglob("*") if p.is_file())


def test_content_dev_already_has_is_already_on_dev_and_nothing_is_written(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    sha = on_ref(repo, "refs/heads/fix/a", base, {"thomas/core/widget.py": "VALUE = 2\n"}, "fix")
    dev = dev_moves(repo, "the same fix, landed another way", {"thomas/core/widget.py": "VALUE = 2\n"})
    before = _objects(repo)

    found = screen(Repo(repo), dev, candidate(sha))

    assert found.already_on_dev
    assert _objects(repo) == before


def test_a_clean_merge_needs_no_model_and_leaves_coordination_files_out(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    files = {"thomas/core/extra.py": "X = 1\n", "plans/thomas/WORKBOARD.md": "claimed\n"}
    sha = on_ref(repo, "refs/heads/feature/x", base, files, "x")
    dev = dev_moves(repo)

    found = screen(Repo(repo), dev, candidate(sha))

    assert not found.already_on_dev and found.mechanical
    assert found.changes == (("A", "thomas/core/extra.py"),)
    assert found.dropped == ("plans/thomas/WORKBOARD.md",)
    assert found.refusal == ""
    board = final_refusal(Repo(repo), dev, "", ["plans/thomas/WORKBOARD.md", "thomas/core/extra.py"])
    assert board == "it changes coordination files the ratchet leaves out: plans/thomas/WORKBOARD.md"


def test_each_conflict_says_which_side_to_keep(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    ours = {"tests/test_widget.py": None, "thomas/core/widget.py": "VALUE = 3\n", "thomas/core/old.py": "OLD = 2\n"}
    sha = on_ref(repo, "refs/heads/split", base, ours, "split")
    theirs = {
        "tests/test_widget.py": "def test_widget():\n    assert True\n",
        "thomas/core/widget.py": "VALUE = 4\n",
        "thomas/core/old.py": None,
    }
    dev = dev_moves(repo, "dev edits", theirs)

    found = screen(Repo(repo), dev, candidate(sha))

    kinds = {c.path: c.kind for c in found.conflicts}
    assert kinds == {
        "tests/test_widget.py": "candidate_deleted",
        "thomas/core/widget.py": "both_changed",
        "thomas/core/old.py": "dev_deleted",
    }
    assert "keep dev's file" in next(c.advice for c in found.conflicts if c.kind == "candidate_deleted")
    assert any(r.startswith("thomas/core/old.py (dev deleted it") for r in found.resurrected)
    assert not found.mechanical and "3 conflict(s)" in found.needs()


def test_the_promoters_refusals_are_known_in_its_own_words(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    dev = git(repo, "rev-parse", "dev")
    gate = on_ref(repo, "refs/heads/gate", dev, {"scripts/forge/gates/gate.py": "GATE = 2\n"}, "gate")
    spaced = on_ref(repo, "refs/heads/spaced", dev, {"plans/a b/notes.md": "x\n"}, "spaced")

    found = screen(Repo(repo), dev, candidate(gate))

    assert found.refusal == checks.integrity_refusal(repo, dev, gate)
    assert found.refusal.startswith("the change edits enforced gate file(s): scripts/forge/gates/gate.py")
    assert "a file header the promoter cannot read safely" in screen(Repo(repo), dev, candidate(spaced)).refusal


def test_copied_tests_and_lines_that_must_not_land_are_flagged(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    commit(repo, {"tests/test_split_a.py": THREE}, "dev's own split")
    base = git(repo, "rev-parse", "dev")
    files = {"tests/test_split_b.py": THREE, "thomas/core/note.py": "# Robin wanted this\nNOTE = 1\n"}
    sha = on_ref(repo, "refs/heads/copy", base, files, "copy")
    dev = dev_moves(repo)

    found = screen(Repo(repo), dev, candidate(sha))

    assert found.duplicate_tests == tuple(f"tests/test_split_b.py::{n}" for n in ("test_one", "test_three", "test_two"))
    assert found.flags == ("a line naming you in thomas/core/note.py",)
    assert not found.mechanical


def test_a_file_the_graveyard_records_as_dead_does_not_come_back(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    record = {
        "id": "file-1",
        "kind": "file",
        "name": "thomas/core/dead.py",
        "dead_sha": "0" * 40,
        "deleted_on": "2026-08-01",
        "reason": "retired",
        "by": "test",
        "refs": "",
    }
    commit(repo, {"docs/ops/graveyard.json": json.dumps({"records": [record]})}, "graveyard")
    base = git(repo, "rev-parse", "dev")
    sha = on_ref(repo, "refs/heads/back", base, {"thomas/core/dead.py": "BACK = 1\n"}, "back")
    dev = dev_moves(repo)

    found = screen(Repo(repo), dev, candidate(sha))

    assert found.resurrected == ("thomas/core/dead.py (the graveyard records it as dead)",)


def test_a_stacked_candidate_brings_only_its_own_commit(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    lower = on_ref(repo, "refs/heads/lower", base, {"thomas/core/widget.py": "VALUE = 2\n"}, "lower")
    upper = on_ref(repo, "refs/salvage/run/upper", lower, {"thomas/core/c.py": "C = 1\n"}, "upper")
    dev = dev_moves(repo, "lower landed another way", {"thomas/core/widget.py": "VALUE = 5\n"})

    found = screen(Repo(repo), dev, candidate(upper), onto=lower)

    assert found.conflicts == ()
    assert found.changes == (("A", "thomas/core/c.py"),)
