from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module("agent_commit", ROOT / "scripts" / "agent_commit.py")


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return str(proc.stdout or "").strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _workboard_text(*claims: str) -> str:
    claim_lines = "\n".join(f"- {claim}" for claim in claims) or "- none"
    active_tasks = []
    for idx, claim in enumerate(claims, start=1):
        scope = claim.split("scope=", 1)[1].split(";", 1)[0]
        agent = claim.split("agent=", 1)[1].split(";", 1)[0]
        task = claim.split("task=", 1)[1]
        active_tasks.append(f"- task_id=TASK-{idx}; agent={agent}; scope={scope}; summary={task}; status=in_progress")
    active_block = "\n".join(active_tasks) or "- none"
    return (
        "# Workboard\n\n"
        "## Agent Claims\n"
        f"{claim_lines}\n\n"
        "## Active Tasks\n"
        f"{active_block}\n\n"
        "## Up For Grabs\n"
        "- none\n\n"
        "## Issues / Blockers\n"
        "- none\n"
    )


def _init_repo(tmp_path: Path, *, claims: tuple[str, ...]) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _write(repo / "src" / "app.py", 'print("init")\n')
    _write(repo / "docs" / "note.md", "init\n")
    _write(repo / "CHANGELOG.md", "# Changelog\n")
    _write(repo / "pyproject.toml", '[project]\nname = "demo"\nversion = "0.1.0"\n')
    _write(repo / "thomas" / "__init__.py", '__version__ = "0.1.0"\n')
    workboard = repo / "plans" / "thomas" / "WORKBOARD.md"
    _write(workboard, _workboard_text(*claims))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo, workboard


def _passing_gates() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (("ok", (sys.executable, "-c", 'print("gate ok")')),)


def test_site_visual_proof_gate_only_runs_for_site_paths() -> None:
    assert mod._gate_applies("site_visual_proof", ["apps/site/src/app/page.tsx"]) is True
    assert mod._gate_applies("site_visual_proof", ["apps/site/verification/ui-proof.json"]) is True
    assert (
        mod._gate_applies("site_visual_proof", ["scripts/agent_commit.py", "tests/test_commit_gate_split.py"]) is False
    )
    assert mod._gate_applies("boot_smoke", ["scripts/agent_commit.py"]) is True


def test_agent_commit_succeeds_with_unrelated_dirty_paths(tmp_path: Path) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=("agent=codex; name=Codex; role=solo; parent=none; scope=src; task=Scoped commit",),
    )
    _write(repo / "src" / "app.py", 'print("scoped")\n')
    _write(repo / "docs" / "note.md", "dirty staged\n")
    _git(repo, "add", "docs/note.md")
    _write(repo / "outside.txt", "untracked\n")

    result = mod.commit_scoped_changes(
        message="feat: scoped commit",
        agent="codex",
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=_passing_gates(),
    )

    assert result.ok is True
    assert result.commit_sha
    status = _git(repo, "status", "--short")
    assert "docs/note.md" in status
    assert "outside.txt" in status
    assert "src/app.py" not in status
    body = _git(repo, "log", "-1", "--pretty=%B")
    assert "Thomas-Agent: codex" in body
    assert "Thomas-Commit-Mode: scoped-local" in body


def test_agent_commit_fallback_succeeds_without_active_claim(tmp_path: Path) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=("agent=claude; name=Claude; role=solo; parent=none; scope=docs; task=Other work",),
    )
    _write(repo / "src" / "app.py", 'print("fallback")\n')

    result = mod.commit_scoped_changes(
        message="feat: fallback commit",
        agent="codex",
        include_paths=["src/app.py"],
        allow_scope_fallback=True,
        fallback_reason="user approved scoped fallback",
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=_passing_gates(),
    )

    assert result.ok is True
    assert result.scope_source == mod.FALLBACK_SOURCE
    body = _git(repo, "log", "-1", "--pretty=%B")
    assert "Thomas-Commit-Mode: scoped-fallback" in body
    assert "Thomas-Fallback-Reason: user approved scoped fallback" in body


def test_agent_commit_fallback_requires_include_and_reason(tmp_path: Path) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=("agent=claude; name=Claude; role=solo; parent=none; scope=docs; task=Other work",),
    )
    _write(repo / "src" / "app.py", 'print("fallback")\n')

    result = mod.commit_scoped_changes(
        message="feat: fallback commit",
        agent="codex",
        allow_scope_fallback=True,
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=_passing_gates(),
    )

    assert result.ok is False
    assert result.blocker_class == "claim_scope_mismatch"
    assert result.scope_source == mod.FALLBACK_SOURCE
    assert result.next_step
    assert result.suggested_command


def test_agent_commit_fallback_rejects_overlap_with_other_claim(tmp_path: Path) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=("agent=claude; name=Claude; role=solo; parent=none; scope=src; task=Other work",),
    )
    _write(repo / "src" / "app.py", 'print("fallback")\n')

    result = mod.commit_scoped_changes(
        message="feat: fallback commit",
        agent="codex",
        include_paths=["src/app.py"],
        allow_scope_fallback=True,
        fallback_reason="user approved scoped fallback",
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=_passing_gates(),
    )

    assert result.ok is False
    assert result.blocker_class == "claim_scope_mismatch"
    assert "overlaps active workboard claim" in result.message


def test_agent_commit_fails_without_active_claim(tmp_path: Path) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=("agent=claude; name=Claude; role=solo; parent=none; scope=src; task=Other work",),
    )
    _write(repo / "src" / "app.py", 'print("changed")\n')

    result = mod.commit_scoped_changes(
        message="feat: missing claim",
        agent="codex",
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=_passing_gates(),
    )

    assert result.ok is False
    assert result.blocker_class == "claim_scope_mismatch"


def test_agent_commit_fails_with_multiple_active_claims(tmp_path: Path) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=(
            "agent=codex; name=Codex; role=solo; parent=none; scope=src; task=One",
            "agent=codex; name=Codex; role=solo; parent=none; scope=docs; task=Two",
        ),
    )
    _write(repo / "src" / "app.py", 'print("changed")\n')

    result = mod.commit_scoped_changes(
        message="feat: too many claims",
        agent="codex",
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=_passing_gates(),
    )

    assert result.ok is False
    assert result.blocker_class == "claim_scope_mismatch"


def test_agent_commit_rejects_include_outside_scope(tmp_path: Path) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=("agent=codex; name=Codex; role=solo; parent=none; scope=src; task=Scoped commit",),
    )
    _write(repo / "src" / "app.py", 'print("changed")\n')
    _write(repo / "docs" / "note.md", "changed\n")

    result = mod.commit_scoped_changes(
        message="feat: bad include",
        agent="codex",
        include_paths=["docs/note.md"],
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=_passing_gates(),
    )

    assert result.ok is False
    assert result.blocker_class == "claim_scope_mismatch"


def test_agent_commit_auto_includes_release_metadata_when_changed(tmp_path: Path) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=("agent=codex; name=Codex; role=solo; parent=none; scope=src; task=Scoped commit",),
    )
    _write(repo / "src" / "app.py", 'print("changed")\n')
    _write(repo / "CHANGELOG.md", "# Changelog\n\nnew\n")
    _write(repo / "thomas" / "__init__.py", '__version__ = "0.1.1"\n')

    result = mod.commit_scoped_changes(
        message="feat: release trio",
        agent="codex",
        dry_run=True,
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=_passing_gates(),
    )

    assert result.ok is True
    assert "src/app.py" in result.selected_paths
    assert "CHANGELOG.md" in result.selected_paths
    assert "thomas/__init__.py" in result.selected_paths
    assert "pyproject.toml" not in result.selected_paths


def test_agent_commit_does_not_include_release_metadata_when_clean(tmp_path: Path) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=("agent=codex; name=Codex; role=solo; parent=none; scope=src; task=Scoped commit",),
    )
    _write(repo / "src" / "app.py", 'print("changed")\n')

    result = mod.commit_scoped_changes(
        message="feat: no release trio",
        agent="codex",
        dry_run=True,
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=_passing_gates(),
    )

    assert result.ok is True
    assert result.selected_paths == ("src/app.py",)


def test_agent_commit_reports_branch_race(tmp_path: Path, monkeypatch) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=("agent=codex; name=Codex; role=solo; parent=none; scope=src; task=Scoped commit",),
    )
    _write(repo / "src" / "app.py", 'print("changed")\n')
    head = _git(repo, "rev-parse", "HEAD")
    call_count = {"value": 0}
    original_current_head = mod._current_head

    def fake_current_head(repo_root: Path) -> str:
        call_count["value"] += 1
        if call_count["value"] >= 2:
            return "f" * 40
        return original_current_head(repo_root)

    monkeypatch.setattr(mod, "_current_head", fake_current_head)

    result = mod.commit_scoped_changes(
        message="feat: race",
        agent="codex",
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=_passing_gates(),
    )

    assert result.ok is False
    assert result.blocker_class == "branch_race"
    assert _git(repo, "rev-parse", "HEAD") == head


def test_agent_commit_reports_local_gate_failure(tmp_path: Path) -> None:
    repo, workboard = _init_repo(
        tmp_path,
        claims=("agent=codex; name=Codex; role=solo; parent=none; scope=src; task=Scoped commit",),
    )
    _write(repo / "src" / "app.py", 'print("changed")\n')

    result = mod.commit_scoped_changes(
        message="feat: gate fail",
        agent="codex",
        repo_root=repo,
        workboard_path=workboard,
        local_gate_commands=(("bad", (sys.executable, "-c", 'import sys; print("nope"); sys.exit(1)')),),
    )

    assert result.ok is False
    assert result.blocker_class == "local_gate_failed"
    assert result.gate_name == "bad"
    assert "nope" in result.gate_output


def test_sync_live_index_resets_selected_paths_to_head(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    calls: list[list[str]] = []

    def fake_run_git(repo_root: Path, args: tuple[str, ...] | list[str], **kwargs):
        calls.append(list(args))

        class Proc:
            returncode = 0
            stderr = ""
            stdout = ""

        return Proc()

    monkeypatch.setattr(mod, "_run_git", fake_run_git)

    mod._sync_live_index(repo, ["src/app.py", "CHANGELOG.md"])

    assert calls == [["reset", "-q", "HEAD", "--", "src/app.py", "CHANGELOG.md"]]


def test_agent_commit_run_json_emits_blocker_payload(monkeypatch, capsys) -> None:
    fake_result = mod.CommitResult(
        ok=False,
        blocker_class="claim_scope_mismatch",
        message="missing claim",
        agent="codex",
        branch=None,
        claim_scopes=(),
        selected_paths=(),
        scope_source=mod.CLAIM_SOURCE,
        next_step="claim the scope",
        suggested_command='python scripts/agent_commit.py --agent codex --message "x"',
    )
    monkeypatch.setattr(mod, "commit_scoped_changes", lambda **kwargs: fake_result)

    rc = mod.run(["--message", "feat: json", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["message"] == "missing claim"
    assert payload["next_step"] == "claim the scope"
    assert payload["suggested_command"]
