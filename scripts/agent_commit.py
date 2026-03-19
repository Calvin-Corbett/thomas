#!/usr/bin/env python3
"""Create scoped agent commits without bundling unrelated repo dirt."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts import agent_identity
    from scripts import check_workboard_claims as claims_gate
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    import agent_identity  # type: ignore
    import check_workboard_claims as claims_gate  # type: ignore


ROOT = _REPO_ROOT
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
RELEASE_METADATA_FILES: tuple[str, ...] = ("CHANGELOG.md", "pyproject.toml", "thomas/__init__.py")
RELEASE_SCOPE_IGNORE = ",".join(RELEASE_METADATA_FILES)
PATH_SCOPED_GATES: dict[str, tuple[str, ...]] = {
    "site_visual_proof": (
        "apps/site/src/app/",
        "apps/site/src/components/",
        "apps/site/verification/",
    ),
}
LOCAL_GATE_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("protected_files", (sys.executable, "scripts/check_protected_files_gate.py")),
    ("agent_safety", (sys.executable, "scripts/validate_agent_changes.py")),
    ("exception_handler", (sys.executable, "scripts/check_exception_handler_gate.py")),
    ("duplicate_filename", (sys.executable, "scripts/check_duplicate_filename_gate.py")),
    (
        "active_folder_guard",
        (
            sys.executable,
            "scripts/active_folders.py",
            "guard-staged",
            "--auto-claim-staged",
            "--require-explicit-agent",
            "--allow-presence-override",
            "--presence-override-reason",
            "scoped local commit isolates claimed changes from unrelated dirty repo activity",
        ),
    ),
    ("precommit_skip_policy", (sys.executable, "scripts/check_precommit_skip_policy.py")),
    ("core_overhead", (sys.executable, "scripts/check_core_overhead_guard.py")),
    ("worktree_rules", (sys.executable, "scripts/check_worktree_rules_gate.py")),
    ("worktree_branch", (sys.executable, "scripts/check_worktree_branch_guard.py")),
    ("workboard_claims", (sys.executable, "scripts/check_workboard_claims.py", "--require-identity-metadata")),
    ("workboard_task_problems", (sys.executable, "scripts/check_workboard_task_problems.py")),
    (
        "workboard_changed_files",
        (
            sys.executable,
            "scripts/check_workboard_changed_files.py",
            "--staged",
            "--require-identity-metadata",
            "--ignore",
            RELEASE_SCOPE_IGNORE,
        ),
    ),
    (
        "workboard_agent_claim",
        (
            sys.executable,
            "scripts/check_workboard_agent_claim.py",
            "--enforce-staged-scope",
            "--staged-scope-ignore",
            RELEASE_SCOPE_IGNORE,
            "--enforce-parent-throughput",
            "--parent-target-workers",
            "2",
            "--parent-min-ready-suggestions",
            "2",
        ),
    ),
    ("workboard_issue_smoke", (sys.executable, "scripts/workboard_issue.py", "--help")),
    ("workboard_problem_record_smoke", (sys.executable, "scripts/workboard_problem_record.py", "--help")),
    ("monolith_guard", (sys.executable, "scripts/check_monolith_guard.py", "--staged-only")),
    (
        "monolith_filename_guard",
        (sys.executable, "scripts/check_monolith_filename_guard.py", "--staged-only"),
    ),
    ("protected_deletion", (sys.executable, "scripts/check_deletions.py", "--staged-only")),
    ("feature_registry", (sys.executable, "scripts/check_feature_registry.py")),
    ("repo_identity", (sys.executable, "scripts/check_repo_identity.py")),
    (
        "release_update",
        (sys.executable, "scripts/check_release_update_gate.py", "--no-include-untracked"),
    ),
    ("site_visual_proof", (sys.executable, "scripts/check_site_visual_proof.py")),
    ("boot_smoke", (sys.executable, "scripts/check_boot_smoke_gate.py")),
    ("type_safety", (sys.executable, "scripts/check_type_safety_gate.py")),
    ("circular_imports", (sys.executable, "scripts/check_circular_imports_gate.py")),
    ("changelog", (sys.executable, "scripts/check_changelog_gate.py")),
)


@dataclass(frozen=True)
class CommitResult:
    ok: bool
    blocker_class: str | None
    message: str
    agent: str
    branch: str | None
    claim_scopes: tuple[str, ...]
    selected_paths: tuple[str, ...]
    commit_sha: str | None = None
    dry_run: bool = False
    gate_name: str | None = None
    gate_output: str = ""


def _normalize_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    while "//" in path:
        path = path.replace("//", "/")
    return path.strip("/")


def _scope_matches_path(scope: str, rel_path: str) -> bool:
    scope_norm = _normalize_path(scope).lower()
    path_norm = _normalize_path(rel_path).lower()
    if not scope_norm or not path_norm:
        return False
    if scope_norm in {".", "*", "**"}:
        return True
    if any(ch in scope_norm for ch in "*?["):
        import fnmatch

        if fnmatch.fnmatchcase(path_norm, scope_norm):
            return True
        if scope_norm.endswith("/**"):
            base = scope_norm[:-3].rstrip("/")
            return bool(base) and (path_norm == base or path_norm.startswith(base + "/"))
        return False
    return path_norm == scope_norm or path_norm.startswith(scope_norm + "/")


def _run_git(repo_root: Path, args: Sequence[str], *, env: dict[str, str] | None = None, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_output(repo_root: Path, args: Sequence[str], *, env: dict[str, str] | None = None) -> str:
    proc = _run_git(repo_root, args, env=env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return str(proc.stdout or "").strip()


def _current_head(repo_root: Path) -> str:
    return _git_output(repo_root, ["rev-parse", "HEAD"])


def _current_branch(repo_root: Path) -> str:
    branch = _git_output(repo_root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    if not branch:
        raise RuntimeError("detached HEAD is not supported for scoped agent commits")
    return branch


def _parse_status_paths(repo_root: Path) -> list[str]:
    proc = _run_git(repo_root, ["status", "--porcelain"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git status --porcelain failed")
    changed: list[str] = []
    for raw in str(proc.stdout or "").splitlines():
        line = str(raw or "").rstrip()
        if not line:
            continue
        token = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in token:
            token = token.split(" -> ", 1)[1].strip()
        normalized = _normalize_path(token)
        if normalized and normalized not in changed:
            changed.append(normalized)
    return changed


def _resolve_active_claim(agent: str, workboard_path: Path) -> claims_gate.Claim:
    violations, claims, _tasks, _grab, _issues = claims_gate.evaluate_board(
        workboard_path,
        require_identity_metadata=True,
    )
    agent_key = str(agent or "").strip().lower()
    mine = [claim for claim in claims if str(claim.agent or "").strip().lower() == agent_key]
    if not mine:
        raise ValueError(f"agent '{agent}' has no active claim in {workboard_path}")
    if len(mine) != 1:
        raise ValueError(f"agent '{agent}' has {len(mine)} active claims; scoped commit requires exactly one")
    if violations:
        raise RuntimeError("; ".join(str(item) for item in violations))
    return mine[0]


def _selected_paths(repo_root: Path, claim: claims_gate.Claim, include_paths: Sequence[str]) -> list[str]:
    changed = _parse_status_paths(repo_root)
    changed_set = set(changed)
    include_norm = [_normalize_path(item) for item in include_paths if _normalize_path(item)]
    if include_norm:
        outside = [path for path in include_norm if not any(_scope_matches_path(scope, path) for scope in claim.scopes)]
        if outside:
            raise ValueError(
                "requested include path(s) are outside the active claim scope: " + ", ".join(outside)
            )
        in_scope = [path for path in include_norm if path in changed_set]
    else:
        in_scope = [path for path in changed if any(_scope_matches_path(scope, path) for scope in claim.scopes)]

    selected = sorted(dict.fromkeys(in_scope))
    if selected:
        for path in RELEASE_METADATA_FILES:
            if path in changed_set and path not in selected:
                selected.append(path)
    return selected


def _build_commit_message(message: str, *, agent: str, claim: claims_gate.Claim) -> str:
    base = str(message or "").strip()
    if not base:
        raise ValueError("commit message is required")
    trailers = [
        f"Thomas-Agent: {agent}",
        f"Thomas-Claim: {','.join(claim.scopes)}",
        "Thomas-Commit-Mode: scoped-local",
    ]
    return base.rstrip() + "\n\n" + "\n".join(trailers) + "\n"


def _temp_index_env(agent: str, index_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(index_path)
    env["AGENT_ID"] = agent
    env["THOMAS_AGENT_ID"] = agent
    return env


def _gate_applies(gate_name: str, selected_paths: Sequence[str]) -> bool:
    prefixes = PATH_SCOPED_GATES.get(gate_name)
    if not prefixes:
        return True
    return any(_normalize_path(path).startswith(prefix) for path in selected_paths for prefix in prefixes)


def _prepare_temp_index(repo_root: Path, *, agent: str, selected_paths: Sequence[str]) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    holder = tempfile.TemporaryDirectory(prefix="thomas-agent-commit-")
    index_path = Path(holder.name) / "index"
    env = _temp_index_env(agent, index_path)
    _git_output(repo_root, ["read-tree", "HEAD"], env=env)
    if selected_paths:
        proc = _run_git(repo_root, ["add", "-A", "--", *selected_paths], env=env)
        if proc.returncode != 0:
            holder.cleanup()
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git add failed for temporary index")
    return index_path, holder


def _run_local_gates(
    repo_root: Path,
    *,
    agent: str,
    index_path: Path,
    selected_paths: Sequence[str],
    local_gate_commands: Sequence[tuple[str, Sequence[str]]],
) -> tuple[bool, str | None, str]:
    env = _temp_index_env(agent, index_path)
    for gate_name, command in local_gate_commands:
        if not _gate_applies(gate_name, selected_paths):
            continue
        proc = subprocess.run(
            list(command),
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            return False, gate_name, output
    return True, None, ""


def _create_commit_object(repo_root: Path, *, agent: str, index_path: Path, parent_head: str, message: str) -> str:
    env = _temp_index_env(agent, index_path)
    tree = _git_output(repo_root, ["write-tree"], env=env)
    proc = _run_git(repo_root, ["commit-tree", tree, "-p", parent_head], env=env, input_text=message)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git commit-tree failed")
    return str(proc.stdout or "").strip()


def _update_branch_ref(repo_root: Path, *, branch: str, commit_sha: str, expected_head: str) -> None:
    proc = _run_git(repo_root, ["update-ref", f"refs/heads/{branch}", commit_sha, expected_head])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git update-ref failed")


def _sync_live_index(repo_root: Path, selected_paths: Sequence[str]) -> None:
    if not selected_paths:
        return
    proc = _run_git(repo_root, ["add", "-A", "--", *selected_paths])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git add failed while syncing live index")


def commit_scoped_changes(
    *,
    message: str,
    agent: str | None = None,
    include_paths: Sequence[str] = (),
    dry_run: bool = False,
    repo_root: Path = ROOT,
    workboard_path: Path = DEFAULT_WORKBOARD,
    local_gate_commands: Sequence[tuple[str, Sequence[str]]] = LOCAL_GATE_COMMANDS,
) -> CommitResult:
    resolved_agent = agent_identity.resolve_agent(agent, include_name_fallback=True)
    if not resolved_agent:
        return CommitResult(
            ok=False,
            blocker_class="claim_scope_mismatch",
            message="agent id is required; pass --agent or set AGENT_ID/THOMAS_AGENT_ID",
            agent="",
            branch=None,
            claim_scopes=(),
            selected_paths=(),
            dry_run=bool(dry_run),
        )

    try:
        claim = _resolve_active_claim(resolved_agent, workboard_path)
    except ValueError as exc:
        return CommitResult(
            ok=False,
            blocker_class="claim_scope_mismatch",
            message=str(exc),
            agent=resolved_agent,
            branch=None,
            claim_scopes=(),
            selected_paths=(),
            dry_run=bool(dry_run),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return CommitResult(
            ok=False,
            blocker_class="broken_repo_tool",
            message=f"could not resolve active claim: {exc}",
            agent=resolved_agent,
            branch=None,
            claim_scopes=(),
            selected_paths=(),
            dry_run=bool(dry_run),
        )

    try:
        selected_paths = _selected_paths(repo_root, claim, include_paths)
    except ValueError as exc:
        return CommitResult(
            ok=False,
            blocker_class="claim_scope_mismatch",
            message=str(exc),
            agent=resolved_agent,
            branch=None,
            claim_scopes=tuple(claim.scopes),
            selected_paths=(),
            dry_run=bool(dry_run),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return CommitResult(
            ok=False,
            blocker_class="broken_repo_tool",
            message=f"could not compute changed paths: {exc}",
            agent=resolved_agent,
            branch=None,
            claim_scopes=tuple(claim.scopes),
            selected_paths=(),
            dry_run=bool(dry_run),
        )

    claimed_changed = [path for path in selected_paths if path not in RELEASE_METADATA_FILES]
    if not claimed_changed:
        return CommitResult(
            ok=False,
            blocker_class="no_claimed_changes",
            message="no changed files inside the active claim scope were found for this commit",
            agent=resolved_agent,
            branch=None,
            claim_scopes=tuple(claim.scopes),
            selected_paths=tuple(selected_paths),
            dry_run=bool(dry_run),
        )

    branch: str | None = None
    holder: tempfile.TemporaryDirectory[str] | None = None
    try:
        branch = _current_branch(repo_root)
        head_before = _current_head(repo_root)
        full_message = _build_commit_message(message, agent=resolved_agent, claim=claim)
        index_path, holder = _prepare_temp_index(repo_root, agent=resolved_agent, selected_paths=selected_paths)
        gates_ok, gate_name, gate_output = _run_local_gates(
            repo_root,
            agent=resolved_agent,
            index_path=index_path,
            selected_paths=selected_paths,
            local_gate_commands=local_gate_commands,
        )
        if not gates_ok:
            return CommitResult(
                ok=False,
                blocker_class="local_gate_failed",
                message=f"local gate failed: {gate_name}",
                agent=resolved_agent,
                branch=branch,
                claim_scopes=tuple(claim.scopes),
                selected_paths=tuple(selected_paths),
                dry_run=bool(dry_run),
                gate_name=gate_name,
                gate_output=gate_output,
            )
        if dry_run:
            return CommitResult(
                ok=True,
                blocker_class=None,
                message="local scoped commit checks passed (dry-run)",
                agent=resolved_agent,
                branch=branch,
                claim_scopes=tuple(claim.scopes),
                selected_paths=tuple(selected_paths),
                dry_run=True,
            )
        commit_sha = _create_commit_object(
            repo_root,
            agent=resolved_agent,
            index_path=index_path,
            parent_head=head_before,
            message=full_message,
        )
        if _current_head(repo_root) != head_before:
            return CommitResult(
                ok=False,
                blocker_class="branch_race",
                message="HEAD changed during scoped commit preparation; branch was not advanced",
                agent=resolved_agent,
                branch=branch,
                claim_scopes=tuple(claim.scopes),
                selected_paths=tuple(selected_paths),
                dry_run=False,
            )
        _update_branch_ref(repo_root, branch=branch, commit_sha=commit_sha, expected_head=head_before)
        _sync_live_index(repo_root, selected_paths)
        return CommitResult(
            ok=True,
            blocker_class=None,
            message="scoped agent commit created",
            agent=resolved_agent,
            branch=branch,
            claim_scopes=tuple(claim.scopes),
            selected_paths=tuple(selected_paths),
            commit_sha=commit_sha,
            dry_run=False,
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        return CommitResult(
            ok=False,
            blocker_class="broken_repo_tool",
            message=str(exc),
            agent=resolved_agent,
            branch=branch,
            claim_scopes=tuple(claim.scopes),
            selected_paths=tuple(selected_paths),
            dry_run=bool(dry_run),
        )
    finally:
        if holder is not None:
            holder.cleanup()


def _render_result(result: CommitResult) -> str:
    lines = ["Scoped agent commit: PASS" if result.ok else "Scoped agent commit: FAIL"]
    if result.ok and result.dry_run:
        lines[0] += " (dry-run)"
    if result.agent:
        lines.append(f"- agent: {result.agent}")
    if result.branch:
        lines.append(f"- branch: {result.branch}")
    if result.claim_scopes:
        lines.append(f"- claim scopes: {', '.join(result.claim_scopes)}")
    lines.append(f"- message: {result.message}")
    if result.blocker_class:
        lines.append(f"- blocker_class: {result.blocker_class}")
    if result.commit_sha:
        lines.append(f"- commit: {result.commit_sha}")
    if result.selected_paths:
        lines.append("- selected paths:")
        for path in result.selected_paths:
            lines.append(f"  - {path}")
    if result.gate_name:
        lines.append(f"- failed gate: {result.gate_name}")
    if result.gate_output:
        lines.append("- gate output:")
        for row in result.gate_output.splitlines()[:20]:
            lines.append(f"  {row}")
    return "\n".join(lines)


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a scoped local commit for the current agent claim.")
    parser.add_argument("--message", required=True, help="Commit message subject/body.")
    parser.add_argument("--agent", default="", help="Agent id override.")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Optional in-claim path(s) to narrow the commit (repeatable or comma-separated).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Evaluate scoped commit selection and gates without creating a commit.")
    args = parser.parse_args(argv)

    include_paths: list[str] = []
    for raw in args.include:
        include_paths.extend(token.strip() for token in str(raw or "").split(",") if token.strip())

    result = commit_scoped_changes(
        message=args.message,
        agent=str(args.agent or "").strip() or None,
        include_paths=include_paths,
        dry_run=bool(args.dry_run),
    )
    print(_render_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
