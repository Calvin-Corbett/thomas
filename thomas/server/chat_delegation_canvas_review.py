"""Structured, fail-closed semantic review for generated Canvas HTML."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from thomas.server.chat_delegation_canvas_review_document import parse_canvas_document
from thomas.server.chat_delegation_canvas_review_rules import (
    GENERIC_PLACEHOLDER_RE,
    chart_prompt_pairs,
    is_chart_request,
    tokenize_prompt,
)
from thomas.server.chat_delegation_canvas_review_scripts import (
    disappearing_animations,
    suspicious_script_mutations,
)

REVIEW_VERSION = "canvas-semantic-v2"


def _chart_pair_mismatches(prompt: str, stable_evidence: tuple[str, ...]) -> list[dict[str, Any]]:
    pairs = chart_prompt_pairs(prompt)
    if not pairs:
        return []
    tokens = [
        token.casefold() for chunk in stable_evidence for token in re.findall(r"\b[\w.-]+\b", str(chunk), re.UNICODE)
    ]
    labels = {label for label, _value in pairs}
    mismatches: list[dict[str, Any]] = []
    for label, expected in pairs:
        positions = [index for index, token in enumerate(tokens) if token == label]
        matched = False
        observed: set[str] = set()
        for position in positions:
            boundary = min(
                (index for index in range(position + 1, len(tokens)) if tokens[index] in labels),
                default=min(len(tokens), position + 8),
            )
            segment = tokens[position + 1 : boundary]
            observed.update(token for token in segment if any(character.isdigit() for character in token))
            if expected in segment:
                matched = True
                break
        if not matched:
            mismatches.append({"label": label, "expected": expected, "observed": sorted(observed)[:6]})
    return mismatches


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
    """Review final Canvas HTML and return durable evidence for presentation gates."""

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

    generic = bool(GENERIC_PLACEHOLDER_RE.search(document.visible_text))
    checks.append(CanvasReviewCheck("generic_placeholder", not generic))
    if generic:
        issues.append(CanvasReviewIssue("generic_placeholder", "render is a generic task placeholder"))

    prompt_tokens = tokenize_prompt(prompt)
    visible_tokens = document.visible_tokens
    stable_tokens = document.stable_tokens
    mutations = suspicious_script_mutations(source, document, prompt_tokens)
    checks.append(CanvasReviewCheck("requested_content_mutation", not mutations, {"findings": mutations[:8]}))
    if mutations:
        issues.append(
            CanvasReviewIssue(
                "requested_content_mutation",
                "render can hide or remove requested content after review",
                {"findings": mutations[:8]},
            )
        )

    disappearing = disappearing_animations(source, document, prompt_tokens)
    checks.append(CanvasReviewCheck("requested_content_animation", not disappearing, {"findings": disappearing[:8]}))
    if disappearing:
        issues.append(
            CanvasReviewIssue(
                "requested_content_disappears",
                "render animation finishes with requested content hidden",
                {"findings": disappearing[:8]},
            )
        )

    numeric_tokens = {token for token in prompt_tokens if any(character.isdigit() for character in token)}
    missing_numeric = sorted(numeric_tokens - stable_tokens)
    checks.append(
        CanvasReviewCheck(
            "requested_values",
            not missing_numeric,
            {"requested": sorted(numeric_tokens), "missing": missing_numeric[:12]},
        )
    )
    if missing_numeric:
        issues.append(
            CanvasReviewIssue(
                "requested_values_missing",
                "render is missing requested data labels: " + ", ".join(missing_numeric[:6]),
                {"missing": missing_numeric[:12]},
            )
        )

    visible_numbers = sorted(token for token in stable_tokens if any(character.isdigit() for character in token))
    # Require stable values when the user supplied values to preserve. A generic
    # request such as "draw a bar chart" may legitimately be satisfied by a
    # graphical plan whose geometry is the data; inventing labels in the review
    # gate would make valid deterministic previews fail closed for the wrong reason.
    chart_values_ok = not is_chart_request(prompt) or not numeric_tokens or bool(visible_numbers)
    checks.append(CanvasReviewCheck("chart_values", chart_values_ok, {"visible_values": visible_numbers[:20]}))
    if not chart_values_ok:
        issues.append(CanvasReviewIssue("chart_values_missing", "chart has no stable visible values or labels"))

    pair_mismatches = _chart_pair_mismatches(prompt, document.stable_evidence) if is_chart_request(prompt) else []
    checks.append(
        CanvasReviewCheck(
            "chart_label_value_semantics",
            not pair_mismatches,
            {"mismatches": pair_mismatches},
        )
    )
    if pair_mismatches:
        issues.append(
            CanvasReviewIssue(
                "chart_label_value_mismatch",
                "chart labels are not associated with their requested values",
                {"mismatches": pair_mismatches},
            )
        )

    semantic_tokens = prompt_tokens - numeric_tokens
    matched = semantic_tokens & stable_tokens
    required = min(2, max(1, (len(semantic_tokens) + 2) // 3)) if semantic_tokens else 0
    subject_ok = not semantic_tokens or len(matched) >= required
    checks.append(
        CanvasReviewCheck(
            "requested_subject",
            subject_ok,
            {"matched": sorted(matched), "required_match_count": required},
        )
    )
    if not subject_ok:
        issues.append(CanvasReviewIssue("subject_mismatch", "render does not match the requested subject"))

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
