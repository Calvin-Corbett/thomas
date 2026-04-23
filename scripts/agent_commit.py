#!/usr/bin/env python3
"""Create scoped agent commits without bundling unrelated repo dirt."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts import agent_identity, breakglass_auth
    from scripts import check_workboard_claims as claims_gate
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    import agent_identity  # type: ignore
    import breakglass_auth  # type: ignore
    import check_workboard_claims as claims_gate  # type: ignore


ROOT = _REPO_ROOT
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
RELEASE_METADATA_FILES: tuple[str, ...] = ("CHANGELOG.md", "pyproject.toml", "thomas/__init__.py")
RELEASE_SCOPE_IGNORE = ",".join(RELEASE_METADATA_FILES)
DEFAULT_COMMIT_CLASS = "private-checkpoint"
COMMIT_CLASS_CHOICES: tuple[str, ...] = (
    "scratch-save",
    "private-checkpoint",
    "private-stable",
    "publish-candidate",
    "public-release",
)
RELEASE_METADATA_COMMIT_CLASSES = frozenset({"publish-candidate", "public-release"})
RELEASE_GATED_COMMIT_CLASSES = frozenset({"publish-candidate", "public-release"})
PATH_SCOPED_GATES: dict[str, tuple[str, ...]] = {
    "site_visual_proof": (
        "apps/site/src/app/",
        "apps/site/src/components/",
        "apps/site/verification/",
    ),
}
STRUCTURED_GATE_COMMANDS: dict[str, tuple[str, ...]] = {
    "bulk_commit_guard": (sys.executable, "scripts/check_bulk_commit_guard.py", "--json"),
    "commit_growth_guard": (sys.executable, "scripts/check_commit_growth_guard.py", "--json"),
    "monolith_guard": (sys.executable, "scripts/check_monolith_guard.py", "--staged-only", "--json"),
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
    ("bulk_commit_guard", (sys.executable, "scripts/check_bulk_commit_guard.py", "--max-files", "50")),
    ("commit_growth_guard", (sys.executable, "scripts/check_commit_growth_guard.py", "--max-growth", "300")),
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
FALLBACK_SCOPE_ENV = "THOMAS_WORKBOARD_SCOPE_FALLBACK"
FALLBACK_REASON_ENV = "THOMAS_WORKBOARD_SCOPE_FALLBACK_REASON"
FALLBACK_RECEIPT_ENV = "THOMAS_WORKBOARD_SCOPE_FALLBACK_RECEIPT"
COMMIT_CLASS_ENV = "THOMAS_COMMIT_CLASS"
CLAIM_SOURCE = "workboard_claim"
FALLBACK_SOURCE = "explicit_fallback"


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
    scope_source: str = CLAIM_SOURCE
    next_step: str | None = None
    suggested_command: str | None = None
    commit_class: str = DEFAULT_COMMIT_CLASS


@dataclass(frozen=True)
class ScopeSelection:
    scopes: tuple[str, ...]
    source: str
    reason: str = ""
    approved_by: str = ""
    approval_method: str = ""


def _normalize_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    while "//" in path:
        path = path.replace("//", "/")
    return path.strip("/")


def _normalize_commit_class(value: str) -> str:
    commit_class = str(value or "").strip().lower()
    if not commit_class:
        return DEFAULT_COMMIT_CLASS
    if commit_class not in COMMIT_CLASS_CHOICES:
        allowed = ", ".join(COMMIT_CLASS_CHOICES)
        raise ValueError(f"unsupported commit class `{commit_class}`; expected one of: {allowed}")
    return commit_class


def _commit_class_requires_release_metadata(commit_class: str) -> bool:
    return commit_class in RELEASE_METADATA_COMMIT_CLASSES


def _gate_requires_release_class(gate_name: str) -> bool:
    return gate_name in {"release_update", "changelog"}


def _scope_matches_path(scope: str, rel_path: str) -> bool:
    scope_norm = _normalize_path(scope).lower()
    path_norm = _normalize_path(rel_path).lower()
    if not scope_norm or not path_norm:
        return False
    if scope_norm in {".", "*", "**"}:
        return True
    if path_norm == scope_norm or path_norm.startswith(scope_norm + "/"):
        return True
    if any(ch in scope_norm for ch in "*?["):
        import fnmatch

        if fnmatch.fnmatchcase(path_norm, scope_norm):
            return True
        if scope_norm.endswith("/**"):
            base = scope_norm[:-3].rstrip("/")
            return bool(base) and (path_norm == base or path_norm.startswith(base + "/"))
        return False
    return False


def _scope_overlap(left: str, right: str) -> bool:
    left_norm = _normalize_path(left)
    right_norm = _normalize_path(right)
    if not left_norm or not right_norm:
        return False
    return _scope_matches_path(left_norm, right_norm) or _scope_matches_path(right_norm, left_norm)


def _run_git(
    repo_root: Path,
    args: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
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
    proc = _run_git(repo_root, ["status", "--porcelain=v1", "-z", "-uall"])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git status --porcelain=v1 -z -uall failed")
    changed: list[str] = []
    entries = str(proc.stdout or "").split("\0")
    index = 0
    while index < len(entries):
        entry = str(entries[index] or "")
        if not entry:
            index += 1
            continue
        status = entry[:2]
        token = entry[3:] if len(entry) > 3 else entry
        if ("R" in status or "C" in status) and index + 1 < len(entries) and str(entries[index + 1] or ""):
            token = str(entries[index + 1] or "")
            index += 1
        normalized = _normalize_path(token)
        if normalized and normalized not in changed:
            changed.append(normalized)
        index += 1
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


def _resolve_fallback_scope(
    agent: str,
    workboard_path: Path,
    include_paths: Sequence[str],
    fallback_reason: str,
    fallback_receipt: str,
) -> ScopeSelection:
    include_norm = sorted(dict.fromkeys(_normalize_path(item) for item in include_paths if _normalize_path(item)))
    if not include_norm:
        raise ValueError(
            "explicit scope fallback requires --include with one or more changed file paths inside the intended commit scope"
        )

    reason = str(fallback_reason or "").strip()
    if not reason:
        raise ValueError("explicit scope fallback requires --fallback-reason describing the approved exception")

    violations, claims, _tasks, _grab, issues = claims_gate.evaluate_board(
        workboard_path,
        require_identity_metadata=True,
    )
    if violations:
        raise RuntimeError("; ".join(str(item) for item in violations))

    overlapping_agents = sorted(
        {
            str(claim.agent).strip()
            for claim in claims
            if str(claim.agent).strip().lower() != str(agent).strip().lower()
            and any(_scope_overlap(scope, include_path) for scope in claim.scopes for include_path in include_norm)
        },
        key=str.lower,
    )
    if overlapping_agents:
        raise ValueError(
            "explicit scope fallback overlaps active workboard claim(s) owned by: " + ", ".join(overlapping_agents)
        )

    unresolved_owned = sorted(
        {
            str(issue.issue_id).strip()
            for issue in issues
            if str(issue.owner).strip().lower() == str(agent).strip().lower()
            and str(issue.state).strip().lower() != "resolved"
            and str(issue.issue_id).strip()
        }
    )
    if unresolved_owned:
        raise ValueError(
            "explicit scope fallback is blocked while the agent owns unresolved workboard issue(s): "
            + ", ".join(unresolved_owned)
        )

    receipt_value = str(fallback_receipt or "").strip()
    if not receipt_value:
        raise ValueError(
            "explicit scope fallback requires --fallback-receipt from a human-approved scope fallback authorization"
        )
    receipt = breakglass_auth.consume_scope_fallback_receipt(
        receipt_value,
        agent=agent,
        scopes=tuple(include_norm),
        reason=reason,
    )
    if receipt is None:
        raise ValueError(
            "explicit scope fallback requires a valid unused fallback approval receipt matching the agent, scope, and reason"
        )

    return ScopeSelection(
        scopes=tuple(include_norm),
        source=FALLBACK_SOURCE,
        reason=reason,
        approved_by=receipt.actor,
        approval_method=str(receipt.method or "").strip(),
    )


def _selected_paths(
    repo_root: Path,
    scope_selection: ScopeSelection,
    include_paths: Sequence[str],
    *,
    commit_class: str,
) -> list[str]:
    changed = _parse_status_paths(repo_root)
    changed_set = set(changed)
    include_norm = [_normalize_path(item) for item in include_paths if _normalize_path(item)]
    if include_norm:
        outside = [
            path
            for path in include_norm
            if not any(_scope_matches_path(scope, path) for scope in scope_selection.scopes)
        ]
        if outside:
            raise ValueError("requested include path(s) are outside the selected commit scope: " + ", ".join(outside))
        in_scope: list[str] = []
        unmatched: list[str] = []
        for requested in include_norm:
            if requested in changed_set:
                in_scope.append(requested)
                continue
            matched = [path for path in changed if _scope_matches_path(requested, path)]
            if matched:
                in_scope.extend(matched)
                continue
            unmatched.append(requested)
        if unmatched:
            raise ValueError("requested include path(s) have no current changes: " + ", ".join(unmatched))
    else:
        in_scope = [
            path for path in changed if any(_scope_matches_path(scope, path) for scope in scope_selection.scopes)
        ]

    selected = sorted(dict.fromkeys(in_scope))
    if selected and _commit_class_requires_release_metadata(commit_class):
        for path in RELEASE_METADATA_FILES:
            if path in changed_set and path not in selected:
                selected.append(path)
    return selected


def _build_commit_message(message: str, *, agent: str, scope_selection: ScopeSelection, commit_class: str) -> str:
    base = str(message or "").strip()
    if not base:
        raise ValueError("commit message is required")
    trailers = [
        f"Thomas-Agent: {agent}",
        f"Thomas-Commit-Class: {commit_class}",
        f"Thomas-Scope: {','.join(scope_selection.scopes)}",
        f"Thomas-Commit-Mode: {'scoped-fallback' if scope_selection.source == FALLBACK_SOURCE else 'scoped-local'}",
    ]
    if scope_selection.source == CLAIM_SOURCE:
        trailers.insert(1, f"Thomas-Claim: {','.join(scope_selection.scopes)}")
    if scope_selection.reason:
        trailers.append(f"Thomas-Fallback-Reason: {scope_selection.reason}")
    if scope_selection.approved_by:
        trailers.append(f"Thomas-Fallback-Approved-By: {scope_selection.approved_by}")
    if scope_selection.approval_method:
        trailers.append(f"Thomas-Fallback-Approval-Method: {scope_selection.approval_method}")
    return base.rstrip() + "\n\n" + "\n".join(trailers) + "\n"


def _temp_index_env(
    agent: str,
    index_path: Path,
    *,
    scope_selection: ScopeSelection | None = None,
    commit_class: str = DEFAULT_COMMIT_CLASS,
) -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(index_path)
    env["AGENT_ID"] = agent
    env["THOMAS_AGENT_ID"] = agent
    env[COMMIT_CLASS_ENV] = _normalize_commit_class(commit_class)
    if scope_selection and scope_selection.source == FALLBACK_SOURCE:
        env[FALLBACK_SCOPE_ENV] = ",".join(scope_selection.scopes)
        env[FALLBACK_REASON_ENV] = scope_selection.reason
        env[FALLBACK_RECEIPT_ENV] = "consumed"
    return env


def _gate_applies(gate_name: str, selected_paths: Sequence[str], *, commit_class: str) -> bool:
    if _gate_requires_release_class(gate_name) and commit_class not in RELEASE_GATED_COMMIT_CLASSES:
        return False
    prefixes = PATH_SCOPED_GATES.get(gate_name)
    if not prefixes:
        return True
    return any(_normalize_path(path).startswith(prefix) for path in selected_paths for prefix in prefixes)


def _resolved_gate_command(
    gate_name: str,
    command: Sequence[str],
    *,
    selected_paths: Sequence[str],
) -> list[str]:
    resolved = list(command)
    if gate_name == "release_update":
        for path in selected_paths:
            normalized = _normalize_path(path)
            if normalized:
                resolved.extend(["--changed-file", normalized])
    return resolved


def _prepare_temp_index(
    repo_root: Path,
    *,
    agent: str,
    selected_paths: Sequence[str],
    scope_selection: ScopeSelection,
    commit_class: str,
) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    holder = tempfile.TemporaryDirectory(prefix="thomas-agent-commit-")
    index_path = Path(holder.name) / "index"
    env = _temp_index_env(agent, index_path, scope_selection=scope_selection, commit_class=commit_class)
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
    scope_selection: ScopeSelection,
    local_gate_commands: Sequence[tuple[str, Sequence[str]]],
    commit_class: str,
) -> tuple[bool, str | None, str]:
    env = _temp_index_env(agent, index_path, scope_selection=scope_selection, commit_class=commit_class)
    for gate_name, command in local_gate_commands:
        if not _gate_applies(gate_name, selected_paths, commit_class=commit_class):
            continue
        resolved_command = _resolved_gate_command(
            gate_name,
            command,
            selected_paths=selected_paths,
        )
        proc = subprocess.run(
            resolved_command,
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
    proc = _run_git(repo_root, ["reset", "-q", "HEAD", "--", *selected_paths])
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr.strip() or proc.stdout.strip() or "git reset failed while realigning the live index to HEAD"
        )


def _fallback_suggested_command(include_paths: Sequence[str]) -> str:
    parts = [
        'python scripts/agent_commit.py --agent <agent-id> --commit-class "private-checkpoint" --message "<message>"'
    ]
    for path in [_normalize_path(item) for item in include_paths if _normalize_path(item)]:
        parts.append(f'--include "{path}"')
    parts.extend(
        [
            "--allow-scope-fallback",
            '--fallback-reason "<approved reason>"',
            '--fallback-receipt "<approval receipt>"',
        ]
    )
    return " ".join(parts)


def _result_payload(result: CommitResult) -> dict[str, object]:
    return asdict(result)


def _load_structured_gate_output(
    repo_root: Path,
    *,
    gate_name: str,
    agent: str,
    index_path: Path,
    scope_selection: ScopeSelection,
    selected_paths: Sequence[str],
    commit_class: str,
) -> dict[str, object] | None:
    command = STRUCTURED_GATE_COMMANDS.get(gate_name)
    if not command:
        return None
    env = _temp_index_env(agent, index_path, scope_selection=scope_selection, commit_class=commit_class)
    resolved_command = _resolved_gate_command(gate_name, command, selected_paths=selected_paths)
    proc = subprocess.run(
        resolved_command,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = str(proc.stdout or "").strip()
    if not payload:
        return None
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _gate_failure_guidance(
    gate_name: str | None,
    *,
    structured_output: dict[str, object] | None,
) -> tuple[str, str, str | None]:
    if gate_name == "bulk_commit_guard":
        suggested_command = 'python scripts/agent_commit.py --agent <agent-id> --message "<message>" --include "<scope>"'
        if isinstance(structured_output, dict):
            batches = structured_output.get("suggested_batches")
            if isinstance(batches, list) and batches:
                first = batches[0]
                if isinstance(first, dict):
                    scope = str(first.get("scope") or "").strip()
                    if scope:
                        suggested_command = (
                            f'python scripts/agent_commit.py --agent <agent-id> --message "<message>" --include "{scope}"'
                        )
        return (
            "local_gate_failed",
            "Split the commit into one focused scope first, then rerun the next batch.",
            suggested_command,
        )
    if gate_name in {"commit_growth_guard", "monolith_guard"}:
        next_step = "Refactor the oversized file(s) into sibling modules, restage the smaller entry files, then retry."
        if isinstance(structured_output, dict):
            violations = structured_output.get("violations")
            if isinstance(violations, list) and violations:
                first = violations[0]
                if isinstance(first, dict):
                    split_paths = first.get("suggested_split_paths")
                    if isinstance(split_paths, list) and split_paths:
                        targets = ", ".join(str(item) for item in split_paths[:2])
                        next_step = f"Refactor the oversized file(s) into sibling modules such as {targets}, then retry."
        return ("needs_refactor", next_step, None)
    return (
        "local_gate_failed",
        "Fix the reported local gate failure, or narrow the selected commit scope and retry.",
        None,
    )


def commit_scoped_changes(
    *,
    message: str,
    agent: str | None = None,
    include_paths: Sequence[str] = (),
    dry_run: bool = False,
    allow_scope_fallback: bool = False,
    prefer_scope_fallback: bool = False,
    fallback_reason: str = "",
    fallback_receipt: str = "",
    commit_class: str = DEFAULT_COMMIT_CLASS,
    repo_root: Path = ROOT,
    workboard_path: Path = DEFAULT_WORKBOARD,
    local_gate_commands: Sequence[tuple[str, Sequence[str]]] = LOCAL_GATE_COMMANDS,
) -> CommitResult:
    try:
        resolved_commit_class = _normalize_commit_class(commit_class)
    except ValueError as exc:
        return CommitResult(
            ok=False,
            blocker_class="broken_repo_tool",
            message=str(exc),
            agent=str(agent or "").strip(),
            branch=None,
            claim_scopes=(),
            selected_paths=(),
            dry_run=bool(dry_run),
            commit_class=str(commit_class or "").strip() or DEFAULT_COMMIT_CLASS,
        )
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
            next_step="Re-run with --agent <agent-id> or export THOMAS_AGENT_ID before committing.",
            suggested_command=(
                'python scripts/agent_commit.py --agent <agent-id> '
                '--commit-class "private-checkpoint" --message "<message>"'
            ),
            commit_class=resolved_commit_class,
        )

    scope_selection: ScopeSelection | None = None
    if allow_scope_fallback and prefer_scope_fallback:
        try:
            scope_selection = _resolve_fallback_scope(
                resolved_agent,
                workboard_path,
                include_paths,
                fallback_reason,
                fallback_receipt,
            )
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
                scope_source=FALLBACK_SOURCE,
                next_step=(
                    "Provide explicit changed file paths with --include, a short --fallback-reason, and a human-approved --fallback-receipt, or narrow the requested maintenance scope."
                ),
                suggested_command=_fallback_suggested_command(include_paths),
                commit_class=resolved_commit_class,
            )
        except (OSError, RuntimeError) as exc:
            return CommitResult(
                ok=False,
                blocker_class="broken_repo_tool",
                message=f"could not resolve fallback scope: {exc}",
                agent=resolved_agent,
                branch=None,
                claim_scopes=(),
                selected_paths=(),
                dry_run=bool(dry_run),
                scope_source=FALLBACK_SOURCE,
                commit_class=resolved_commit_class,
            )
    try:
        if scope_selection is None:
            claim = _resolve_active_claim(resolved_agent, workboard_path)
            scope_selection = ScopeSelection(scopes=tuple(claim.scopes), source=CLAIM_SOURCE)
    except ValueError as exc:
        error_message = str(exc)
        if allow_scope_fallback and "has no active claim" in error_message:
            try:
                scope_selection = _resolve_fallback_scope(
                    resolved_agent,
                    workboard_path,
                    include_paths,
                    fallback_reason,
                    fallback_receipt,
                )
            except ValueError as fallback_exc:
                return CommitResult(
                    ok=False,
                    blocker_class="claim_scope_mismatch",
                    message=str(fallback_exc),
                    agent=resolved_agent,
                    branch=None,
                    claim_scopes=(),
                    selected_paths=(),
                    dry_run=bool(dry_run),
                    scope_source=FALLBACK_SOURCE,
                    next_step=(
                        "Provide explicit changed file paths with --include, a short --fallback-reason, and a human-approved --fallback-receipt, or add a normal workboard claim first."
                    ),
                    suggested_command=_fallback_suggested_command(include_paths),
                    commit_class=resolved_commit_class,
                )
            except (OSError, RuntimeError) as fallback_exc:
                return CommitResult(
                    ok=False,
                    blocker_class="broken_repo_tool",
                    message=f"could not resolve fallback scope: {fallback_exc}",
                    agent=resolved_agent,
                    branch=None,
                    claim_scopes=(),
                    selected_paths=(),
                    dry_run=bool(dry_run),
                    scope_source=FALLBACK_SOURCE,
                    commit_class=resolved_commit_class,
                )
        else:
            next_step = (
                "Create a workboard claim first, or re-run with explicit --include paths plus --allow-scope-fallback, --fallback-reason, and --fallback-receipt."
                if "has no active claim" in error_message
                else "Fix the workboard claim mismatch before committing."
            )
            return CommitResult(
                ok=False,
                blocker_class="claim_scope_mismatch",
                message=error_message,
                agent=resolved_agent,
                branch=None,
                claim_scopes=(),
                selected_paths=(),
                dry_run=bool(dry_run),
                next_step=next_step,
                suggested_command=(
                    _fallback_suggested_command(include_paths) if "has no active claim" in error_message else None
                ),
                commit_class=resolved_commit_class,
            )
    except (OSError, RuntimeError) as exc:
        return CommitResult(
            ok=False,
            blocker_class="broken_repo_tool",
            message=f"could not resolve active claim: {exc}",
            agent=resolved_agent,
            branch=None,
            claim_scopes=(),
            selected_paths=(),
            dry_run=bool(dry_run),
            commit_class=resolved_commit_class,
        )

    assert scope_selection is not None
    try:
        selected_paths = _selected_paths(
            repo_root,
            scope_selection,
            include_paths,
            commit_class=resolved_commit_class,
        )
    except ValueError as exc:
        return CommitResult(
            ok=False,
            blocker_class="claim_scope_mismatch",
            message=str(exc),
            agent=resolved_agent,
            branch=None,
            claim_scopes=tuple(scope_selection.scopes),
            selected_paths=(),
            dry_run=bool(dry_run),
            scope_source=scope_selection.source,
            commit_class=resolved_commit_class,
        )
    except (OSError, RuntimeError) as exc:
        return CommitResult(
            ok=False,
            blocker_class="broken_repo_tool",
            message=f"could not compute changed paths: {exc}",
            agent=resolved_agent,
            branch=None,
            claim_scopes=tuple(scope_selection.scopes),
            selected_paths=(),
            dry_run=bool(dry_run),
            scope_source=scope_selection.source,
            commit_class=resolved_commit_class,
        )

    claimed_changed = [path for path in selected_paths if path not in RELEASE_METADATA_FILES]
    if not claimed_changed:
        scope_label = (
            "selected explicit fallback scope" if scope_selection.source == FALLBACK_SOURCE else "active claim scope"
        )
        return CommitResult(
            ok=False,
            blocker_class="no_claimed_changes",
            message=f"no changed files inside the {scope_label} were found for this commit",
            agent=resolved_agent,
            branch=None,
            claim_scopes=tuple(scope_selection.scopes),
            selected_paths=tuple(selected_paths),
            dry_run=bool(dry_run),
            scope_source=scope_selection.source,
            next_step="Update the selected files or narrow --include to paths that currently have changes.",
            commit_class=resolved_commit_class,
        )

    branch: str | None = None
    holder: tempfile.TemporaryDirectory[str] | None = None
    try:
        branch = _current_branch(repo_root)
        head_before = _current_head(repo_root)
        full_message = _build_commit_message(
            message,
            agent=resolved_agent,
            scope_selection=scope_selection,
            commit_class=resolved_commit_class,
        )
        index_path, holder = _prepare_temp_index(
            repo_root,
            agent=resolved_agent,
            selected_paths=selected_paths,
            scope_selection=scope_selection,
            commit_class=resolved_commit_class,
        )
        gates_ok, gate_name, gate_output = _run_local_gates(
            repo_root,
            agent=resolved_agent,
            index_path=index_path,
            selected_paths=selected_paths,
            scope_selection=scope_selection,
            local_gate_commands=local_gate_commands,
            commit_class=resolved_commit_class,
        )
        if not gates_ok:
            structured_output = _load_structured_gate_output(
                repo_root,
                gate_name=gate_name or "",
                agent=resolved_agent,
                index_path=index_path,
                scope_selection=scope_selection,
                selected_paths=selected_paths,
                commit_class=resolved_commit_class,
            )
            blocker_class, next_step, suggested_command = _gate_failure_guidance(
                gate_name,
                structured_output=structured_output,
            )
            return CommitResult(
                ok=False,
                blocker_class=blocker_class,
                message=f"local gate failed: {gate_name}",
                agent=resolved_agent,
                branch=branch,
                claim_scopes=tuple(scope_selection.scopes),
                selected_paths=tuple(selected_paths),
                dry_run=bool(dry_run),
                gate_name=gate_name,
                gate_output=gate_output,
                scope_source=scope_selection.source,
                next_step=next_step,
                suggested_command=suggested_command,
                commit_class=resolved_commit_class,
            )
        if dry_run:
            return CommitResult(
                ok=True,
                blocker_class=None,
                message="local scoped commit checks passed (dry-run)",
                agent=resolved_agent,
                branch=branch,
                claim_scopes=tuple(scope_selection.scopes),
                selected_paths=tuple(selected_paths),
                dry_run=True,
                scope_source=scope_selection.source,
                commit_class=resolved_commit_class,
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
                claim_scopes=tuple(scope_selection.scopes),
                selected_paths=tuple(selected_paths),
                dry_run=False,
                scope_source=scope_selection.source,
                next_step="Re-run the scoped commit after refreshing the branch state.",
                commit_class=resolved_commit_class,
            )
        _update_branch_ref(repo_root, branch=branch, commit_sha=commit_sha, expected_head=head_before)
        _sync_live_index(repo_root, selected_paths)
        return CommitResult(
            ok=True,
            blocker_class=None,
            message="scoped agent commit created",
            agent=resolved_agent,
            branch=branch,
            claim_scopes=tuple(scope_selection.scopes),
            selected_paths=tuple(selected_paths),
            commit_sha=commit_sha,
            dry_run=False,
            scope_source=scope_selection.source,
            commit_class=resolved_commit_class,
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        return CommitResult(
            ok=False,
            blocker_class="broken_repo_tool",
            message=str(exc),
            agent=resolved_agent,
            branch=branch,
            claim_scopes=tuple(scope_selection.scopes),
            selected_paths=tuple(selected_paths),
            dry_run=bool(dry_run),
            scope_source=scope_selection.source,
            commit_class=resolved_commit_class,
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
    lines.append(f"- commit class: {result.commit_class}")
    if result.claim_scopes:
        lines.append(f"- claim scopes: {', '.join(result.claim_scopes)}")
    lines.append(f"- scope source: {result.scope_source}")
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
    if result.next_step:
        lines.append(f"- next step: {result.next_step}")
    if result.suggested_command:
        lines.append(f"- suggested command: {result.suggested_command}")
    return "\n".join(lines)


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a scoped local commit for the current agent claim.")
    parser.add_argument("--message", required=True, help="Commit message subject/body.")
    parser.add_argument("--agent", default="", help="Agent id override.")
    parser.add_argument(
        "--commit-class",
        default=DEFAULT_COMMIT_CLASS,
        choices=COMMIT_CLASS_CHOICES,
        help="Commit policy lane. Private checkpoints skip release metadata gates by default.",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Optional in-claim path(s) to narrow the commit (repeatable or comma-separated).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate scoped commit selection and gates without creating a commit.",
    )
    parser.add_argument(
        "--allow-scope-fallback",
        action="store_true",
        help="Allow an explicit, audited fallback scope when the agent has no active workboard claim.",
    )
    parser.add_argument(
        "--prefer-scope-fallback",
        action="store_true",
        help="Use the explicit fallback scope even when an active workboard claim exists.",
    )
    parser.add_argument(
        "--fallback-reason",
        default="",
        help="Short approval/audit reason required with --allow-scope-fallback.",
    )
    parser.add_argument(
        "--fallback-receipt",
        default=os.getenv(FALLBACK_RECEIPT_ENV, ""),
        help="Single-use approval receipt required for explicit fallback scope commits.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    include_paths: list[str] = []
    for raw in args.include:
        include_paths.extend(token.strip() for token in str(raw or "").split(",") if token.strip())

    result = commit_scoped_changes(
        message=args.message,
        agent=str(args.agent or "").strip() or None,
        commit_class=str(args.commit_class or "").strip() or DEFAULT_COMMIT_CLASS,
        include_paths=include_paths,
        dry_run=bool(args.dry_run),
        allow_scope_fallback=bool(args.allow_scope_fallback),
        prefer_scope_fallback=bool(args.prefer_scope_fallback),
        fallback_reason=str(args.fallback_reason or ""),
        fallback_receipt=str(args.fallback_receipt or ""),
    )
    if args.json:
        print(json.dumps(_result_payload(result), sort_keys=True))
    else:
        print(_render_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
