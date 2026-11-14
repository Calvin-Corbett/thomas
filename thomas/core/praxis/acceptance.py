"""Fail-closed acceptance settlement for Praxis Build runs.

The runner supplies verifier receipts; a builder's prose is never a verdict.
This module evaluates identities, citations, completeness, and report delivery,
without executing model-authored commands or treating transport failures as work.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

CHECK_KINDS = frozenset(
    {
        "project_test_command",
        "file_exists",
        "file_contains",
        "render_html",
        "lint",
        "pdf_opens",
        "image_dimensions",
        "custom_command",
    }
)
PASS = "pass"
FAIL = "fail"
UNVERIFIED = "unverified"


def _normalized(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _cited(quote: object, instructions: str) -> bool:
    text = _normalized(quote)
    return bool(text) and text in _normalized(instructions)


def _evidence(receipt: Mapping[str, Any]) -> bool:
    """Require a verifiable artifact reference and an observed check outcome."""
    ref = receipt.get("evidence_ref")
    return (
        isinstance(ref, str)
        and bool(ref.strip())
        and receipt.get("source") == "verifier"
        and receipt.get("status") in {PASS, FAIL}
    )


def evaluate_acceptance(
    checks: Sequence[Mapping[str, Any]],
    receipts: Sequence[Mapping[str, Any]],
    *,
    instructions: str,
    child_rows: Sequence[Mapping[str, Any]] = (),
    observed_evidence_refs: Sequence[str] = (),
    require_child_reports: bool = True,
) -> dict[str, Any]:
    """Settle one frozen acceptance list against observed verifier receipts.

    Each receipt must name the exact check id and kind, cite a stored evidence
    artifact, and say whether that independent check passed or failed. Duplicate
    or conflicting receipts cannot make a check pass. A missing citation or
    incomplete evaluation remains unverified. Explicit failures are distinct
    from infrastructure and evaluation gaps, matching the experiment's routing.
    """
    declared: list[dict[str, Any]] = []
    ids: list[str] = []
    for index, check in enumerate(checks):
        check_id = str(check.get("id") or f"check_{index + 1}").strip()
        kind = str(check.get("kind") or "").strip()
        cited = _cited(check.get("cites"), instructions)
        ids.append(check_id)
        declared.append({"id": check_id, "kind": kind, "text": str(check.get("text") or ""), "cited": cited})
    duplicate_ids = {check_id for check_id, count in Counter(ids).items() if count > 1}

    receipts_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for receipt in receipts:
        receipts_by_id.setdefault(str(receipt.get("check_id") or ""), []).append(receipt)

    items: list[dict[str, Any]] = []
    for check in declared:
        check_id = check["id"]
        kind = check["kind"]
        matching = receipts_by_id.get(check_id, [])
        reasons: list[str] = []
        if not check_id or check_id in duplicate_ids:
            reasons.append("duplicate_or_missing_id")
        if kind not in CHECK_KINDS:
            reasons.append("unknown_check_kind")
        if not check["cited"]:
            reasons.append("uncited_check")
        if not check["text"].strip():
            reasons.append("empty_check")
        if not matching:
            reasons.append("missing_verifier_receipt")
        elif len(matching) != 1:
            reasons.append("ambiguous_verifier_receipts")
        elif matching[0].get("kind") != kind:
            reasons.append("check_kind_mismatch")
        elif not _evidence(matching[0]):
            reasons.append("missing_verifier_evidence")
        receipt = matching[0] if len(matching) == 1 else {}
        status = UNVERIFIED if reasons else str(receipt["status"])
        items.append(
            {
                **check,
                "status": status,
                "evidence_ref": receipt.get("evidence_ref") if not reasons else None,
                "reasons": reasons,
            }
        )

    known_refs = {str(ref) for ref in observed_evidence_refs if str(ref).strip()}
    known_refs.update(str(item["evidence_ref"]) for item in items if item["evidence_ref"])
    reports: list[dict[str, Any]] = []
    seen_agents: set[str] = set()
    for child in child_rows:
        agent_id = str(child.get("agent_id") or "")
        issues: list[str] = []
        if not agent_id or agent_id in seen_agents:
            issues.append("duplicate_or_missing_agent")
        seen_agents.add(agent_id)
        if child.get("state") != "completed":
            issues.append("child_not_completed")
        report = child.get("report")
        if not isinstance(report, Mapping):
            issues.append("missing_report")
            report = {}
        if not str(report.get("text") or "").strip():
            issues.append("empty_report")
        refs = report.get("evidence_refs")
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            issues.append("uncited_report")
        elif any(ref not in known_refs for ref in refs):
            issues.append("unobserved_report_evidence")
        reports.append({"agent_id": agent_id, "status": PASS if not issues else UNVERIFIED, "reasons": issues})

    if not checks:
        state = "completed_unverified"
    elif any(item["status"] == FAIL for item in items):
        state = "failed"
    elif all(item["status"] == PASS for item in items) and (
        not require_child_reports or (bool(reports) and all(row["status"] == PASS for row in reports))
    ):
        state = "completed"
    else:
        state = "completed_unverified"
    return {
        "state": state,
        "acceptance": items,
        "reports": reports,
        "passed": sum(item["status"] == PASS for item in items),
        "total": len(items),
        "unmatched_receipt_ids": sorted(set(receipts_by_id) - set(ids)),
    }


__all__ = ["CHECK_KINDS", "evaluate_acceptance"]
