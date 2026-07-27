"""Deterministic verification of artifacts and structured tool receipts.

This module intentionally does not parse a user's request or a worker's prose.
The model owns task semantics; verification owns only observable files and tool
results.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_RECOVERABLE_READ_TOOLS = {"fs.read_file", "fs_read_file", "fs.list_dir", "fs_list_dir"}
_OPTIONAL_ENRICHMENT_TOOLS = {"create_skill", "skills.create", "skill.create"}


def _hidden_completion_review_passes(
    prompt: str,
    work_dir: Path | None,
    created_files: list[str],
    summary: str,
    verified_candidate: bool,
    failed_tools: list[str],
    *,
    succeeded_tools: list[str] | None = None,
) -> bool:
    """Review only actual file/readback/tool evidence before completion."""

    del prompt
    root = work_dir.resolve() if work_dir is not None else None
    missing_or_empty: list[str] = []
    for relative in created_files:
        candidate = (root / relative).resolve() if root is not None else None
        if candidate is None:
            missing_or_empty.append(str(relative))
            continue
        try:
            candidate.relative_to(root)
        except ValueError:
            missing_or_empty.append(str(relative))
            continue
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            missing_or_empty.append(str(relative))

    succeeded = {str(tool) for tool in (succeeded_tools or []) if str(tool)}
    recovered_reads = (
        succeeded.intersection(_RECOVERABLE_READ_TOOLS)
        if created_files and not missing_or_empty
        else set()
    )
    optional_failures = _OPTIONAL_ENRICHMENT_TOOLS if created_files and not missing_or_empty else set()
    unrecovered_failures = [
        str(tool)
        for tool in failed_tools
        if str(tool) and str(tool) not in recovered_reads and str(tool) not in optional_failures
    ]
    evidence: dict[str, Any] = {
        "summary": str(summary or ""),
        "created_files": list(created_files),
        "failed_tools": list(failed_tools),
        "unrecovered_failed_tools": unrecovered_failures,
        "missing_or_empty": missing_or_empty,
    }

    from thomas.marketplace.orchestrator import adversarial_review

    def _score(_work: Any, _rubric: dict[str, Any], lens: str) -> float:
        if not verified_candidate or unrecovered_failures or missing_or_empty or not str(summary or "").strip():
            return 0.0
        return 9.0 if lens in {"correctness", "completeness", "robustness"} else 8.0

    review = adversarial_review.review_deliverable(
        evidence,
        {"verified": bool(verified_candidate), "artifact_count": len(created_files)},
        scorer=_score,
        budget_ok=True,
    )
    return bool(review.passed)


__all__ = ["_hidden_completion_review_passes"]
