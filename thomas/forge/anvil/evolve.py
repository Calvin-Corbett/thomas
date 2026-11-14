"""Green-side self-improvement runtime for Thomas evolve mode."""

from __future__ import annotations

import ast
import difflib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import subprocess  # nosec
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomllib

from evolve_supervisor import evaluate_spend_governor, record_evolve_child_spend, run_evolve_corpus, run_verifier_panel
from thomas.core.config import load_config
from thomas.core.model_resolution import resolve_model_profile_name
from thomas.preferences.model_resolution import resolve_effective_model

from .doppelganger import (
    _GREEN_SUPPORT_DIRS,
    _GREEN_SUPPORT_FILES,
    _IGNORE_NAMES,
    _INCLUDE_DIRS,
    _INCLUDE_FILES,
    SUPERVISOR_OWNED_PATHS,
    ensure_green_venv,
    find_project_root,
    get_paths,
    promote_green_delta_to_blue,
    sync_blue_to_green,
)

# Charter/session-store, architecture-debt sync, and prompt building were split
# into sibling modules (2026-07-15) to keep this file under MONOLITH_CEILING.
# Everything is re-exported here so `thomas.forge.anvil.evolve` remains the
# stable import surface for the CLI, server routes, and tests.
from .evolve_arch_sync import _sync_architecture_health_debt  # noqa: F401

# fmt: off
# isort: off
# Every moved name stays reachable as evolve.<name>; kept compact on purpose.
from .evolve_blue_green import (  # noqa: F401
    MAX_BLAST_RADIUS_TEST_FILES, BLUE_SUPERVISOR_MANIFEST_VERSION, BLUE_SUPERVISOR_MANIFEST_KEY,
    BLUE_SUPERVISOR_MANIFEST_SCOPES, EVOLVE_GREEN_QUALITY_ENV, logger, _PromotionRejected, _iter_scope_files,
    _canonical_json_bytes, _blue_supervisor_manifest_key_path, _load_or_create_blue_supervisor_manifest_key,
    _load_blue_supervisor_manifest_key, _blue_supervisor_manifest_payload, _signed_blue_supervisor_manifest,
    _validate_blue_supervisor_manifest_for_promotion, _read_text, _load_evolve_protected_paths,
    _is_evolve_protected_path, _restore_green_path_from_blue, _revert_protected_changes, _collect_tree_delta,
    _delta_signature, _delta_content_fingerprints_for_root, _delta_fingerprint_for_root, _delta_fingerprint,
    _delta_drift_rejection_reasons, _delta_fingerprint_drift_rejection_reasons, _diff_preview,
    _preferred_evolve_codex_profile, _normalize_evolve_profile_name, _resolve_evolve_profile,
    _evolve_secret_root, _copy_tree_without_caches, _prepare_verification_root,
    _prepare_delta_candidate_root, _validate_verified_delta_for_promotion, _non_python_delta_files,
    _has_passing_non_python_verifier, _non_python_rejection, _supervisor_rejection_codes, _verifier_panel_rejection_reason,
    _evolve_corpus_rejection_reason, _verifier_panel_nonpassing_votes, _evaluate_promotion_candidate,
    _is_test_infra_path, _is_loop_package_new_py, _is_loop_package_py, _is_green_support_path,
    _session_rejection_reasons, _session_status,
)
# isort: on
# fmt: on
from .evolve_charter import (  # noqa: F401
    DEFAULT_EVOLVE_GOAL,
    DEFAULT_EVOLVE_OBJECTIVE,
    DEFAULT_EVOLVE_PRINCIPLES,
    DEFAULT_VERIFY_COMMANDS,
    LEGACY_DEFAULT_VERIFY_COMMAND_SETS,
    EvolveCharter,
    _charter_json_path,
    _charter_markdown_path,
    _current_default_if_legacy,
    _normalize_relpath,
    _normalize_verify_commands,
    _read_json,
    _sessions_root,
    _sha256,
    _write_json,
    _write_text,
    build_charter_markdown,
    ensure_evolve_charter,
    has_evolve_charter,
    list_evolve_sessions,
    load_evolve_charter,
    load_evolve_session,
    load_latest_evolve_session,
    resolve_evolve_root,
    resolve_repo_root,
    utc_now_iso,
)
from .evolve_prompts import (  # noqa: F401
    _build_agent_prompt,
    _build_no_change_retry_goal,
    _render_session_markdown,
)
from .evolve_runtime_exec import (
    _build_green_chat_command,
    _evolve_child_env,
    _evolve_cli_fallback_enabled,
    _evolve_max_agent_iterations,
    _evolve_retry_max_agent_iterations,
    _merge_tool_denylist,
    _run_exec,
    _strip_evolve_verification_env,
)
from .evolve_verification import (  # noqa: F401
    MAX_BLAST_RADIUS_TEST_FILES as _MAX_BLAST_RADIUS_TEST_FILES,
)
from .evolve_verification import (  # noqa: F401
    _blast_radius_tests,
    _build_verification_failure_repair_goal,
    _build_verify_commands,
    _build_verify_plan,
    _normalize_acceptance_checks,
    _repairable_verification_failures,
    _run_verification_plan,
    _verification_floor_failures,
    _verification_result_blocks_promotion,
    _verification_skipped_reason,
    _write_verification_repair_artifacts,
)


def run_evolve_session(
    project_root: Path | None = None,
    *,
    goal: str = "",
    profile: str = "",
    passes: int | None = None,
    promote_on_pass: bool = False,
    timeout_seconds: int = 1800,
    refactor_first: bool = True,
    acceptance_checks: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    repo_root = resolve_repo_root(project_root)
    evolve_root, _, _ = ensure_evolve_charter(repo_root)
    charter = load_evolve_charter(repo_root)
    active_acceptance_checks = _normalize_acceptance_checks([*charter.acceptance_checks, *(acceptance_checks or [])])
    requested_passes = max(1, min(int(passes or charter.max_passes or 1), 8))
    effective_profile = _resolve_evolve_profile(repo_root, profile)
    session_id = f"evolve-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    session_dir = _sessions_root(repo_root) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now_iso()
    blue_supervisor_manifest = _signed_blue_supervisor_manifest(repo_root)

    paths = get_paths(repo_root)
    sync_blue_to_green(paths)

    # Ensure the green environment can run Thomas.
    # Prefer the dedicated green venv; fall back to the system Python with
    # PYTHONPATH pointed at the green mirror (works in sandboxed envs where
    # venv creation or network access may be blocked).
    try:
        green_python = str(ensure_green_venv(paths))
    except (OSError, RuntimeError, subprocess.SubprocessError):
        green_python = sys.executable

    green_env = _evolve_child_env()
    green_env["THOMAS_MEMORY_ROOT"] = str(paths.green_runtime)
    # Keep green memory isolated while allowing the model provider to reuse the
    # operator's existing OAuth connection.
    green_env["THOMAS_SECRET_ROOT"] = str(_evolve_secret_root(repo_root))
    green_env["THOMAS_MAX_AGENT_ITERATIONS"] = _evolve_max_agent_iterations()
    green_env["THOMAS_EVOLVE_GREEN_RUNTIME_WRITES"] = "1"
    green_env.update(EVOLVE_GREEN_QUALITY_ENV)
    _merge_tool_denylist(green_env)
    green_env["THOMAS_SPEND_PATH"] = str(
        Path(os.environ.get("THOMAS_SPEND_PATH") or (repo_root / "thomas_spend.jsonl"))
    )
    green_env["THOMAS_EVOLVE_SPEND_WATCHDOG_ROOT"] = str(repo_root)
    # Always set PYTHONPATH so that `python -m thomas` resolves from the
    # green mirror, even when using the system interpreter as fallback.
    green_env["PYTHONPATH"] = str(paths.green_root)

    spend_governor_checks: list[dict[str, Any]] = []
    spend_ledger_writes: list[dict[str, Any]] = []
    spend_governor_rejections: list[str] = []

    def _append_spend_rejection(phase: str, message: str) -> None:
        rejection = f"spend governor blocked {phase}: {message}"
        if rejection not in spend_governor_rejections:
            spend_governor_rejections.append(rejection)

    def _run_green_child_with_spend_accounting(
        command: str | list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout_seconds: int,
        phase: str,
        pass_index: int,
    ) -> dict[str, Any] | None:
        verdict = evaluate_spend_governor(repo_root)
        check_row = verdict.to_dict()
        check_row["phase"] = phase
        check_row["pass_index"] = int(pass_index)
        spend_governor_checks.append(check_row)
        if not verdict.ok:
            _append_spend_rejection(phase, verdict.message)
            return None

        result = _run_exec(
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
        )
        ledger_write = record_evolve_child_spend(
            repo_root,
            result,
            session_id=session_id,
            phase=phase,
            pass_index=pass_index,
        )
        write_row = ledger_write.to_dict()
        write_row["phase"] = phase
        write_row["pass_index"] = int(pass_index)
        spend_ledger_writes.append(write_row)
        if not ledger_write.ok:
            _append_spend_rejection(phase, ledger_write.message)
        return result

    refactor_child_index = 0

    def _run_refactor_child(
        command: str | list[str], *, cwd: Path, env: dict[str, str], timeout_seconds: int
    ) -> dict[str, Any]:
        nonlocal refactor_child_index
        refactor_child_index += 1
        result = _run_green_child_with_spend_accounting(
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            phase="refactor",
            pass_index=refactor_child_index,
        )
        if result is None or spend_governor_rejections:
            raise RuntimeError(
                spend_governor_rejections[-1] if spend_governor_rejections else "spend governor stopped refactor"
            )
        return result

    # Phase 0: Mandatory refactor pass (runs before creative passes)
    refactor_results: dict[str, Any] = {}
    if refactor_first:
        try:
            from .refactor_pass import run_refactor_pass

            refactor_results = run_refactor_pass(
                repo_root,
                paths,
                green_env=green_env,
                green_python=green_python,
                timeout_seconds=timeout_seconds,
                profile=effective_profile,
                run_exec=_run_refactor_child,
            )
        except (ImportError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Refactor pass failed (non-fatal, continuing): %s",
                exc,
            )
            refactor_results = {"phase": "refactor", "error": str(exc)}

    pass_results: list[dict[str, Any]] = []
    goal_used = str(goal or charter.default_goal).strip() or DEFAULT_EVOLVE_GOAL
    for idx in range(requested_passes):
        if spend_governor_rejections:
            break
        prompt = _build_agent_prompt(
            charter,
            goal_used,
            pass_index=idx + 1,
            pass_count=requested_passes,
            acceptance_checks=active_acceptance_checks,
        )
        command = _build_green_chat_command(green_python, effective_profile, prompt)
        result = _run_green_child_with_spend_accounting(
            command,
            cwd=paths.green_root,
            env=green_env,
            timeout_seconds=timeout_seconds,
            phase="creative",
            pass_index=idx + 1,
        )
        if result is None:
            break
        result["pass_index"] = idx + 1
        result["prompt"] = prompt
        pass_results.append(result)
        if int(result.get("returncode") or 0) != 0 or spend_governor_rejections:
            break

    no_change_retry_attempted = False
    if (
        not spend_governor_rejections
        and pass_results
        and all(int(item.get("returncode") or 0) == 0 for item in pass_results)
    ):
        retry_delta = _collect_tree_delta(paths)
        if int(retry_delta.get("changed_count") or 0) <= 0:
            no_change_retry_attempted = True
            retry_goal = _build_no_change_retry_goal(goal_used)
            prompt = _build_agent_prompt(
                charter,
                retry_goal,
                pass_index=len(pass_results) + 1,
                pass_count=len(pass_results) + 1,
                acceptance_checks=active_acceptance_checks,
            )
            command = _build_green_chat_command(
                green_python,
                effective_profile,
                prompt,
                max_iterations=_evolve_retry_max_agent_iterations(),
            )
            retry_env = dict(green_env)
            retry_env["THOMAS_SELF_DEVELOPMENT_WRITE_GUARD_LIMIT"] = "2"
            result = _run_green_child_with_spend_accounting(
                command,
                cwd=paths.green_root,
                env=retry_env,
                timeout_seconds=timeout_seconds,
                phase="no_change_retry",
                pass_index=len(pass_results) + 1,
            )
            if result is not None:
                result["pass_index"] = len(pass_results) + 1
                result["retry_reason"] = "no_candidate_changes"
                result["prompt"] = prompt
                pass_results.append(result)

    # Headless build fallback: if the in-process agent produced no changes (e.g. the
    # operator's model OAuth is not reachable in THIS process), build the goal via the
    # claude CLI in the green mirror so the loop still completes a real improvement on
    # the operator's own subscription. run_evolve_session's own (non-git) delta
    # detection + verification + the blue gate then process claude's changes unchanged.
    if (
        _evolve_cli_fallback_enabled()
        and not spend_governor_rejections
        and int(_collect_tree_delta(paths).get("changed_count") or 0) <= 0
    ):
        try:
            from .evolve_claude_bridge import dispatch_via_claude_cli

            _cli = dispatch_via_claude_cli(goal_used, cwd=paths.green_root, timeout=900, dry_run=False)
            pass_results.append(
                {
                    "pass_index": len(pass_results) + 1,
                    "phase": "cli_fallback",
                    "returncode": 0 if _cli.ok else 1,
                    "prompt": goal_used,
                    "cli_fallback": _cli.to_dict(),
                }
            )
            # When the CLI fallback IS the builder and it succeeded with real changes,
            # the in-process agent's failure (no reachable model) is expected and must
            # not mark the whole session agent_failed. Neutralize those superseded
            # failures so the session is judged on the verified CLI-built delta.
            if _cli.ok and int(_collect_tree_delta(paths).get("changed_count") or 0) > 0:
                for _pr in pass_results:
                    if _pr.get("phase") != "cli_fallback" and int(_pr.get("returncode") or 0) != 0:
                        _pr["returncode_original"] = _pr.get("returncode")
                        _pr["returncode"] = 0
                        _pr["superseded_by_cli_fallback"] = True
        # The fallback spawns the `claude` CLI and reads its stream-json output, so
        # the transport faults are OSError (spawn/pipe) and subprocess.SubprocessError
        # (TimeoutExpired). Parsing that stream and the tree delta gives ValueError
        # (covers json.JSONDecodeError and UnicodeDecodeError), TypeError, KeyError,
        # IndexError and AttributeError; the bridge's own guards raise RuntimeError;
        # the lazy import can raise ImportError. Recorded as a failed pass rather
        # than raised because the session is judged on the verified tree delta.
        except (
            ImportError,
            OSError,
            subprocess.SubprocessError,
            AttributeError,
            IndexError,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            pass_results.append(
                {"pass_index": len(pass_results) + 1, "phase": "cli_fallback", "returncode": 1, "error": str(exc)}
            )

    pre_sync_delta = _collect_tree_delta(paths)
    architecture_sync = _sync_architecture_health_debt(paths, set(pre_sync_delta.get("changed_files") or []))
    pre_policy_delta = _collect_tree_delta(paths)
    protected_paths = _load_evolve_protected_paths(repo_root)
    delta, policy_violations, reverted_policy_paths = _revert_protected_changes(
        paths,
        pre_policy_delta,
        protected_paths,
    )
    session_rejections = [*_session_rejection_reasons(delta), *spend_governor_rejections]
    verify_root = _prepare_verification_root(paths)
    verification_floor_failures = (
        []
        if policy_violations or session_rejections
        else _verification_floor_failures(delta, verify_root, blue_root=paths.blue_root)
    )
    agent_failed = any(int(item.get("returncode") or 0) != 0 for item in pass_results)
    verification_skipped_reason = _verification_skipped_reason(
        agent_failed=agent_failed,
        policy_violations=policy_violations,
        session_rejections=session_rejections,
        verification_floor_failures=verification_floor_failures,
        delta=delta,
    )
    verify_plan = (
        []
        if verification_skipped_reason
        else _build_verify_plan(
            charter,
            delta,
            verify_root,
            goal=goal_used,
            acceptance_checks=active_acceptance_checks,
        )
    )
    verified_delta_fingerprint = _delta_fingerprint(paths, delta)
    blue_delta_base_fingerprint = _delta_fingerprint_for_root(paths.blue_root, delta)
    verification_delta_fingerprint = _delta_fingerprint_for_root(verify_root, delta)
    verification = _run_verification_plan(
        paths,
        verify_root=verify_root,
        verify_plan=verify_plan,
        timeout_seconds=timeout_seconds,
        artifact_dir=session_dir / "verification-output" / "initial",
        prepare_verification_root=_prepare_verification_root,
        evolve_child_env=_evolve_child_env,
        run_exec=_run_exec,
        strip_evolve_verification_env=_strip_evolve_verification_env,
    )
    verification_repair_attempted = False
    verification_repair_failures = _repairable_verification_failures(verification)
    verification_repair_artifacts: list[dict[str, str]] = []
    if (
        verification_repair_failures
        and not agent_failed
        and not policy_violations
        and not session_rejections
        and not verification_floor_failures
    ):
        verification_repair_attempted = True
        verification_repair_artifacts = _write_verification_repair_artifacts(
            session_dir,
            verification_repair_failures,
        )
        repair_goal = _build_verification_failure_repair_goal(
            goal_used,
            verification_repair_failures,
            artifacts=verification_repair_artifacts,
        )
        prompt = _build_agent_prompt(
            charter,
            repair_goal,
            pass_index=len(pass_results) + 1,
            pass_count=len(pass_results) + 1,
            acceptance_checks=active_acceptance_checks,
        )
        command = _build_green_chat_command(
            green_python,
            effective_profile,
            prompt,
            max_iterations=_evolve_retry_max_agent_iterations(),
        )
        repair_env = dict(green_env)
        repair_env["THOMAS_SELF_DEVELOPMENT_WRITE_GUARD_LIMIT"] = "2"
        result = _run_green_child_with_spend_accounting(
            command,
            cwd=paths.green_root,
            env=repair_env,
            timeout_seconds=timeout_seconds,
            phase="verification_repair",
            pass_index=len(pass_results) + 1,
        )
        if result is not None:
            result["pass_index"] = len(pass_results) + 1
            result["retry_reason"] = "verification_failure"
            result["verification_failures"] = verification_repair_failures
            result["verification_failure_artifacts"] = verification_repair_artifacts
            result["prompt"] = prompt
            pass_results.append(result)

        pre_policy_delta = _collect_tree_delta(paths)
        delta, policy_violations, reverted_policy_paths = _revert_protected_changes(
            paths,
            pre_policy_delta,
            protected_paths,
        )
        session_rejections = [*_session_rejection_reasons(delta), *spend_governor_rejections]
        verify_root = _prepare_verification_root(paths)
        verification_floor_failures = (
            []
            if policy_violations or session_rejections
            else _verification_floor_failures(delta, verify_root, blue_root=paths.blue_root)
        )
        agent_failed = any(int(item.get("returncode") or 0) != 0 for item in pass_results)
        verification_skipped_reason = _verification_skipped_reason(
            agent_failed=agent_failed,
            policy_violations=policy_violations,
            session_rejections=session_rejections,
            verification_floor_failures=verification_floor_failures,
            delta=delta,
        )
        verify_plan = (
            []
            if verification_skipped_reason
            else _build_verify_plan(
                charter,
                delta,
                verify_root,
                goal=goal_used,
                acceptance_checks=active_acceptance_checks,
            )
        )
        verified_delta_fingerprint = _delta_fingerprint(paths, delta)
        blue_delta_base_fingerprint = _delta_fingerprint_for_root(paths.blue_root, delta)
        verification_delta_fingerprint = _delta_fingerprint_for_root(verify_root, delta)
        verification = _run_verification_plan(
            paths,
            verify_root=verify_root,
            verify_plan=verify_plan,
            timeout_seconds=timeout_seconds,
            artifact_dir=session_dir / "verification-output" / "after-repair",
            prepare_verification_root=_prepare_verification_root,
            evolve_child_env=_evolve_child_env,
            run_exec=_run_exec,
            strip_evolve_verification_env=_strip_evolve_verification_env,
        )
    post_verification_sandbox_fingerprint = _delta_fingerprint_for_root(verify_root, delta)
    post_verification_delta = _collect_tree_delta(paths)
    delta_drift_rejections = _delta_drift_rejection_reasons(delta, post_verification_delta)
    post_verification_delta_fingerprint = _delta_fingerprint(paths, post_verification_delta)
    delta_drift_rejections.extend(
        _delta_fingerprint_drift_rejection_reasons(
            verified_delta_fingerprint,
            post_verification_delta_fingerprint,
        )
    )
    verification_sandbox_rejections = _delta_fingerprint_drift_rejection_reasons(
        verification_delta_fingerprint,
        post_verification_sandbox_fingerprint,
    )
    verification_sandbox_rejections = [
        item.replace("green tree content changed after verification", "verification sandbox content changed")
        for item in verification_sandbox_rejections
    ]
    session_rejections = [*session_rejections, *delta_drift_rejections]
    session_rejections = [*session_rejections, *verification_sandbox_rejections]

    diff_path = session_dir / "changes.patch"
    _write_text(diff_path, _diff_preview(paths, delta) or "# No tracked changes\n")

    # P0 safety rule: touching protected or test infrastructure rejects the whole
    # session. Reverting the protected file is cleanup only; it is not permission
    # to promote the remainder.
    promotable = (
        bool(delta["changed_count"])
        and bool(verification)
        and not agent_failed
        and not policy_violations
        and not session_rejections
        and not verification_floor_failures
        and not any(_verification_result_blocks_promotion(item) for item in verification)
    )
    promoted = False
    promotion_backup = ""
    supervisor_verdict: dict[str, Any] = {}
    verifier_panel: dict[str, Any] = {}
    if promote_on_pass and promotable:
        promotion_payload = {
            "session_id": session_id,
            "repo_root": str(repo_root),
            "evolve_root": str(evolve_root),
            "green_root": str(paths.green_root),
            "goal": goal_used,
            "acceptance_checks": active_acceptance_checks,
            "profile": effective_profile,
            "passes_requested": requested_passes,
            "verification": verification,
            "verification_delta_fingerprint": verification_delta_fingerprint,
            "verified_delta_fingerprint": verified_delta_fingerprint,
            "blue_delta_base_fingerprint": blue_delta_base_fingerprint,
            "blue_supervisor_manifest": blue_supervisor_manifest,
            "post_verification_delta_fingerprint": post_verification_delta_fingerprint,
            "session_rejections": session_rejections,
            "policy_violations": policy_violations,
            "delta": delta,
            "changed_files": list(delta["changed_files"]),
            "promotable": promotable,
            "promoted": False,
        }
        try:
            backup, supervisor_verdict = _promote_verified_green_delta(
                paths,
                promotion_payload,
                delta,
                candidate_dirname="promote-candidate-auto",
            )
            promotion_backup = str(backup)
            promoted = True
            verifier_panel = dict(supervisor_verdict.get("verifier_panel") or {})
        except _PromotionRejected as exc:
            supervisor_verdict = exc.supervisor_verdict
            verifier_panel = dict(supervisor_verdict.get("verifier_panel") or {})
            session_rejections = [*session_rejections, f"auto-promotion rejected: {exc}"]
            promotable = False
        except RuntimeError as exc:
            session_rejections = [*session_rejections, f"auto-promotion rejected: {exc}"]
            promotable = False

    session = {
        "session_id": session_id,
        "repo_root": str(repo_root),
        "evolve_root": str(evolve_root),
        "green_root": str(paths.green_root),
        "goal": goal_used,
        "acceptance_checks": active_acceptance_checks,
        "profile": effective_profile,
        "passes_requested": requested_passes,
        "no_change_retry_attempted": no_change_retry_attempted,
        "verification_repair_attempted": verification_repair_attempted,
        "verification_repair_failures": verification_repair_failures,
        "verification_repair_artifacts": verification_repair_artifacts,
        "refactor_results": refactor_results,
        "pass_results": pass_results,
        "spend_governor_checks": spend_governor_checks,
        "spend_ledger_writes": spend_ledger_writes,
        "spend_governor_rejections": spend_governor_rejections,
        "verification": verification,
        "verification_skipped_reason": verification_skipped_reason,
        "verification_root": str(verify_root),
        "verification_delta_fingerprint": verification_delta_fingerprint,
        "post_verification_sandbox_fingerprint": post_verification_sandbox_fingerprint,
        "verification_sandbox_rejections": verification_sandbox_rejections,
        "post_verification_delta": post_verification_delta,
        "verified_delta_fingerprint": verified_delta_fingerprint,
        "blue_delta_base_fingerprint": blue_delta_base_fingerprint,
        "blue_supervisor_manifest": blue_supervisor_manifest,
        "post_verification_delta_fingerprint": post_verification_delta_fingerprint,
        "delta_drift_rejections": delta_drift_rejections,
        "verification_floor_failures": verification_floor_failures,
        "session_rejections": session_rejections,
        "policy_violations": policy_violations,
        "reverted_policy_paths": reverted_policy_paths,
        "tamper_count": len(policy_violations),
        "architecture_sync": architecture_sync,
        "delta": delta,
        "changed_files": list(delta["changed_files"]),
        "promotable": promotable,
        "promoted": promoted,
        "promotion_backup": promotion_backup,
        "supervisor_verdict": supervisor_verdict,
        "verifier_panel": verifier_panel,
        "diff_path": str(diff_path),
        "charter": charter.to_dict(),
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "status": _session_status(
            pass_results,
            verification,
            delta["changed_count"],
            promoted,
            policy_violations=policy_violations,
            session_rejections=session_rejections,
            verification_floor_failures=verification_floor_failures,
        ),
    }
    _write_json(session_dir / "session.json", session)
    _write_text(session_dir / "session.md", _render_session_markdown(session))
    return {"ok": session["status"] != "agent_failed", "session": session}


def promote_evolve_session(
    project_root: Path | None = None,
    *,
    session_id: str = "",
    stop_port: int = 8899,
    allow_critical_risk_floor: bool = False,
) -> dict[str, Any]:
    repo_root = resolve_repo_root(project_root)
    session = (
        load_evolve_session(repo_root, session_id) if str(session_id).strip() else load_latest_evolve_session(repo_root)
    )
    if session is None:
        raise RuntimeError("no evolve sessions found")
    if session.get("promoted"):
        return {"ok": True, "session": session, "already_promoted": True}
    if not bool(session.get("promotable")):
        raise RuntimeError("latest evolve session is not promotable")
    paths = get_paths(repo_root)
    if not paths.green_root.exists():
        raise RuntimeError("green doppelganger slot does not exist")
    expected_delta = dict(session.get("delta") or {})
    changed_files = [str(item) for item in expected_delta.get("changed_files") or []]
    if reason := _non_python_rejection(changed_files, session):
        raise RuntimeError(reason)
    backup, supervisor_verdict = _promote_verified_green_delta(
        paths,
        session,
        expected_delta,
        stop_port=int(stop_port),
        allow_critical_risk_floor=bool(allow_critical_risk_floor),
    )
    session["promoted"] = True
    session["supervisor_verdict"] = supervisor_verdict
    session["verifier_panel"] = dict(supervisor_verdict.get("verifier_panel") or {})
    session["promotion_backup"] = str(backup)
    session["status"] = "promoted"
    session["finished_at"] = utc_now_iso()
    session_dir = _sessions_root(repo_root) / str(session["session_id"])
    _write_json(session_dir / "session.json", session)
    _write_text(session_dir / "session.md", _render_session_markdown(session))
    return {"ok": True, "session": session, "backup_path": str(backup)}


def _promote_verified_green_delta(
    paths,
    session_payload: dict[str, Any],
    expected_delta: dict[str, Any],
    *,
    stop_port: int = 8899,
    candidate_dirname: str = "promote-candidate",
    allow_critical_risk_floor: bool = False,
) -> tuple[Path, dict[str, Any]]:
    changed_files = _validate_verified_delta_for_promotion(paths, session_payload, expected_delta)
    supervisor_verdict = _evaluate_promotion_candidate(
        paths,
        expected_delta,
        session_payload,
        candidate_dirname=candidate_dirname,
    )
    if not supervisor_verdict.get("ok"):
        codes = _supervisor_rejection_codes(supervisor_verdict)
        raise _PromotionRejected(
            f"blue-only supervisor rejected evolve promotion: {codes or 'unknown'}",
            supervisor_verdict=supervisor_verdict,
        )
    panel_result = run_verifier_panel(session_payload, supervisor_verdict=supervisor_verdict)
    verifier_panel = panel_result.to_dict()
    supervisor_verdict["verifier_panel"] = verifier_panel
    if not verifier_panel.get("ok") or _verifier_panel_nonpassing_votes(verifier_panel):
        raise _PromotionRejected(
            f"verifier panel rejected evolve promotion: {_verifier_panel_rejection_reason(verifier_panel)}",
            supervisor_verdict=supervisor_verdict,
        )
    if str(supervisor_verdict.get("risk_floor") or "").strip().lower() == "critical" and not allow_critical_risk_floor:
        raise _PromotionRejected(
            "blue-only supervisor requires human approval for critical risk floor",
            supervisor_verdict=supervisor_verdict,
        )
    if reason := _non_python_rejection(changed_files, session_payload):
        raise _PromotionRejected(reason, supervisor_verdict=supervisor_verdict)
    corpus_result = run_evolve_corpus(paths.blue_root).to_dict()
    supervisor_verdict["evolve_corpus"] = corpus_result
    if not bool(corpus_result.get("ok")):
        raise _PromotionRejected(
            f"blue evolve corpus rejected promotion: {_evolve_corpus_rejection_reason(corpus_result)}",
            supervisor_verdict=supervisor_verdict,
        )
    backup = promote_green_delta_to_blue(paths, changed_files, stop_port=int(stop_port))
    return backup, supervisor_verdict
