"""Module-level audit registry helpers.

This registry tracks when each major module was last audited, by whom,
and with a tamper-evident signature chain.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

SCHEMA_VERSION = 1

# Major module buckets inside `thomas/`.
MAJOR_MODULES = (
    "agent",
    "autonomy",
    "core",
    "models",
    "policy",
    "realtime",
    "server",
    "tools",
    "observability",
    "memory",
    "notifications",
    "preferences",
    "intake",
    "vision",
    "watcher",
    "tray_agent",
    "demo",
)

VALID_AUDIT_STATUSES = frozenset({"pass", "warn", "fail", "pending_review"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_path(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def module_for_path(path: str) -> Optional[str]:
    """Map a changed file path to a major module name."""
    p = normalize_path(path)
    if not p.startswith("thomas/"):
        return None
    parts = p.split("/")
    if len(parts) < 3:
        return None
    module = parts[1]
    if module not in MAJOR_MODULES:
        return None
    return module


def touched_modules(changed_files: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for raw in changed_files:
        m = module_for_path(raw)
        if m:
            out.add(m)
    return out


def default_registry_path(repo_root: Path) -> Path:
    return repo_root / "docs" / "ops" / "module_audit_log.json"


def empty_registry() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now_iso(),
        "latest_by_module": {},
        "history": [],
    }


def load_registry(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return empty_registry()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return empty_registry()
    out = empty_registry()
    out.update(raw)
    if not isinstance(out.get("latest_by_module"), dict):
        out["latest_by_module"] = {}
    if not isinstance(out.get("history"), list):
        out["history"] = []
    return out


def save_registry(path: Path, registry: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _entry_payload_for_sig(entry: Dict[str, Any], prev_signature: str) -> bytes:
    payload = {
        "id": entry.get("id", ""),
        "module": entry.get("module", ""),
        "audited_at": entry.get("audited_at", ""),
        "auditor": entry.get("auditor", ""),
        "status": entry.get("status", ""),
        "summary": entry.get("summary", ""),
        "run_id": entry.get("run_id", ""),
        "files_touched": entry.get("files_touched", []),
        "prev_signature": prev_signature or "",
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sign_entry(entry: Dict[str, Any], *, prev_signature: str, signing_key: Optional[str]) -> str:
    payload = _entry_payload_for_sig(entry, prev_signature)
    if signing_key:
        return hmac.new(signing_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hashlib.sha256(payload).hexdigest()


def record_audit(
    *,
    registry_path: Path,
    module: str,
    auditor: str,
    status: str,
    summary: str,
    run_id: str = "",
    files_touched: Optional[Iterable[str]] = None,
    signing_key: Optional[str] = None,
) -> Dict[str, Any]:
    mod = str(module or "").strip()
    if mod not in MAJOR_MODULES:
        raise ValueError(f"unknown major module: {mod}")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in VALID_AUDIT_STATUSES:
        raise ValueError(f"invalid audit status: {status}")
    who = str(auditor or "").strip()
    if not who:
        raise ValueError("auditor is required")

    registry = load_registry(registry_path)
    latest = registry.get("latest_by_module", {}).get(mod) or {}
    prev_sig = str(latest.get("signature") or "")

    touched = sorted({normalize_path(p) for p in (files_touched or []) if normalize_path(p)})
    entry: Dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "module": mod,
        "audited_at": utc_now_iso(),
        "auditor": who,
        "status": normalized_status,
        "summary": str(summary or "").strip(),
        "run_id": str(run_id or "").strip(),
        "files_touched": touched,
        "prev_signature": prev_sig,
        "signature_scheme": "hmac-sha256" if signing_key else "sha256",
    }
    entry["signature"] = sign_entry(entry, prev_signature=prev_sig, signing_key=signing_key)

    history = list(registry.get("history") or [])
    history.append(entry)
    # Keep file bounded for long-lived repos.
    if len(history) > 5000:
        history = history[-5000:]

    latest_by_module = dict(registry.get("latest_by_module") or {})
    latest_by_module[mod] = entry

    registry["schema_version"] = SCHEMA_VERSION
    registry["updated_at"] = utc_now_iso()
    registry["latest_by_module"] = latest_by_module
    registry["history"] = history
    save_registry(registry_path, registry)
    return entry

