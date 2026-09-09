from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.crew.brief import commit as scoped
from scripts.crew.brief import commit_integrity
from scripts.forge import commit_master
from scripts.forge.commit_master import CommitMaster

REPO = Path(__file__).resolve().parents[1]


def _body(sha: str) -> str:
    return subprocess.run(
        ["git", "show", "-s", "--format=%B", sha],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.mark.parametrize("sha", ["7df98718", "e78b755f"])
def test_observed_duplicate_trailer_commits_are_invalid_fixtures(sha: str) -> None:
    body = _body(sha)
    assert body.count("Thomas-Agent: claude") == 2
    with pytest.raises(commit_integrity.CommitIntegrityError):
        commit_integrity.validate_caller_message(body)


@pytest.mark.parametrize(
    "forged",
    [
        "Thomas-Agent: claude",
        "thomas-agent: claude",
        " Thomas - Agent : claude ",
        "THOMAS   AGENT: claude",
        "body\n\nThomas-Agent: first\nThomas-Agent: first",
        "body\n\nThomas-Agent: first\nThomas-Agent: other",
        "body\n\nThomas-Committed-By: attacker",
    ],
)
def test_both_commit_paths_reject_caller_reserved_variants(forged: str) -> None:
    selection = scoped.ScopeSelection(scopes=("src",), source=scoped.CLAIM_SOURCE)
    with pytest.raises(ValueError):
        scoped._build_commit_message(f"feat: x\n\n{forged}", agent="codex", scope_selection=selection)
    master = object.__new__(CommitMaster)
    with pytest.raises(ValueError):
        master._compose_message({"message": forged, "agent": "red", "id": "s1"})


def test_scoped_trailers_have_exact_cardinality_and_order() -> None:
    selection = scoped.ScopeSelection(scopes=("src/a.py", "src/b.py"), source=scoped.CLAIM_SOURCE)
    message = scoped._build_commit_message("feat: exact", agent="codex", scope_selection=selection)
    expected = ["Thomas-Agent", "Thomas-Claim", "Thomas-Scope", "Thomas-Commit-Mode"]
    block = message.rstrip().split("\n\n")[-1].splitlines()
    assert [line.split(":", 1)[0] for line in block] == expected
    assert all(message.count(f"{key}:") == 1 for key in expected)


def test_master_trailers_have_exact_cardinality_and_order() -> None:
    master = object.__new__(CommitMaster)
    message = master._compose_message({"message": "feat: exact", "agent": "codex", "id": "s1"})
    expected = ["Thomas-Submitted-By", "Thomas-Committed-By", "Thomas-Submission-Id", "Thomas-Gated"]
    block = message.rstrip().split("\n\n")[-1].splitlines()
    assert [line.split(":", 1)[0] for line in block] == expected
    assert all(message.count(f"{key}:") == 1 for key in expected)


def test_master_privileged_helpers_resolve_inside_protected_gate_boundary() -> None:
    protected = (REPO / "scripts" / "forge" / "gates").resolve()
    dependencies = commit_master._verify_privileged_dependencies_protected()

    assert {path.name for path in dependencies} == {"commit_master_inbox.py", "commit_master_cli.py"}
    assert all(path.is_relative_to(protected) for path in dependencies)


def test_master_refuses_privileged_helper_outside_protected_gate_boundary(tmp_path: Path) -> None:
    protected = tmp_path / "protected" / "scripts" / "forge" / "gates"
    protected.mkdir(parents=True)
    outside = tmp_path / "unprotected" / "commit_master_inbox.py"

    with pytest.raises(RuntimeError, match="outside protected gate boundary"):
        commit_master._verify_privileged_dependencies_protected((outside,), protected_root=protected)


def test_master_inbox_facade_preserves_monkeypatched_core_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = subprocess.CompletedProcess(["git"], 0, stdout="one.py\ntwo.py\n", stderr="")
    monkeypatch.setattr(commit_master, "_git", lambda *_args, **_kwargs: result)

    assert commit_master._submission_changed_files(tmp_path, None) == ["one.py", "two.py"]


def test_master_cli_facade_dispatches_through_monkeypatched_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def fake_submit(args: object) -> int:
        observed["args"] = args
        return 17

    monkeypatch.setattr(commit_master, "_cmd_submit", fake_submit)
    status = commit_master.main(["submit", "--agent", "codex", "--message", "test"])

    assert status == 17
    assert vars(observed["args"])["patch_file"] is None


def test_verified_commit_readback_checks_tree_parent_message_and_order(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Thomas Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    parent = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / "a.txt").write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    tree = subprocess.check_output(["git", "write-tree"], cwd=tmp_path, text=True).strip()
    trailers = [("Thomas-Agent", "codex"), ("Thomas-Scope", "a.txt")]
    message = commit_integrity.compose_message("test: object", trailers)
    sha = subprocess.run(
        ["git", "commit-tree", tree, "-p", parent],
        cwd=tmp_path,
        input=message,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    verified = commit_integrity.read_verified_commit(
        tmp_path,
        sha,
        expected_tree=tree,
        expected_parent=parent,
        expected_body="test: object",
        expected_trailers=trailers,
    )
    assert verified.sha == sha
    with pytest.raises(commit_integrity.CommitIntegrityError):
        commit_integrity.read_verified_commit(
            tmp_path,
            sha,
            expected_tree=tree,
            expected_parent=parent,
            expected_body="test: object",
            expected_trailers=list(reversed(trailers)),
        )


def test_claude_instructions_delegate_reserved_trailers_to_commit_tools() -> None:
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "MUST tag every commit with `Thomas-Agent: claude`" not in text
    assert "reserved Thomas trailers" in text
