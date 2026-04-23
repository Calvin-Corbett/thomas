#!/usr/bin/env python3
"""Report module-audit freshness and findings coverage."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from thomas.marketplace.observability.module_audit import MAJOR_MODULES, default_registry_path, load_registry

ROOT = Path(__file__).resolve().parent.parent
READY_STATUSES = {"pass", "warn", "fail"}


def _parse_iso(raw: str) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize module-audit freshness and issue counts.")
    parser.add_argument(
        "--registry",
        default=str(default_registry_path(ROOT)),
        help="Path to module audit registry JSON (default: docs/ops/module_audit_log.json).",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=24.0,
        help="Freshness threshold in hours (default: 24).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if any module is missing/stale/invalid.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    registry_path = Path(args.registry).expanduser()
    if not registry_path.is_absolute():
        registry_path = (ROOT / registry_path).resolve()

    if args.max_age_hours <= 0:
        payload = {
            "action": "module_audit_status",
            "ok": False,
            "error": "--max-age-hours must be > 0",
            "registry": str(registry_path),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("Module audit status: FAIL")
            print("- --max-age-hours must be > 0")
        return 1

    registry = load_registry(registry_path)
    latest = dict(registry.get("latest_by_module") or {})
    now = datetime.now(timezone.utc)
    max_age_seconds = float(args.max_age_hours) * 3600.0

    modules: list[dict[str, object]] = []
    stale_modules: list[str] = []
    missing_modules: list[str] = []
    invalid_modules: list[str] = []
    total_issue_count = 0

    for module in MAJOR_MODULES:
        row = latest.get(module) if isinstance(latest, dict) else None
        if not isinstance(row, dict):
            missing_modules.append(module)
            modules.append({"module": module, "status": "missing", "ok": False, "issue_count": 0})
            continue

        status = str(row.get("status") or "").strip().lower()
        audited_at_raw = str(row.get("audited_at") or "").strip()
        audited_at = _parse_iso(audited_at_raw)
        issue_count = len([x for x in (row.get("issues") or []) if str(x).strip()])
        total_issue_count += issue_count

        age_hours = None
        ok = True
        if status not in READY_STATUSES:
            invalid_modules.append(module)
            ok = False
        if audited_at is None:
            invalid_modules.append(module)
            ok = False
        else:
            age_seconds = max(0.0, (now - audited_at).total_seconds())
            age_hours = round(age_seconds / 3600.0, 2)
            if age_seconds > max_age_seconds:
                stale_modules.append(module)
                ok = False

        modules.append(
            {
                "module": module,
                "status": status,
                "audited_at": audited_at_raw,
                "age_hours": age_hours,
                "issue_count": issue_count,
                "ok": ok,
            }
        )

    ok = not missing_modules and not stale_modules and not invalid_modules
    payload = {
        "action": "module_audit_status",
        "ok": ok,
        "strict": bool(args.strict),
        "max_age_hours": float(args.max_age_hours),
        "module_count": len(MAJOR_MODULES),
        "missing_count": len(missing_modules),
        "stale_count": len(stale_modules),
        "invalid_count": len(invalid_modules),
        "total_issue_count": total_issue_count,
        "missing_modules": missing_modules,
        "stale_modules": stale_modules,
        "invalid_modules": sorted(set(invalid_modules), key=str.lower),
        "modules": modules,
        "registry": str(registry_path),
    }

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        if ok:
            print("Module audit status: PASS")
        else:
            print("Module audit status: FAIL")
        print(
            f"- modules={len(MAJOR_MODULES)} stale={len(stale_modules)} "
            f"missing={len(missing_modules)} invalid={len(set(invalid_modules))} "
            f"issues={total_issue_count}"
        )

    if args.strict and not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
