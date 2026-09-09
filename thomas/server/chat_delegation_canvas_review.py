"""Structured, fail-closed semantic review for generated Canvas HTML."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from thomas.server.chat_delegation_canvas_review_document import parse_canvas_document
from thomas.server.chat_delegation_canvas_review_scripts import (
    disappearing_animations,
    suspicious_script_mutations,
)

REVIEW_VERSION = "canvas-structural-v3"


@dataclass(frozen=True)
class CanvasReviewIssue:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


@dataclass(frozen=True)
class CanvasReviewCheck:
    check_id: str
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"check_id": self.check_id, "passed": self.passed, "details": dict(self.details)}


@dataclass(frozen=True)
class CanvasReviewEvidence:
    status: str
    source_sha256: str
    review_version: str
    checks: tuple[CanvasReviewCheck, ...]
    issues: tuple[CanvasReviewIssue, ...]
    visible_tokens: tuple[str, ...]
    stable_tokens: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "passed" and not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "source_sha256": self.source_sha256,
            "review_version": self.review_version,
            "checks": [check.to_dict() for check in self.checks],
            "issues": [issue.to_dict() for issue in self.issues],
            "visible_tokens": list(self.visible_tokens),
            "stable_tokens": list(self.stable_tokens),
        }


def conforms_to_contract(html: str) -> bool:
    """Return whether a document carries the minimum live-reveal contract."""

    source = str(html or "")
    return bool(
        "tc-stage" in source
        and ('data-reveal="pending"' in source or "data-reveal='pending'" in source)
        and "--i" in source
    )


def review_canvas_html(prompt: str, html: str) -> CanvasReviewEvidence:
    """Validate actual Canvas structure without interpreting request semantics."""

    # Compatibility-only.  The frontier model owns what the request means and
    # emits the Canvas content.  This gate validates the resulting document; it
    # does not compare prompt words with output words or choose a visual type.
    del prompt

    source = str(html or "").strip()
    source_hash = hashlib.sha256(source.encode("utf-8", errors="replace")).hexdigest()
    checks: list[CanvasReviewCheck] = []
    issues: list[CanvasReviewIssue] = []

    contract_ok = conforms_to_contract(source)
    checks.append(CanvasReviewCheck("render_contract", contract_ok))
    if not contract_ok:
        issues.append(CanvasReviewIssue("contract_incomplete", "render contract is incomplete"))

    try:
        document = parse_canvas_document(source)
    except (TypeError, ValueError, RuntimeError) as exc:
        checks.append(CanvasReviewCheck("document_parse", False, {"error": type(exc).__name__}))
        issues.append(CanvasReviewIssue("document_parse_failed", "render could not be reviewed safely"))
        return CanvasReviewEvidence(
            status="failed",
            source_sha256=source_hash,
            review_version=REVIEW_VERSION,
            checks=tuple(checks),
            issues=tuple(issues),
            visible_tokens=(),
            stable_tokens=(),
        )

    checks.append(
        CanvasReviewCheck(
            "document_parse",
            True,
            {"element_count": len(document.elements), "has_graphical_content": document.has_graphical_content},
        )
    )
    enough_content = len(document.visible_text) >= 3 or document.has_graphical_content
    checks.append(
        CanvasReviewCheck("visible_content", enough_content, {"visible_characters": len(document.visible_text)})
    )
    if not enough_content:
        issues.append(CanvasReviewIssue("visible_content_missing", "render has too little visible content"))

    visible_tokens = document.visible_tokens
    stable_tokens = document.stable_tokens
    mutations = suspicious_script_mutations(source, document)
    checks.append(CanvasReviewCheck("content_mutation", not mutations, {"findings": mutations[:8]}))
    if mutations:
        issues.append(
            CanvasReviewIssue(
                "content_mutation",
                "render can hide or remove stable content after review",
                {"findings": mutations[:8]},
            )
        )

    disappearing = disappearing_animations(source, document)
    checks.append(CanvasReviewCheck("content_animation", not disappearing, {"findings": disappearing[:8]}))
    if disappearing:
        issues.append(
            CanvasReviewIssue(
                "content_disappears",
                "render animation finishes with stable content hidden",
                {"findings": disappearing[:8]},
            )
        )

    return CanvasReviewEvidence(
        status="passed" if not issues else "failed",
        source_sha256=source_hash,
        review_version=REVIEW_VERSION,
        checks=tuple(checks),
        issues=tuple(issues),
        visible_tokens=tuple(sorted(visible_tokens)),
        stable_tokens=tuple(sorted(stable_tokens)),
    )


def canvas_review_issues(prompt: str, html: str) -> list[str]:
    """Compatibility API for existing Canvas workers that only consume messages."""

    return [issue.message for issue in review_canvas_html(prompt, html).issues]


canvas_review_evidence = review_canvas_html


__all__ = [
    "CanvasReviewCheck",
    "CanvasReviewEvidence",
    "CanvasReviewIssue",
    "canvas_review_evidence",
    "canvas_review_issues",
    "conforms_to_contract",
    "review_canvas_html",
]
