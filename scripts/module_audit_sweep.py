#!/usr/bin/env python3
"""Record a full major-module audit sweep with issue capture."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Sequence

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from thomas._architecture import MODULES as ARCH_MODULES
from thomas.observability.module_audit import MAJOR_MODULES, default_registry_path, record_audit

try:
    from scripts import record_module_audit as record_cli
except Exception:  # pragma: no cover
    import record_module_audit as record_cli  # type: ignore


ROOT = Path(__file__).resolve().parent.parent


def _default_auditor() -> str:
    for key in ("THOMAS_AGENT_ID", "AGENT_ID", "THOMAS_AGENT_NAME", "AGENT_NAME"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    return "module-audit-sweep-bot"


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write module audit entries for every major module.")
    parser.add_argument("--auditor", default="", help="Auditor identity (default: env agent id/name).")
    parser.add_argument(
        "--registry",
        default=str(default_registry_path(ROOT)),
        help="Registry path (default: docs/ops/module_audit_log.json).",
    )
    parser.add_argument("--run-id", default="", help="Optional run id.")
    parser.add_argument(
        "--summary",
        default="24h module audit sweep from architecture debt map",
        help="Summary text for each entry.",
    )
    parser.add_argument(
        "--status-if-clean",
        default="pass",
        choices=["pass", "warn", "fail", "pending_review"],
        help="Status when module has no debt metadata (default: pass).",
    )
    parser.add_argument(
        "--status-if-debt",
        default="warn",
        choices=["pass", "warn", "fail", "pending_review"],
        help="Status when module has debt metadata (default: warn).",
    )
    parser.add_argument(
        "--with-changelog",
        action="store_true",
        help="Append changelog audit lines (off by default for sweep runs).",
    )
    parser.add_argument("--changelog", default="CHANGELOG.md", help="Changelog path relative to repo root.")
    parser.add_argument("--signing-key", default="", help="Optional signing key (overrides env).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    auditor = str(args.auditor or _default_auditor()).strip()
    if not auditor:
        message = "auditor is required"
        if args.json:
            print(
                json.dumps(
                    {"action": "module_audit_sweep", "ok": False, "error": message},
                    sort_keys=True,
                )
            )
        else:
            print("Module audit sweep: FAIL")
            print(f"- {message}")
        return 1

    registry_path = Path(args.registry).expanduser()
    if not registry_path.is_absolute():
        registry_path = (ROOT / registry_path).resolve()
    signing_key = str(args.signing_key or os.environ.get("THOMAS_AUDIT_SIGNING_KEY") or "").strip() or None
    changelog_path = (ROOT / args.changelog).resolve()

    entries: List[dict[str, object]] = []
    for module in MAJOR_MODULES:
        details = dict(ARCH_MODULES.get(module) or {})
        debt = str(details.get("debt") or "").strip()
        issues = [debt] if debt else []
        status = args.status_if_debt if issues else args.status_if_clean
        entry = record_audit(
            registry_path=registry_path,
            module=module,
            auditor=auditor,
            status=status,
            summary=args.summary,
            run_id=args.run_id,
            files_touched=[],
            file_hashes={},
            issues=issues,
            signing_key=signing_key,
        )
        if args.with_changelog:
            sig_short = str(entry.get("signature", ""))[:12]
            line = (
                f"- Module `thomas/{module}` audited by `{entry['auditor']}` on "
                f"{str(entry.get('audited_at', ''))[:10]} (status: {entry['status']}, sig: `{sig_short}`)."
            )
            record_cli.append_unreleased_audit_line(changelog_path, line)
        entries.append(
            {
                "module": module,
                "status": status,
                "issue_count": len(issues),
                "signature": str(entry.get("signature") or ""),
            }
        )

    payload = {
        "action": "module_audit_sweep",
        "ok": True,
        "auditor": auditor,
        "module_count": len(entries),
        "issue_module_count": len([item for item in entries if int(item["issue_count"]) > 0]),
        "registry": str(registry_path),
        "entries": entries,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Module audit sweep: PASS")
        print(f"- auditor: {auditor}")
        print(f"- modules audited: {len(entries)}")
        print(f"- modules with issues: {payload['issue_module_count']}")
        print(f"- registry: {registry_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
