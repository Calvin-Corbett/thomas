"""Runtime helpers for browser workflow profiles and corpus cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from thomas.browser.workflows import get_workflow_profile, list_workflow_profiles

WORKFLOW_CORPUS_ROOT = Path(__file__).resolve().parent / "workflow_corpus"


def list_profiles() -> list[dict[str, Any]]:
    return list_workflow_profiles()


def load_profile(profile_id: str) -> dict[str, Any] | None:
    return get_workflow_profile(profile_id)


def list_case_files(limit: int | None = None) -> list[Path]:
    files = sorted(WORKFLOW_CORPUS_ROOT.glob("case_*.json"))
    if limit is not None and limit >= 0:
        return files[: int(limit)]
    return files


def load_case(case_id: str) -> dict[str, Any]:
    needle = str(case_id or "").strip()
    if not needle:
        raise ValueError("case_id is required")

    if needle.endswith(".json") and needle.startswith("case_"):
        filename = needle
    elif needle.startswith("browser-workflow-"):
        suffix = needle.rsplit("-", 1)[-1]
        if not (len(suffix) == 4 and suffix.isdigit()):
            raise ValueError(f"invalid workflow_id format: {needle}")
        filename = f"case_{suffix}.json"
    elif needle.isdigit() and len(needle) == 4:
        filename = f"case_{needle}.json"
    else:
        raise ValueError(f"unsupported case identifier: {needle}")

    path = WORKFLOW_CORPUS_ROOT / filename
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"workflow case not found: {filename}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_case_payload(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return False, ["payload must be an object"]

    def _req_str(key: str) -> None:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{key} must be a non-empty string")

    _req_str("schema_version")
    _req_str("workflow_id")
    _req_str("category")
    _req_str("objective")

    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps must be a non-empty list")
    else:
        for idx, row in enumerate(steps, start=1):
            if not isinstance(row, dict):
                errors.append(f"steps[{idx}] must be an object")
                continue
            for key in ("action", "target"):
                value = row.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"steps[{idx}].{key} must be a non-empty string")

    assertions = payload.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        errors.append("assertions must be a non-empty list")

    return len(errors) == 0, errors


def validate_case_file(path: Path) -> tuple[bool, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return validate_case_payload(payload)


def validate_corpus(limit: int | None = None) -> dict[str, Any]:
    files = list_case_files(limit=limit)
    valid = 0
    invalid = 0
    issues: list[dict[str, Any]] = []
    for path in files:
        ok, errors = validate_case_file(path)
        if ok:
            valid += 1
        else:
            invalid += 1
            issues.append({"file": path.name, "errors": errors[:10]})
    return {
        "root": str(WORKFLOW_CORPUS_ROOT),
        "total": len(files),
        "valid": valid,
        "invalid": invalid,
        "issues": issues,
    }
