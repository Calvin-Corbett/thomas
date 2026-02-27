"""Mutating API route policy exception auditing."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app import create_app

DEFAULT_MANIFEST_RELATIVE_PATH = Path("docs/security/mutating_route_policy_exceptions.json")
DEFAULT_AUTHZ_POLICY = "require_api_access"
DEFAULT_CSRF_POLICY = "same_origin_browser_local_mode"


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _parse_iso_date(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None


def _route_key(method: Any, path: Any) -> tuple[str, str]:
    return (str(method or "").strip().upper(), str(path or "").strip())


def _load_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not path.exists():
        return {}, [
            {
                "code": "mutating_route_policy.manifest_missing",
                "message": f"Manifest not found at {path}",
                "remediation": "Create docs/security/mutating_route_policy_exceptions.json with explicit exception records.",
            }
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, [
            {
                "code": "mutating_route_policy.manifest_invalid_json",
                "message": f"Could not parse {path}: {type(exc).__name__}: {exc}",
                "remediation": "Fix JSON syntax in the mutating route policy exception manifest.",
            }
        ]
    if not isinstance(data, dict):
        return {}, [
            {
                "code": "mutating_route_policy.manifest_not_object",
                "message": "Manifest root must be a JSON object.",
                "remediation": "Wrap manifest content in a top-level JSON object.",
            }
        ]
    return data, []


def _load_policy_snapshot(repo_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    runtime_root = (repo_root / ".tmp" / "mutating_route_policy_audit").resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, Any]] = []
    try:
        cfg = AppConfig(
            models={"local": ModelConfig(name="local", model="dummy")},
            default_model="local",
            memory=MemoryConfig(root=str(runtime_root)),
            server=ServerConfig(access_mode="local"),
        )
        app = create_app(cfg)
    except Exception as exc:
        errors.append(
            {
                "code": "mutating_route_policy.snapshot_build_failed",
                "message": f"Could not build mutating route policy snapshot: {type(exc).__name__}: {exc}",
                "remediation": "Ensure server app creation succeeds before running policy audits.",
            }
        )
        return {}, errors

    snapshot: dict[str, Any] = {}
    memory_obj: Any = None
    for key, value in app.items():
        key_text = repr(key)
        if "mutating_route_policy_snapshot" in key_text and isinstance(value, dict):
            snapshot = dict(value)
        if ".memory" in key_text:
            memory_obj = value

    if memory_obj is not None and hasattr(memory_obj, "close"):
        try:
            memory_obj.close()
        except Exception:
            pass

    if not snapshot:
        errors.append(
            {
                "code": "mutating_route_policy.snapshot_missing",
                "message": "Server app did not expose a mutating route policy snapshot.",
                "remediation": "Verify APP_MUTATING_ROUTE_POLICY_SNAPSHOT initialization in thomas/server/app.py.",
            }
        )
    return snapshot, errors


def evaluate_mutating_route_policy_manifest(
    snapshot: dict[str, Any],
    manifest: dict[str, Any],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    now = today or _today_utc()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    payload = dict(snapshot or {})
    defaults_raw = payload.get("defaults")
    defaults = defaults_raw if isinstance(defaults_raw, dict) else {}
    default_authz = str(defaults.get("authz") or DEFAULT_AUTHZ_POLICY).strip()
    default_csrf = str(defaults.get("csrf") or DEFAULT_CSRF_POLICY).strip()

    policies = list(payload.get("policies") or [])
    route_map: dict[tuple[str, str], dict[str, Any]] = {}
    observed_exceptions: dict[tuple[str, str], dict[str, Any]] = {}
    for row in policies:
        if not isinstance(row, dict):
            continue
        method, path = _route_key(row.get("method"), row.get("path"))
        if not method or not path:
            continue
        route_map[(method, path)] = row
        authz = str(row.get("authz") or "").strip()
        csrf = str(row.get("csrf") or "").strip()
        if authz != default_authz or csrf != default_csrf:
            observed_exceptions[(method, path)] = {
                "method": method,
                "path": path,
                "authz": authz,
                "csrf": csrf,
            }

    manifest_payload = dict(manifest or {})
    manifest_defaults_raw = manifest_payload.get("defaults")
    manifest_defaults = manifest_defaults_raw if isinstance(manifest_defaults_raw, dict) else {}
    if manifest_defaults:
        manifest_authz = str(manifest_defaults.get("authz") or "").strip()
        manifest_csrf = str(manifest_defaults.get("csrf") or "").strip()
        if manifest_authz and manifest_authz != default_authz:
            errors.append(
                {
                    "code": "mutating_route_policy.defaults_authz_mismatch",
                    "message": (
                        f"Manifest default authz '{manifest_authz}' does not match runtime default '{default_authz}'."
                    ),
                    "remediation": "Update manifest defaults.authz to match runtime default policy.",
                }
            )
        if manifest_csrf and manifest_csrf != default_csrf:
            errors.append(
                {
                    "code": "mutating_route_policy.defaults_csrf_mismatch",
                    "message": (
                        f"Manifest default csrf '{manifest_csrf}' does not match runtime default '{default_csrf}'."
                    ),
                    "remediation": "Update manifest defaults.csrf to match runtime default policy.",
                }
            )

    exceptions_raw = manifest_payload.get("exceptions", [])
    if not isinstance(exceptions_raw, list):
        errors.append(
            {
                "code": "mutating_route_policy.manifest_exceptions_not_list",
                "message": "Manifest 'exceptions' must be a JSON array.",
                "remediation": "Set 'exceptions' to [] or an array of exception records.",
            }
        )
        exceptions_raw = []

    approved_keys: set[tuple[str, str]] = set()
    approved_exceptions: list[dict[str, Any]] = []

    for idx, row in enumerate(exceptions_raw):
        if not isinstance(row, dict):
            errors.append(
                {
                    "code": "mutating_route_policy.exception_not_object",
                    "message": f"Exception entry at index {idx} must be an object.",
                    "remediation": "Replace non-object exception entries with structured records.",
                }
            )
            continue

        method, path = _route_key(row.get("method"), row.get("path"))
        if not method or not path:
            errors.append(
                {
                    "code": "mutating_route_policy.exception_missing_route_key",
                    "message": f"Exception entry at index {idx} is missing method/path.",
                    "remediation": "Provide both 'method' and 'path' for every exception entry.",
                }
            )
            continue

        key = (method, path)
        approved_keys.add(key)
        route_policy = route_map.get(key)
        if route_policy is None:
            errors.append(
                {
                    "code": "mutating_route_policy.exception_route_missing",
                    "message": f"Exception {method} {path} does not map to any runtime mutating API route.",
                    "remediation": "Remove stale exception or fix method/path to the active route.",
                }
            )
            continue

        declared_authz = str(row.get("authz") or route_policy.get("authz") or default_authz).strip()
        declared_csrf = str(row.get("csrf") or route_policy.get("csrf") or default_csrf).strip()
        actual_authz = str(route_policy.get("authz") or "").strip()
        actual_csrf = str(route_policy.get("csrf") or "").strip()
        if declared_authz != actual_authz or declared_csrf != actual_csrf:
            errors.append(
                {
                    "code": "mutating_route_policy.exception_policy_mismatch",
                    "message": (
                        f"Exception {method} {path} does not match runtime policy "
                        f"(declared authz={declared_authz}, csrf={declared_csrf}; "
                        f"actual authz={actual_authz}, csrf={actual_csrf})."
                    ),
                    "remediation": "Update exception policy fields to match runtime or remove stale exception.",
                }
            )

        reason = str(row.get("reason") or "").strip()
        owner = str(row.get("owner") or "").strip()
        reviewed_on = _parse_iso_date(row.get("reviewed_on"))
        expires_on = _parse_iso_date(row.get("expires_on"))
        if not reason:
            errors.append(
                {
                    "code": "mutating_route_policy.exception_reason_missing",
                    "message": f"Exception {method} {path} is missing a reason.",
                    "remediation": "Document why this exception is necessary and what compensating controls exist.",
                }
            )
        if not owner:
            errors.append(
                {
                    "code": "mutating_route_policy.exception_owner_missing",
                    "message": f"Exception {method} {path} is missing an owner.",
                    "remediation": "Assign an accountable owner team or person for this exception.",
                }
            )
        if reviewed_on is None:
            errors.append(
                {
                    "code": "mutating_route_policy.exception_reviewed_on_invalid",
                    "message": f"Exception {method} {path} has invalid reviewed_on date.",
                    "remediation": "Use ISO date format YYYY-MM-DD for reviewed_on.",
                }
            )
        if expires_on is None:
            errors.append(
                {
                    "code": "mutating_route_policy.exception_expires_on_invalid",
                    "message": f"Exception {method} {path} has invalid expires_on date.",
                    "remediation": "Use ISO date format YYYY-MM-DD for expires_on.",
                }
            )
        elif expires_on < now:
            errors.append(
                {
                    "code": "mutating_route_policy.exception_expired",
                    "message": f"Exception {method} {path} expired on {expires_on.isoformat()}.",
                    "remediation": "Remove or renew the exception after policy review.",
                }
            )

        approved_exceptions.append(
            {
                "method": method,
                "path": path,
                "authz": declared_authz,
                "csrf": declared_csrf,
                "owner": owner,
                "reason": reason,
                "reviewed_on": reviewed_on.isoformat() if reviewed_on else "",
                "expires_on": expires_on.isoformat() if expires_on else "",
            }
        )

    for key, row in observed_exceptions.items():
        if key in approved_keys:
            continue
        errors.append(
            {
                "code": "mutating_route_policy.unapproved_exception",
                "message": f"Runtime policy exception detected without approval: {row['method']} {row['path']}.",
                "remediation": "Add a reviewed exception record to the manifest or remove the policy exception.",
            }
        )

    for key in sorted(approved_keys):
        if key in observed_exceptions:
            continue
        method, path = key
        warnings.append(
            {
                "code": "mutating_route_policy.stale_manifest_exception",
                "message": f"Approved exception {method} {path} is no longer present in runtime policy snapshot.",
                "remediation": "Remove stale exception entries from the manifest.",
            }
        )

    return {
        "ok": len(errors) == 0,
        "defaults": {
            "authz": default_authz,
            "csrf": default_csrf,
        },
        "summary": {
            "route_count": len(route_map),
            "observed_exception_count": len(observed_exceptions),
            "approved_exception_count": len(approved_keys),
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "observed_exceptions": list(observed_exceptions.values()),
        "approved_exceptions": approved_exceptions,
        "errors": errors,
        "warnings": warnings,
    }


def evaluate_mutating_route_policy_exceptions(
    repo_root: Path,
    *,
    manifest_path: Path | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    target_manifest = (manifest_path or (root / DEFAULT_MANIFEST_RELATIVE_PATH)).resolve()

    manifest_payload, manifest_errors = _load_manifest(target_manifest)
    snapshot_payload, snapshot_errors = _load_policy_snapshot(root)

    if manifest_errors or snapshot_errors:
        errors = [*manifest_errors, *snapshot_errors]
        return {
            "ok": False,
            "manifest_path": str(target_manifest),
            "summary": {
                "route_count": int(len(list((snapshot_payload or {}).get("policies") or []))),
                "observed_exception_count": 0,
                "approved_exception_count": 0,
                "error_count": len(errors),
                "warning_count": 0,
            },
            "errors": errors,
            "warnings": [],
            "observed_exceptions": [],
            "approved_exceptions": [],
        }

    report = evaluate_mutating_route_policy_manifest(snapshot_payload, manifest_payload, today=today)
    report["manifest_path"] = str(target_manifest)
    report["snapshot_generated_at_utc"] = str(snapshot_payload.get("generated_at_utc") or "")
    return report
