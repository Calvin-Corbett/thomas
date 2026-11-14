"""The promoter's gate-file check answers in one git process, with the same verdicts as before.

Measured 2026-10-08: before every card the promoter asked git twice per enforced path -- 136 processes, 9.95 s of the
12.7 s it spent before showing a card. One `git cat-file --batch-check` gives the same answers; when git cannot answer
every one plainly, the check asks path by path exactly as it did before.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.cage import promoter_service
from scripts.cage import self_change_checks as checks
from scripts.cage.self_change_promoter import Outcome

GATE_A = "scripts/forge/gates/gate_a.py"
GATE_B = "scripts/forge/gates/gate_b.py"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _tree(repo: Path, files: dict[str, str | None]) -> str:
    """The tree of dev with *files* written (None deletes), without moving dev."""
    _git(repo, "checkout", "-q", "--detach", "dev")
    for path, text in files.items():
        target = repo / path
        if text is None:
            _git(repo, "rm", "-q", path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        _git(repo, "add", path)
    tree = _git(repo, "write-tree")
    _git(repo, "reset", "-q", "--hard", "dev")
    return tree


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "dev")
    manifest = {GATE_A: "x", GATE_B: "y", "scripts/forge/gates/not_there_yet.py": "z"}
    files = {checks.MANIFEST_PATH: json.dumps(manifest), GATE_A: "A = 1\n", GATE_B: "B = 1\n", "thomas/x.py": "X = 1\n"}
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


CASES = {
    "an ordinary change": {"thomas/x.py": "X = 2\n"},
    "a gate edited": {GATE_A: "A = 2\n"},
    "a gate deleted": {GATE_B: None},
    "a listed gate created": {"scripts/forge/gates/not_there_yet.py": "N = 1\n"},
    "the manifest edited": {checks.MANIFEST_PATH: json.dumps({GATE_A: "x"})},
    "two gates and a file": {GATE_A: "A = 3\n", GATE_B: "B = 3\n", "thomas/x.py": "X = 3\n"},
}


def _one_at_a_time(repo: Path, parent: str, tree: str, monkeypatch: pytest.MonkeyPatch) -> str | None:
    with monkeypatch.context() as patched:
        patched.setattr(checks, "_object_ids", lambda _repo, _specs: None)
        return checks.integrity_refusal(repo, parent, tree)


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_verdict_is_word_for_word_the_one_path_by_path_gave(
    repo: Path, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = _git(repo, "rev-parse", "dev")
    tree = _tree(repo, CASES[case])
    expected = _one_at_a_time(repo, parent, tree, monkeypatch)
    assert checks.integrity_refusal(repo, parent, tree) == expected
    assert (expected is None) == (case == "an ordinary change"), expected


def test_a_gate_change_is_still_refused_and_named(repo: Path) -> None:
    parent = _git(repo, "rev-parse", "dev")
    refusal = checks.integrity_refusal(repo, parent, _tree(repo, {GATE_B: None, "thomas/x.py": "X = 9\n"}))
    assert refusal is not None and GATE_B in refusal and "thomas/x.py" not in refusal


def test_it_asks_git_a_handful_of_times_not_twice_per_gate(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _git(repo, "rev-parse", "dev")
    tree = _tree(repo, {GATE_A: "A = 4\n"})
    calls: list[tuple[str, ...]] = []
    real = checks.run_git

    def counting(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(str(a) for a in args[1:3]))
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(checks, "run_git", counting)
    assert checks.integrity_refusal(repo, parent, tree) is not None
    assert len(calls) <= 3, calls  # reading the manifest (2) and one cat-file for every path at both revisions


def test_when_git_cannot_answer_in_one_pass_it_asks_path_by_path(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _git(repo, "rev-parse", "dev")
    tree = _tree(repo, {GATE_A: "A = 5\n"})
    real = checks.run_git

    def failing_batch(repo_: Path, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "cat-file":
            return subprocess.CompletedProcess(args, 128, "", "fatal: simulated")
        return real(repo_, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(checks, "run_git", failing_batch)
    refusal = checks.integrity_refusal(repo, parent, tree)
    assert refusal is not None and GATE_A in refusal


def test_an_answer_that_is_neither_an_id_nor_missing_means_ask_path_by_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def ambiguous(_repo: Path, *args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, "dev:x ambiguous\n", "")

    monkeypatch.setattr(checks, "run_git", ambiguous)
    assert checks._object_ids(Path("."), ["dev:x"]) is None
    assert checks._object_ids(Path("."), []) == []


@pytest.mark.parametrize(
    ("outcome", "rests"),
    [
        (None, True),
        (Outcome("withdrawn", "put back"), True),
        (Outcome("held", "the approval cards are tampered"), True),
        (Outcome("landed"), False),
        (Outcome("declined"), False),
        (Outcome("refused"), False),
        (Outcome("error"), False),
    ],
)
def test_the_loop_rests_unless_the_hand_in_left_the_inbox(outcome: Outcome | None, rests: bool) -> None:
    """A withdrawn hand-in goes back to the inbox: looking again at once would spin on it."""
    assert promoter_service._left_the_inbox(outcome) is not rests
