"""Threat model cadence checks for security maturity."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

_RE_LAST_REVIEWED = re.compile(r"last\s+reviewed\s*:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)



def _parse_date(raw: str) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        dt = datetime.strptime(text, "%Y-%m-%d")
    except Exception:
        return None
    return dt.replace(tzinfo=UTC)



def evaluate_threat_model_cadence(path: Path, *, max_age_days: int = 14) -> Dict[str, Any]:
    max_days = max(1, int(max_age_days))
    errors = []
    warnings = []

    if not path.exists():
        errors.append(
            {
                "code": "threat_model.missing",
                "message": f"Threat model file not found: {path}",
                "remediation": "Create/update the threat model document and commit it.",
            }
        )
        return {
            "ok": False,
            "path": str(path),
            "errors": errors,
            "warnings": warnings,
            "summary": {"error_count": len(errors), "warning_count": len(warnings)},
        }

    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    age_days = (datetime.now(UTC) - modified).total_seconds() / 86400.0
    if age_days > float(max_days):
        errors.append(
            {
                "code": "threat_model.stale_file_mtime",
                "message": f"Threat model file is stale ({age_days:.1f} days old, limit {max_days}).",
                "remediation": "Review/update threat model and commit a fresh revision.",
            }
        )

    text = path.read_text(encoding="utf-8", errors="ignore")
    match = _RE_LAST_REVIEWED.search(text)
    reviewed_iso = ""
    if match:
        reviewed_iso = str(match.group(1) or "").strip()
        reviewed_dt = _parse_date(reviewed_iso)
        if reviewed_dt is None:
            warnings.append(
                {
                    "code": "threat_model.last_reviewed_invalid",
                    "message": f"Invalid Last reviewed date format: {reviewed_iso}",
                    "remediation": "Use `Last reviewed: YYYY-MM-DD`.",
                }
            )
        else:
            reviewed_age = (datetime.now(UTC) - reviewed_dt).total_seconds() / 86400.0
            if reviewed_age > float(max_days):
                errors.append(
                    {
                        "code": "threat_model.last_reviewed_stale",
                        "message": f"Last reviewed date is stale ({reviewed_age:.1f} days old, limit {max_days}).",
                        "remediation": "Update threat model review and set a fresh Last reviewed date.",
                    }
                )
    else:
        warnings.append(
            {
                "code": "threat_model.last_reviewed_missing",
                "message": "Threat model does not include `Last reviewed: YYYY-MM-DD`.",
                "remediation": "Add an explicit review date to support cadence checks.",
            }
        )

    return {
        "ok": len(errors) == 0,
        "path": str(path),
        "max_age_days": max_days,
        "file_age_days": round(age_days, 3),
        "last_reviewed": reviewed_iso,
        "errors": errors,
        "warnings": warnings,
        "summary": {"error_count": len(errors), "warning_count": len(warnings)},
    }
