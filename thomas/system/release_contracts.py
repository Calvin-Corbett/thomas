"""Release contract registry checks for versioned compatibility discipline."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = ROOT / "docs" / "release" / "contract_registry.json"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
ALLOWED_STATUS = {"active", "deprecated", "sunset"}


@dataclass(frozen=True)
class ContractFinding:
    level: str
    code: str
    message: str
    remediation: str
    contract_id: str = ""

    def to_dict(self) -> Dict[str, str]:
        payload = {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
        }
        if self.contract_id:
            payload["contract_id"] = self.contract_id
        return payload


def _parse_iso_date(raw: Any) -> Optional[date]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None


def _safe_int(raw: Any, default: int) -> int:
    try:
        value = int(raw)
    except Exception:
        return int(default)
    return int(value)


def _read_registry(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Registry JSON must be an object.")
    return payload


def evaluate_release_contract_registry(
    registry: Dict[str, Any],
    *,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    now = today or datetime.now(UTC).date()
    findings: List[ContractFinding] = []

    policy = registry.get("policy")
    policy_dict = policy if isinstance(policy, dict) else {}
    min_notice_days = max(1, _safe_int(policy_dict.get("min_deprecation_notice_days"), 30))

    contracts_raw = registry.get("contracts")
    if not isinstance(contracts_raw, list):
        findings.append(
            ContractFinding(
                level="error",
                code="contracts.missing",
                message="Contract registry must include a `contracts` list.",
                remediation="Define versioned contract entries in `contracts`.",
            )
        )
        contracts_raw = []

    seen_ids: set[str] = set()
    normalized_contracts: List[Dict[str, Any]] = []

    for item in contracts_raw:
        if not isinstance(item, dict):
            findings.append(
                ContractFinding(
                    level="error",
                    code="contracts.invalid_entry",
                    message="Contract entry must be an object.",
                    remediation="Rewrite invalid entries as JSON objects.",
                )
            )
            continue

        contract_id = str(item.get("id") or "").strip()
        version = str(item.get("version") or "").strip()
        status = str(item.get("status") or "active").strip().lower()
        surface = str(item.get("surface") or "").strip()

        if not contract_id:
            findings.append(
                ContractFinding(
                    level="error",
                    code="contracts.id_missing",
                    message="Contract entry is missing `id`.",
                    remediation="Add a stable `id` for each contract.",
                )
            )
            continue
        if contract_id in seen_ids:
            findings.append(
                ContractFinding(
                    level="error",
                    code="contracts.duplicate_id",
                    message=f"Duplicate contract id `{contract_id}`.",
                    remediation="Keep one unique entry per contract id.",
                    contract_id=contract_id,
                )
            )
        seen_ids.add(contract_id)

        if not surface:
            findings.append(
                ContractFinding(
                    level="error",
                    code="contracts.surface_missing",
                    message=f"Contract `{contract_id}` is missing `surface`.",
                    remediation="Set `surface` to the API/SDK/runtime boundary this contract governs.",
                    contract_id=contract_id,
                )
            )

        if not SEMVER_RE.match(version):
            findings.append(
                ContractFinding(
                    level="error",
                    code="contracts.version_invalid",
                    message=f"Contract `{contract_id}` version `{version}` is not semver `X.Y.Z`.",
                    remediation="Use semantic version format (for example `1.2.0`).",
                    contract_id=contract_id,
                )
            )

        if status not in ALLOWED_STATUS:
            findings.append(
                ContractFinding(
                    level="error",
                    code="contracts.status_invalid",
                    message=f"Contract `{contract_id}` has unsupported status `{status}`.",
                    remediation="Use one of: active, deprecated, sunset.",
                    contract_id=contract_id,
                )
            )
            status = "active"

        deprecated_on_raw = str(item.get("deprecated_on") or "").strip()
        sunset_on_raw = str(item.get("sunset_on") or "").strip()
        deprecated_on = _parse_iso_date(deprecated_on_raw)
        sunset_on = _parse_iso_date(sunset_on_raw)

        if deprecated_on_raw and deprecated_on is None:
            findings.append(
                ContractFinding(
                    level="error",
                    code="contracts.deprecated_on_invalid",
                    message=f"Contract `{contract_id}` has invalid deprecated_on date `{deprecated_on_raw}`.",
                    remediation="Use `YYYY-MM-DD` for deprecated_on.",
                    contract_id=contract_id,
                )
            )

        if sunset_on_raw and sunset_on is None:
            findings.append(
                ContractFinding(
                    level="error",
                    code="contracts.sunset_on_invalid",
                    message=f"Contract `{contract_id}` has invalid sunset_on date `{sunset_on_raw}`.",
                    remediation="Use `YYYY-MM-DD` for sunset_on.",
                    contract_id=contract_id,
                )
            )

        if status == "deprecated":
            if deprecated_on is None:
                findings.append(
                    ContractFinding(
                        level="error",
                        code="contracts.deprecated_on_required",
                        message=f"Deprecated contract `{contract_id}` requires `deprecated_on`.",
                        remediation="Add `deprecated_on: YYYY-MM-DD`.",
                        contract_id=contract_id,
                    )
                )
            if sunset_on is None:
                findings.append(
                    ContractFinding(
                        level="error",
                        code="contracts.sunset_on_required",
                        message=f"Deprecated contract `{contract_id}` requires `sunset_on`.",
                        remediation="Add `sunset_on: YYYY-MM-DD`.",
                        contract_id=contract_id,
                    )
                )
            if deprecated_on is not None and sunset_on is not None:
                delta_days = (sunset_on - deprecated_on).days
                if delta_days < min_notice_days:
                    findings.append(
                        ContractFinding(
                            level="error",
                            code="contracts.notice_window_too_short",
                            message=(
                                f"Deprecated contract `{contract_id}` notice window is {delta_days} days "
                                f"(minimum {min_notice_days})."
                            ),
                            remediation="Push `sunset_on` out or increase notice period before removal.",
                            contract_id=contract_id,
                        )
                    )
                if sunset_on < now:
                    findings.append(
                        ContractFinding(
                            level="warning",
                            code="contracts.deprecated_past_sunset",
                            message=f"Deprecated contract `{contract_id}` is past sunset date.",
                            remediation="Remove it or move status to `sunset` explicitly.",
                            contract_id=contract_id,
                        )
                    )

        if status == "sunset" and sunset_on is None:
            findings.append(
                ContractFinding(
                    level="error",
                    code="contracts.sunset_requires_date",
                    message=f"Sunset contract `{contract_id}` requires `sunset_on`.",
                    remediation="Add `sunset_on: YYYY-MM-DD` for sunset contracts.",
                    contract_id=contract_id,
                )
            )

        if status == "active" and sunset_on is not None:
            findings.append(
                ContractFinding(
                    level="warning",
                    code="contracts.active_with_sunset",
                    message=f"Active contract `{contract_id}` defines `sunset_on`.",
                    remediation="Drop sunset date or move status to `deprecated`.",
                    contract_id=contract_id,
                )
            )

        normalized_contracts.append(
            {
                "id": contract_id,
                "surface": surface,
                "version": version,
                "status": status,
                "deprecated_on": deprecated_on_raw,
                "sunset_on": sunset_on_raw,
                "owner": str(item.get("owner") or "").strip(),
                "description": str(item.get("description") or "").strip(),
            }
        )

    migration_raw = registry.get("migration_guarantees")
    migration_rows: List[Dict[str, str]] = []
    if not isinstance(migration_raw, list) or not migration_raw:
        findings.append(
            ContractFinding(
                level="warning",
                code="migration_guarantees.missing",
                message="No migration guarantees are declared.",
                remediation="Declare migration guarantees and verification hooks.",
            )
        )
    else:
        for item in migration_raw:
            if not isinstance(item, dict):
                findings.append(
                    ContractFinding(
                        level="error",
                        code="migration_guarantees.invalid_entry",
                        message="Migration guarantee entry must be an object.",
                        remediation="Rewrite invalid guarantee entries as JSON objects.",
                    )
                )
                continue
            gid = str(item.get("id") or "").strip()
            guarantee = str(item.get("guarantee") or "").strip()
            verified_by = str(item.get("verified_by") or "").strip()
            if not gid or not guarantee:
                findings.append(
                    ContractFinding(
                        level="error",
                        code="migration_guarantees.required_fields_missing",
                        message="Migration guarantee requires `id` and `guarantee`.",
                        remediation="Fill both `id` and `guarantee`.",
                        contract_id=gid,
                    )
                )
            if not verified_by:
                findings.append(
                    ContractFinding(
                        level="warning",
                        code="migration_guarantees.unverified",
                        message=f"Migration guarantee `{gid or 'unknown'}` has no `verified_by` hook.",
                        remediation="Attach a script/test identifier under `verified_by`.",
                        contract_id=gid,
                    )
                )
            migration_rows.append(
                {
                    "id": gid,
                    "guarantee": guarantee,
                    "verified_by": verified_by,
                }
            )

    errors = [f.to_dict() for f in findings if f.level == "error"]
    warnings = [f.to_dict() for f in findings if f.level == "warning"]
    deprecated_count = sum(1 for row in normalized_contracts if row.get("status") == "deprecated")

    return {
        "ok": len(errors) == 0,
        "as_of": now.isoformat(),
        "policy": {
            "min_deprecation_notice_days": min_notice_days,
        },
        "contracts": normalized_contracts,
        "migration_guarantees": migration_rows,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "contract_count": len(normalized_contracts),
            "deprecated_count": deprecated_count,
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
    }


def build_release_contract_report(
    registry_path: Optional[Path] = None,
    *,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    path = (registry_path or DEFAULT_REGISTRY_PATH).resolve()
    if not path.exists():
        return {
            "ok": False,
            "registry_path": str(path),
            "as_of": (today or datetime.now(UTC).date()).isoformat(),
            "contracts": [],
            "migration_guarantees": [],
            "errors": [
                {
                    "level": "error",
                    "code": "registry.missing",
                    "message": f"Contract registry file not found: {path}",
                    "remediation": "Create docs/release/contract_registry.json.",
                }
            ],
            "warnings": [],
            "summary": {
                "contract_count": 0,
                "deprecated_count": 0,
                "error_count": 1,
                "warning_count": 0,
            },
            "policy": {"min_deprecation_notice_days": 30},
        }

    try:
        registry = _read_registry(path)
    except Exception as exc:
        return {
            "ok": False,
            "registry_path": str(path),
            "as_of": (today or datetime.now(UTC).date()).isoformat(),
            "contracts": [],
            "migration_guarantees": [],
            "errors": [
                {
                    "level": "error",
                    "code": "registry.invalid_json",
                    "message": f"Failed to parse contract registry: {type(exc).__name__}: {exc}",
                    "remediation": "Fix malformed JSON in contract registry.",
                }
            ],
            "warnings": [],
            "summary": {
                "contract_count": 0,
                "deprecated_count": 0,
                "error_count": 1,
                "warning_count": 0,
            },
            "policy": {"min_deprecation_notice_days": 30},
        }

    report = evaluate_release_contract_registry(registry, today=today)
    report["registry_path"] = str(path)
    return report


def _render_findings(lines: List[str], title: str, rows: Iterable[Dict[str, Any]]) -> None:
    entries = list(rows)
    if not entries:
        return
    lines.append("")
    lines.append(title)
    for row in entries:
        contract_id = str(row.get("contract_id") or "").strip()
        prefix = f"[{row.get('code', 'unknown')}] "
        if contract_id:
            prefix += f"{contract_id}: "
        lines.append(f"- {prefix}{row.get('message', '')}")
        lines.append(f"  Fix: {row.get('remediation', '')}")


def format_text_report(report: Dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        f"Contract registry: {report.get('registry_path', '')}",
        f"As of: {report.get('as_of', '')}",
        f"Result: {'OK' if report.get('ok') else 'FAILED'}",
        f"Contracts: {summary.get('contract_count', 0)}",
        f"Deprecated: {summary.get('deprecated_count', 0)}",
    ]
    _render_findings(lines, "Errors:", report.get("errors") if isinstance(report.get("errors"), list) else [])
    _render_findings(
        lines,
        "Warnings:",
        report.get("warnings") if isinstance(report.get("warnings"), list) else [],
    )
    if int(summary.get("error_count", 0) or 0) == 0 and int(summary.get("warning_count", 0) or 0) == 0:
        lines.append("")
        lines.append("No contract-discipline issues detected.")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate release contract registry and deprecation discipline.")
    parser.add_argument(
        "--path",
        dest="registry_path",
        default=str(DEFAULT_REGISTRY_PATH),
        help="Path to contract registry JSON.",
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON output.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any contract-discipline errors are present.",
    )
    args = parser.parse_args(argv)

    path = Path(args.registry_path).resolve()
    report = build_release_contract_report(path)
    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_text_report(report))

    if bool(args.strict) and not bool(report.get("ok")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
