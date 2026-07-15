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
from thomas.core.model_resolution import resolve_effective_model, resolve_model_profile_name

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
from .evolve_verification import (
    MAX_BLAST_RADIUS_TEST_FILES as _MAX_BLAST_RADIUS_TEST_FILES,
)
from .evolve_verification import (
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

MAX_BLAST_RADIUS_TEST_FILES = _MAX_BLAST_RADIUS_TEST_FILES
BLUE_SUPERVISOR_MANIFEST_VERSION = 1
BLUE_SUPERVISOR_MANIFEST_KEY = ".thomas/evolve/blue-supervisor-manifest.key"
BLUE_SUPERVISOR_MANIFEST_SCOPES = (
    "evolve_supervisor",
    "thomas/forge/anvil",
)

EVOLVE_GREEN_QUALITY_ENV = {
    "THOMAS_QUALITY_ENABLED": "false",
    "THOMAS_QUALITY_ENFORCE": "false",
    "THOMAS_QUALITY_MAX_AUTO_RETRIES": "0",
}
logger = logging.getLogger(__name__)


class _PromotionRejected(RuntimeError):
    def __init__(self, message: str, *, supervisor_verdict: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.supervisor_verdict = supervisor_verdict or {}


def _iter_scope_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for name in tuple(_INCLUDE_FILES) + tuple(_GREEN_SUPPORT_FILES):
        candidate = root / name
        if candidate.is_file():
            files[candidate.relative_to(root).as_posix()] = candidate
    for dirname in tuple(_INCLUDE_DIRS) + tuple(_GREEN_SUPPORT_DIRS):
        base = root / dirname
        if not base.exists():
            continue
        for candidate in base.rglob("*"):
            if candidate.is_dir():
                continue
            if candidate.name.endswith(".pyc"):
                continue
            if any(part in _IGNORE_NAMES for part in candidate.parts):
                continue
            files[candidate.relative_to(root).as_posix()] = candidate
    return files


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _blue_supervisor_manifest_key_path(repo_root: Path) -> Path:
    return Path(repo_root) / BLUE_SUPERVISOR_MANIFEST_KEY


def _load_or_create_blue_supervisor_manifest_key(repo_root: Path) -> bytes:
    key_path = _blue_supervisor_manifest_key_path(repo_root)
    if key_path.exists():
        raw = key_path.read_text(encoding="utf-8").strip()
        if raw:
            return bytes.fromhex(raw)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    raw = secrets.token_hex(32)
    key_path.write_text(raw + "\n", encoding="utf-8")
    return bytes.fromhex(raw)


def _load_blue_supervisor_manifest_key(repo_root: Path) -> bytes:
    key_path = _blue_supervisor_manifest_key_path(repo_root)
    if not key_path.exists():
        raise RuntimeError("evolve session is missing blue supervisor manifest key; refusing promotion")
    raw = key_path.read_text(encoding="utf-8").strip()
    if not raw:
        raise RuntimeError("evolve session has an empty blue supervisor manifest key; refusing promotion")
    return bytes.fromhex(raw)


def _blue_supervisor_manifest_payload(repo_root: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    root = Path(repo_root)
    for scope in BLUE_SUPERVISOR_MANIFEST_SCOPES:
        base = root / scope
        if not base.exists():
            continue
        for candidate in sorted(base.rglob("*.py")):
            if not candidate.is_file():
                continue
            rel = candidate.relative_to(root)
            if any(part in _IGNORE_NAMES for part in rel.parts):
                continue
            files[rel.as_posix()] = _sha256(candidate)
    payload = {
        "version": BLUE_SUPERVISOR_MANIFEST_VERSION,
        "scopes": list(BLUE_SUPERVISOR_MANIFEST_SCOPES),
        "files": files,
    }
    payload["manifest_sha256"] = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return payload


def _signed_blue_supervisor_manifest(repo_root: Path) -> dict[str, Any]:
    payload = _blue_supervisor_manifest_payload(repo_root)
    key = _load_or_create_blue_supervisor_manifest_key(repo_root)
    payload["signature"] = {
        "alg": "hmac-sha256",
        "value": hmac.new(key, _canonical_json_bytes(payload), hashlib.sha256).hexdigest(),
    }
    return payload


def _validate_blue_supervisor_manifest_for_promotion(repo_root: Path, session: dict[str, Any]) -> None:
    manifest = dict(session.get("blue_supervisor_manifest") or {})
    if not manifest:
        raise RuntimeError("evolve session is missing blue supervisor/anvil manifest; refusing promotion")
    signature = dict(manifest.get("signature") or {})
    if signature.get("alg") != "hmac-sha256" or not str(signature.get("value") or "").strip():
        raise RuntimeError("evolve session has an invalid blue supervisor/anvil manifest signature; refusing promotion")
    signed_value = str(signature["value"])
    unsigned_manifest = dict(manifest)
    unsigned_manifest.pop("signature", None)
    expected_manifest = _blue_supervisor_manifest_payload(repo_root)
    if unsigned_manifest != expected_manifest:
        raise RuntimeError("blue supervisor/anvil files changed since evolve session baseline; refusing promotion")
    key = _load_blue_supervisor_manifest_key(repo_root)
    actual_signature = hmac.new(key, _canonical_json_bytes(unsigned_manifest), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signed_value, actual_signature):
        raise RuntimeError("blue supervisor/anvil manifest signature mismatch; refusing promotion")


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    except OSError:
        return None


def _load_evolve_protected_paths(repo_root: Path) -> set[str]:
    relpaths = set(SUPERVISOR_OWNED_PATHS)
    config_path = repo_root / "agent_safety.toml"
    if not config_path.exists():
        return relpaths
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return relpaths
    protected = payload.get("protected")
    if not isinstance(protected, dict):
        return relpaths
    for key in ("policy_files", "guardrails_files", "enforcement_files", "enforcement_scripts"):
        rows = protected.get(key) or []
        if not isinstance(rows, list):
            continue
        for item in rows:
            rel = _normalize_relpath(str(item or "")).strip()
            if rel:
                relpaths.add(rel)
    return relpaths


def _is_evolve_protected_path(rel: str, protected_paths: set[str]) -> bool:
    norm = _normalize_relpath(rel)
    if norm in protected_paths:
        return True
    return any(item.endswith("/") and norm.startswith(item.rstrip("/") + "/") for item in protected_paths if item)


def _restore_green_path_from_blue(paths, rel: str) -> None:
    rel_path = Path(_normalize_relpath(rel))
    blue_path = paths.blue_root / rel_path
    green_path = paths.green_root / rel_path
    if blue_path.exists():
        green_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(blue_path, green_path)
        return
    if green_path.exists():
        green_path.unlink()


def _revert_protected_changes(
    paths,
    delta: dict[str, Any],
    protected_paths: set[str],
    *,
    allow_retain: set[str] | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    retained = {_normalize_relpath(rel) for rel in (allow_retain or set())}
    violations = sorted(
        rel
        for rel in (delta.get("changed_files") or [])
        if _is_evolve_protected_path(_normalize_relpath(rel), protected_paths)
        and _normalize_relpath(rel) not in retained
    )
    reverted: list[str] = []
    for rel in violations:
        _restore_green_path_from_blue(paths, rel)
        reverted.append(rel)
    if violations:
        delta = _collect_tree_delta(paths)
    return delta, violations, reverted


def _collect_tree_delta(paths) -> dict[str, Any]:
    blue = _iter_scope_files(paths.blue_root)
    green = _iter_scope_files(paths.green_root)
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    for rel in sorted(set(blue) | set(green)):
        blue_path = blue.get(rel)
        green_path = green.get(rel)
        if blue_path is None and green_path is not None:
            added.append(rel)
        elif green_path is None and blue_path is not None:
            removed.append(rel)
        elif blue_path is not None and green_path is not None and _sha256(blue_path) != _sha256(green_path):
            modified.append(rel)
    changed = list(added) + list(modified) + list(removed)
    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "changed_files": changed,
        "changed_count": len(changed),
    }


def _delta_signature(delta: dict[str, Any]) -> dict[str, Any]:
    return {
        "added": sorted(str(rel) for rel in (delta.get("added") or [])),
        "modified": sorted(str(rel) for rel in (delta.get("modified") or [])),
        "removed": sorted(str(rel) for rel in (delta.get("removed") or [])),
        "changed_files": sorted(str(rel) for rel in (delta.get("changed_files") or [])),
        "changed_count": int(delta.get("changed_count") or 0),
    }


def _delta_content_fingerprints_for_root(root: Path, delta: dict[str, Any]) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for rel in sorted(str(item) for item in (delta.get("changed_files") or [])):
        green_path = Path(root) / rel
        if green_path.is_file():
            fingerprints[rel] = _sha256(green_path)
        else:
            fingerprints[rel] = "<missing>"
    return fingerprints


def _delta_fingerprint_for_root(root: Path, delta: dict[str, Any]) -> dict[str, Any]:
    return {
        "signature": _delta_signature(delta),
        "content": _delta_content_fingerprints_for_root(root, delta),
    }


def _delta_fingerprint(paths, delta: dict[str, Any]) -> dict[str, Any]:
    return _delta_fingerprint_for_root(paths.green_root, delta)


def _delta_drift_rejection_reasons(expected_delta: dict[str, Any], current_delta: dict[str, Any]) -> list[str]:
    if _delta_signature(expected_delta) == _delta_signature(current_delta):
        return []
    current_preview = ", ".join(list(_delta_signature(current_delta)["changed_files"])[:8])
    expected_preview = ", ".join(list(_delta_signature(expected_delta)["changed_files"])[:8])
    return [
        "green tree changed after verification: "
        f"verified=[{expected_preview or 'none'}]; current=[{current_preview or 'none'}]"
    ]


def _delta_fingerprint_drift_rejection_reasons(
    expected_fingerprint: dict[str, Any],
    current_fingerprint: dict[str, Any],
) -> list[str]:
    if expected_fingerprint == current_fingerprint:
        return []
    expected_files = ", ".join(list(dict(expected_fingerprint.get("content") or {}).keys())[:8])
    current_files = ", ".join(list(dict(current_fingerprint.get("content") or {}).keys())[:8])
    return [
        "green tree content changed after verification: "
        f"verified=[{expected_files or 'none'}]; current=[{current_files or 'none'}]"
    ]


def _diff_preview(paths, delta: dict[str, Any], *, limit: int = 32) -> str:
    out: list[str] = []
    for rel in list(delta.get("modified") or [])[:limit]:
        before = _read_text(paths.blue_root / rel)
        after = _read_text(paths.green_root / rel)
        if before is None or after is None:
            out.append(f"*** {rel} (binary or undecodable)\n")
            continue
        out.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                n=3,
            )
        )
    for rel in list(delta.get("added") or [])[:limit]:
        after = _read_text(paths.green_root / rel)
        if after is None:
            out.append(f"*** {rel} (new binary or undecodable file)\n")
            continue
        out.extend(
            difflib.unified_diff([], after.splitlines(keepends=True), fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3)
        )
    for rel in list(delta.get("removed") or [])[:limit]:
        before = _read_text(paths.blue_root / rel)
        if before is None:
            out.append(f"*** {rel} (removed binary or undecodable file)\n")
            continue
        out.extend(
            difflib.unified_diff(before.splitlines(keepends=True), [], fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3)
        )
    return "".join(out)


def _preferred_evolve_codex_profile(config: Any) -> str:
    if "openai_codex" in config.models:
        return "openai_codex"
    if "codex" in config.models:
        return "codex"
    return ""


def _normalize_evolve_profile_name(config: Any, profile_name: str | None) -> str:
    requested = str(profile_name or "").strip()
    if not requested:
        return ""
    resolved = resolve_model_profile_name(config, requested)
    if resolved:
        return resolved
    if requested.lower() == "codex":
        return _preferred_evolve_codex_profile(config) or requested
    return requested


def _resolve_evolve_profile(repo_root: Path, requested_profile: str = "") -> str:
    config = load_config(repo_root / "thomas.toml")
    requested = _normalize_evolve_profile_name(config, requested_profile)
    env_profile = _normalize_evolve_profile_name(config, os.environ.get("THOMAS_DEFAULT_MODEL", ""))
    resolved_profile, _ = resolve_effective_model(
        config,
        cli_profile=requested or None,
        env_profile=env_profile or None,
    )
    resolved = str(resolved_profile or "").strip()
    preferred_codex = _preferred_evolve_codex_profile(config)
    if not resolved and preferred_codex:
        return preferred_codex
    if not str(requested_profile or "").strip() and resolved.lower() == "local" and preferred_codex:
        return preferred_codex
    return resolved


def _evolve_secret_root(repo_root: Path) -> Path:
    override = str(os.environ.get("THOMAS_SECRET_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return load_config(repo_root / "thomas.toml").memory.root_path / ".thomas"


def _copy_tree_without_caches(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for candidate in src.rglob("*"):
        rel = candidate.relative_to(src)
        if any(part in _IGNORE_NAMES for part in rel.parts):
            continue
        target = dst / rel
        if candidate.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target)


def _prepare_verification_root(paths, *, source_root: Path | None = None, dirname: str = "verify") -> Path:
    """Build a clean exam mirror from scoped green files only."""
    source = Path(source_root or paths.green_root)
    verify_root = paths.dg_root / dirname
    if verify_root.exists():
        shutil.rmtree(verify_root)
    verify_root.mkdir(parents=True, exist_ok=True)
    for support_dir in tuple(_INCLUDE_DIRS) + tuple(_GREEN_SUPPORT_DIRS):
        src = source / support_dir
        if src.exists():
            _copy_tree_without_caches(src, verify_root / support_dir)
    for filename in tuple(_INCLUDE_FILES) + tuple(_GREEN_SUPPORT_FILES):
        src = source / filename
        if src.exists():
            target = verify_root / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    return verify_root


def _prepare_delta_candidate_root(paths, delta: dict[str, Any], *, dirname: str = "promote-candidate") -> Path:
    """Build current-blue plus the verified green delta for supervisor review."""
    candidate_root = paths.dg_root / dirname
    if candidate_root.exists():
        shutil.rmtree(candidate_root)
    candidate_root.mkdir(parents=True, exist_ok=True)
    for include_dir in tuple(_INCLUDE_DIRS) + tuple(_GREEN_SUPPORT_DIRS):
        src = paths.blue_root / include_dir
        if src.exists():
            _copy_tree_without_caches(src, candidate_root / include_dir)
    for include_file in tuple(_INCLUDE_FILES) + tuple(_GREEN_SUPPORT_FILES):
        src = paths.blue_root / include_file
        if src.exists():
            target = candidate_root / include_file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    for rel in sorted(str(item) for item in (delta.get("changed_files") or [])):
        src = paths.green_root / rel
        target = candidate_root / rel
        if src.exists():
            if src.is_dir():
                raise RuntimeError(f"candidate delta path is a directory: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        elif target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
    return candidate_root


def _validate_verified_delta_for_promotion(paths, session: dict[str, Any], expected_delta: dict[str, Any]) -> list[str]:
    changed_files = list(expected_delta.get("changed_files") or [])
    current_fingerprint = _delta_fingerprint_for_root(paths.green_root, expected_delta)
    expected_fingerprint = dict(session.get("verified_delta_fingerprint") or {})
    if not expected_fingerprint:
        raise RuntimeError("evolve session is missing verified delta fingerprint; refusing promotion")
    if expected_fingerprint != current_fingerprint:
        raise RuntimeError("green tree changed since evolve session verification; refusing promotion")
    expected_blue_base = dict(session.get("blue_delta_base_fingerprint") or {})
    if not expected_blue_base:
        raise RuntimeError("evolve session is missing blue delta base fingerprint; refusing promotion")
    current_blue_base = _delta_fingerprint_for_root(paths.blue_root, expected_delta)
    if expected_blue_base != current_blue_base:
        raise RuntimeError("blue target files changed since evolve session baseline; refusing promotion")
    _validate_blue_supervisor_manifest_for_promotion(paths.blue_root, session)
    return changed_files


def _non_python_delta_files(changed_files: list[str]) -> list[str]:
    return [str(rel).replace("\\", "/") for rel in changed_files if not str(rel).replace("\\", "/").endswith(".py")]


def _has_passing_non_python_verifier(session: dict[str, Any]) -> bool:
    for item in session.get("verification") or []:
        if not isinstance(item, dict) or int(item.get("returncode") or 0) != 0:
            continue
        label = " ".join(
            str(item.get(key) or "") for key in ("source", "description", "acceptance_check", "command")
        ).lower()
        normalized = label.replace("_", "-")
        if "non-python" in normalized or "nonpy" in normalized:
            return True
    return False


def _supervisor_rejection_codes(supervisor_verdict: dict[str, Any]) -> str:
    return ", ".join(str(item.get("code") or "unknown") for item in (supervisor_verdict.get("findings") or [])[:8])


def _verifier_panel_rejection_reason(panel_result: dict[str, Any]) -> str:
    critical_dissent_count = int(panel_result.get("critical_dissent_count") or 0)
    if critical_dissent_count:
        return f"{critical_dissent_count} critical dissent vote(s)"
    pass_count = int(panel_result.get("pass_count") or 0)
    quorum = int(panel_result.get("quorum") or 0)
    nonpassing_votes = _verifier_panel_nonpassing_votes(panel_result)
    if nonpassing_votes:
        return "non-passing verifier vote(s): " + ", ".join(nonpassing_votes[:5])
    return f"pass_count {pass_count} below quorum {quorum}"


def _evolve_corpus_rejection_reason(corpus_result: dict[str, Any]) -> str:
    lock_errors = corpus_result.get("lock_errors") or []
    if lock_errors:
        codes = [str(item.get("code") or "unknown") for item in lock_errors if isinstance(item, dict)]
        return "lock errors: " + ", ".join(codes[:5])
    failed_cases = [
        str(item.get("case_id") or "unknown")
        for item in (corpus_result.get("cases") or [])
        if isinstance(item, dict) and not bool(item.get("ok"))
    ]
    if failed_cases:
        return "failed cases: " + ", ".join(failed_cases[:5])
    return "no passing evolve corpus cases"


def _verifier_panel_nonpassing_votes(panel_result: dict[str, Any]) -> list[str]:
    votes = panel_result.get("votes") or []
    nonpassing: list[str] = []
    for vote in votes:
        if not isinstance(vote, dict):
            continue
        status = str(vote.get("status") or "").strip() or "unknown"
        if status == "pass":
            continue
        role = str(vote.get("role") or "unknown").strip() or "unknown"
        nonpassing.append(f"{role}:{status}")
    return nonpassing


def _evaluate_promotion_candidate(
    paths,
    expected_delta: dict[str, Any],
    session_payload: dict[str, Any],
    *,
    candidate_dirname: str = "promote-candidate",
) -> dict[str, Any]:
    try:
        from evolve_supervisor import evaluate_candidate
    except ImportError as exc:
        raise RuntimeError("blue-only evolve supervisor is unavailable; refusing promotion") from exc

    candidate_root = _prepare_delta_candidate_root(paths, expected_delta, dirname=candidate_dirname)
    return evaluate_candidate(
        paths.blue_root,
        candidate_root,
        claimed_category=str(session_payload.get("category") or ""),
        claimed_risk=str(session_payload.get("risk_tier") or "low"),
        session_payload=session_payload,
    ).to_dict()


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
    non_python_files = _non_python_delta_files(changed_files)
    if non_python_files and not _has_passing_non_python_verifier(session_payload):
        preview = ", ".join(non_python_files[:8])
        raise _PromotionRejected(
            f"non-Python delta requires a dedicated passing non-Python verifier before promotion: {preview}",
            supervisor_verdict=supervisor_verdict,
        )
    corpus_result = run_evolve_corpus(paths.blue_root).to_dict()
    supervisor_verdict["evolve_corpus"] = corpus_result
    if not bool(corpus_result.get("ok")):
        raise _PromotionRejected(
            f"blue evolve corpus rejected promotion: {_evolve_corpus_rejection_reason(corpus_result)}",
            supervisor_verdict=supervisor_verdict,
        )
    backup = promote_green_delta_to_blue(paths, changed_files, stop_port=int(stop_port))
    return backup, supervisor_verdict


def _is_test_infra_path(rel: str) -> bool:
    norm = _normalize_relpath(rel)
    name = Path(norm).name
    return norm.startswith("tests/") or name in {"conftest.py", "pytest.ini"}


def _is_loop_package_new_py(rel: str) -> bool:
    norm = _normalize_relpath(rel)
    return norm.startswith("thomas/forge/anvil/") and norm.endswith(".py")


def _is_loop_package_py(rel: str) -> bool:
    norm = _normalize_relpath(rel)
    return norm.startswith("thomas/forge/anvil/") and norm.endswith(".py")


def _is_green_support_path(rel: str) -> bool:
    norm = _normalize_relpath(rel)
    if norm in {_normalize_relpath(item) for item in _GREEN_SUPPORT_FILES}:
        return True
    return any(norm.startswith(_normalize_relpath(dirname).rstrip("/") + "/") for dirname in _GREEN_SUPPORT_DIRS)


def _session_rejection_reasons(delta: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    test_infra = sorted(rel for rel in (delta.get("changed_files") or []) if _is_test_infra_path(str(rel)))
    if test_infra:
        reasons.append("test infrastructure changed: " + ", ".join(test_infra[:8]))
    support_changed = sorted(rel for rel in (delta.get("changed_files") or []) if _is_green_support_path(str(rel)))
    if support_changed:
        reasons.append("green support file changed before supervisor exists: " + ", ".join(support_changed[:8]))
    loop_new = sorted(rel for rel in (delta.get("added") or []) if _is_loop_package_new_py(str(rel)))
    if loop_new:
        reasons.append("new evolve-loop Python file created: " + ", ".join(loop_new[:8]))
    return reasons


def _session_status(
    pass_results: list[dict[str, Any]],
    verification: list[dict[str, Any]],
    changed_count: int,
    promoted: bool,
    *,
    policy_violations: list[str] | None = None,
    session_rejections: list[str] | None = None,
    verification_floor_failures: list[str] | None = None,
) -> str:
    if any(int(item.get("returncode") or 0) != 0 for item in pass_results):
        return "agent_failed"
    if policy_violations:
        return "policy_violation"
    if session_rejections:
        return "rejected"
    if verification_floor_failures:
        return "verification_failed"
    if any(_verification_result_blocks_promotion(item) for item in verification):
        return "verification_failed"
    if changed_count <= 0:
        return "no_change"
    if not verification:
        return "unverified"
    if promoted:
        return "promoted"
    return "ready"


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
        except Exception as exc:  # noqa: BLE001 - fallback is best-effort; never crash the session
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
