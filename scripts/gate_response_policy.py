"""Shared policy for how agents should react to local gate failures.

This does not weaken gates. It classifies them so the agent workflow can
distinguish:
- hard-stop integrity / ownership / security failures
- structural / quality failures that should trigger remediation and retry
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GateResponsePolicy:
    gate: str
    response_class: str
    continue_after_fix: bool
    stop_immediately: bool
    summary: str
    next_step: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_HARD_STOP_POLICIES: dict[str, GateResponsePolicy] = {
    "protected_files": GateResponsePolicy(
        gate="protected_files",
        response_class="hard_stop",
        continue_after_fix=False,
        stop_immediately=True,
        summary="Protected policy/enforcement files are not a normal remediation lane.",
        next_step="Stop and use the explicit protected-file or human-approved governance path.",
    ),
    "precommit_skip_policy": GateResponsePolicy(
        gate="precommit_skip_policy",
        response_class="hard_stop",
        continue_after_fix=False,
        stop_immediately=True,
        summary="Skip-policy violations are integrity events, not normal workflow noise.",
        next_step="Stop and use the audited breakglass path only if the human explicitly wants that override.",
    ),
    "worktree_rules": GateResponsePolicy(
        gate="worktree_rules",
        response_class="hard_stop",
        continue_after_fix=False,
        stop_immediately=True,
        summary="Worktree-rules failures mean the agent is in the wrong lane for the current repo state.",
        next_step="Stop and move into the required clean-worktree, cleanup, or benchmark lane before continuing.",
    ),
    "worktree_branch": GateResponsePolicy(
        gate="worktree_branch",
        response_class="hard_stop",
        continue_after_fix=False,
        stop_immediately=True,
        summary="Branch-guard failures are coordination/integrity failures.",
        next_step="Stop and switch to the allowed branch/worktree lane before continuing.",
    ),
    "protected_deletion": GateResponsePolicy(
        gate="protected_deletion",
        response_class="hard_stop",
        continue_after_fix=False,
        stop_immediately=True,
        summary="Protected-deletion failures should not be auto-pushed through.",
        next_step="Stop and restore the protected path or use an explicit human-approved deletion lane.",
    ),
    "repo_identity": GateResponsePolicy(
        gate="repo_identity",
        response_class="hard_stop",
        continue_after_fix=False,
        stop_immediately=True,
        summary="Repo-identity failures mean the guard chain cannot trust the repo metadata/state.",
        next_step="Stop and repair repo identity/config before continuing.",
    ),
}

_AUTO_REMEDIATE_POLICIES: dict[str, GateResponsePolicy] = {
    "active_folder_guard": GateResponsePolicy(
        gate="active_folder_guard",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Folder coordination failures should trigger claim/scope repair, not a dead stop.",
        next_step="Claim or sync the active folder/workboard scope, then retry the same operation.",
    ),
    "workboard_claims": GateResponsePolicy(
        gate="workboard_claims",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Malformed or missing workboard claims are coordination issues that should be repaired and retried.",
        next_step="Repair or bootstrap the workboard claim metadata, then retry the same operation.",
    ),
    "workboard_task_problems": GateResponsePolicy(
        gate="workboard_task_problems",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Task/problem ledger failures are workflow debt, not a reason to abandon the task.",
        next_step="Update the task/problem ledger so the work is tracked correctly, then retry.",
    ),
    "workboard_changed_files": GateResponsePolicy(
        gate="workboard_changed_files",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Changed-file scope mismatches should trigger rescoping or a fresh claim.",
        next_step="Rescope the claim or narrow the changed files so they map to one active claim, then retry.",
    ),
    "workboard_agent_claim": GateResponsePolicy(
        gate="workboard_agent_claim",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Agent-claim mismatches should trigger claim repair, not a generic stop.",
        next_step="Create, release, or rescope the agent claim so ownership is unambiguous, then retry.",
    ),
    "monolith_guard": GateResponsePolicy(
        gate="monolith_guard",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Monolith guard failures should push the agent into a split/refactor/baseline lane.",
        next_step="Reduce growth by moving logic out of the hotspot or use the explicit baseline-approval lane if the growth is intentional, then retry.",
    ),
    "monolith_filename_guard": GateResponsePolicy(
        gate="monolith_filename_guard",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Monolith filename guard failures should be fixed by renaming or restructuring the file.",
        next_step="Rename the file or move the change into an allowed module shape, then retry.",
    ),
    "release_update": GateResponsePolicy(
        gate="release_update",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Release-update drift should be repaired and retried.",
        next_step="Update the release metadata/docs expected by the gate, then retry.",
    ),
    "site_visual_proof": GateResponsePolicy(
        gate="site_visual_proof",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="UI proof failures should trigger proof refresh/check steps, not an abandoned task.",
        next_step="Run the required visual-proof refresh/check commands, fix the mismatch, then retry.",
    ),
    "changelog": GateResponsePolicy(
        gate="changelog",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Changelog failures are documentation follow-through, not hard-stop integrity issues.",
        next_step="Stage the changelog entry expected by the change scope, then retry.",
    ),
    "boot_smoke": GateResponsePolicy(
        gate="boot_smoke",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Boot-smoke failures should send the agent into startup/import repair and retry.",
        next_step="Fix the import/startup breakage the smoke gate found, then retry.",
    ),
    "type_safety": GateResponsePolicy(
        gate="type_safety",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Type-safety failures should be repaired and retried.",
        next_step="Fix the typing issue(s) reported by the gate, then retry.",
    ),
    "circular_imports": GateResponsePolicy(
        gate="circular_imports",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Circular-import failures should trigger module-boundary repair and retry.",
        next_step="Repair the import layering/cycle and retry.",
    ),
    "exception_handler": GateResponsePolicy(
        gate="exception_handler",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Broad exception-handler failures should be fixed in code, not bypassed.",
        next_step="Make the exception handling specific or satisfy the guard requirements, then retry.",
    ),
    "feature_registry": GateResponsePolicy(
        gate="feature_registry",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Feature registry mismatches should be synchronized and retried.",
        next_step="Update the feature registry/baseline expected by the change, then retry.",
    ),
    "core_overhead": GateResponsePolicy(
        gate="core_overhead",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Core-overhead failures should push the change into a smaller/cleaner shape.",
        next_step="Reduce the added core overhead or move the change to the approved extension point, then retry.",
    ),
    "agent_safety": GateResponsePolicy(
        gate="agent_safety",
        response_class="auto_remediate",
        continue_after_fix=True,
        stop_immediately=False,
        summary="Agent-safety validation failures should be fixed in the patch and retried.",
        next_step="Repair the unsafe pattern(s) reported by validation, then retry.",
    ),
}

_DEFAULT_POLICY = GateResponsePolicy(
    gate="unknown",
    response_class="manual_review",
    continue_after_fix=False,
    stop_immediately=False,
    summary="Unclassified gate failure requires human/agent review of the specific output.",
    next_step="Inspect the gate output, decide whether it is structural or integrity-related, then remediate accordingly.",
)


def describe_gate(gate: str) -> GateResponsePolicy:
    """Return the response policy for a local gate name."""
    name = str(gate or "").strip()
    if name in _HARD_STOP_POLICIES:
        return _HARD_STOP_POLICIES[name]
    if name in _AUTO_REMEDIATE_POLICIES:
        return _AUTO_REMEDIATE_POLICIES[name]
    if name.endswith("_smoke"):
        return GateResponsePolicy(
            gate=name,
            response_class="auto_remediate",
            continue_after_fix=True,
            stop_immediately=False,
            summary="Smoke-check failures should be investigated, repaired, and retried.",
            next_step="Fix the broken command/path the smoke check reported, then retry.",
        )
    return GateResponsePolicy(
        gate=name or "unknown",
        response_class=_DEFAULT_POLICY.response_class,
        continue_after_fix=_DEFAULT_POLICY.continue_after_fix,
        stop_immediately=_DEFAULT_POLICY.stop_immediately,
        summary=_DEFAULT_POLICY.summary,
        next_step=_DEFAULT_POLICY.next_step,
    )


def startup_gate_guidance() -> dict[str, Any]:
    """Return a startup-facing summary of hard-stop vs auto-remediate gates."""
    auto_remediate = sorted(_AUTO_REMEDIATE_POLICIES)
    hard_stop = sorted(_HARD_STOP_POLICIES)
    return {
        "summary": (
            "Structural/quality gates should trigger remediation and retry; "
            "integrity/ownership/security gates remain hard stops."
        ),
        "auto_remediate": auto_remediate,
        "hard_stop": hard_stop,
    }


def gate_applies(
    gate_name: str,
    selected_paths: Sequence[str],
    path_scoped_gates: dict[str, Sequence[str]],
    *,
    normalize_path: Callable[[str], str],
) -> bool:
    prefixes = tuple(path_scoped_gates.get(gate_name) or ())
    if not prefixes:
        return True
    return any(normalize_path(path).startswith(prefix) for path in selected_paths for prefix in prefixes)


def resolved_gate_command(
    gate_name: str,
    command: Sequence[str],
    *,
    selected_paths: Sequence[str],
    normalize_path: Callable[[str], str],
) -> list[str]:
    resolved = list(command)
    if gate_name == "release_update":
        for path in selected_paths:
            normalized = normalize_path(path)
            if normalized:
                resolved.extend(["--changed-file", normalized])
    return resolved


def suggested_retry_command(*, gate_name: str, agent: str, message: str) -> str | None:
    safe_message = str(message or "").replace('"', '\\"').strip() or "checkpoint"
    if gate_name in {
        "active_folder_guard",
        "workboard_claims",
        "workboard_task_problems",
        "workboard_changed_files",
        "workboard_agent_claim",
    }:
        return (
            f'python scripts/crew/brief/bootstrap_claim.py --agent "{agent}" --task "{safe_message}" --no-auto-dispatch'
        )
    if gate_name == "site_visual_proof":
        return "python scripts/refresh_site_visual_proof.py; python scripts/forge/gates/site_visual_proof.py"
    if gate_name == "release_update":
        return "python scripts/forge/gates/release_update_gate.py --changed-file <path>"
    if gate_name == "monolith_guard":
        return "python scripts/forge/gates/monolith_guard.py --staged-only"
    return None
