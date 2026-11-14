"""The blue/green promotion machinery behind evolve.

The signed blue supervisor manifest and its validation, the protected paths and
the revert that restores them from blue, delta fingerprints and drift reasons,
profile resolution, the verification root, and the verified-delta promotion.
Split out of ``evolve.py`` on 2026-09-07 along the seam the seam finder named:
``evolve.py`` keeps the session entry points and re-imports every name here.
"""

from __future__ import annotations

import difflib
import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
from pathlib import Path
from typing import Any

import tomllib

from evolve_supervisor import run_evolve_corpus, run_verifier_panel
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
    promote_green_delta_to_blue,
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
from .evolve_verification import (
    MAX_BLAST_RADIUS_TEST_FILES as _MAX_BLAST_RADIUS_TEST_FILES,
)
from .evolve_verification import (
    _verification_result_blocks_promotion,
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


def _non_python_rejection(changed_files: list[str], session: dict[str, Any]) -> str:
    """Why a delta with non-Python files may not be promoted yet, or "" when it may."""
    non_python_files = _non_python_delta_files(changed_files)
    if not non_python_files or _has_passing_non_python_verifier(session):
        return ""
    preview = ", ".join(non_python_files[:8])
    return f"non-Python delta requires a dedicated passing non-Python verifier before promotion: {preview}"


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
