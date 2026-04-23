"""Cross-document pattern detection and timeline building.

After all documents are analyzed, synthesizer looks across all claims to find
recurring patterns, builds a chronological timeline, and computes pattern
strength scores (deterministic, no LLM needed for scoring).
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from thomas.marketplace.investigation.prompts import (
    PATTERN_SYNTHESIS_SYSTEM,
    PATTERN_SYNTHESIS_USER,
    TIMELINE_SYNTHESIS_SYSTEM,
    TIMELINE_SYNTHESIS_USER,
)
from thomas.marketplace.investigation.store import InvestigationStore, Pattern, TimelineEvent

log = logging.getLogger(__name__)


@dataclass
class SynthesisResult:
    patterns_found: int = 0
    timeline_events: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Pattern strength scoring (deterministic, no LLM)
# ---------------------------------------------------------------------------


def compute_pattern_strength(
    evidence_count: int,
    avg_severity: float,
    date_span_days: int | None,
    avg_confidence: float,
) -> float:
    """Compute pattern strength from evidence metrics.

    - evidence_count: more evidence = stronger (log scale)
    - avg_severity: higher severity claims = more significant
    - date_span_days: consistent patterns over time score higher
    - avg_confidence: higher LLM confidence = more reliable
    """
    count_factor = math.log2(max(1, evidence_count) + 1)
    severity_weight = 0.5 + (avg_severity / 5.0) * 1.5  # 0.5 to 2.0

    if date_span_days is not None and date_span_days > 0:
        frequency = evidence_count / max(1, date_span_days / 30)
        frequency_factor = min(2.0, 0.5 + frequency * 0.3)
    else:
        frequency_factor = 1.0

    confidence_weight = 0.6 + (avg_confidence * 0.4)  # 0.6 to 1.0

    return round(count_factor * severity_weight * frequency_factor * confidence_weight, 3)


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------


class InvestigationSynthesizer:
    """Detect patterns across claims and build timeline."""

    def __init__(
        self,
        store: InvestigationStore,
        *,
        max_claims_per_synthesis: int = 300,
    ):
        self.store = store
        self.max_claims = max_claims_per_synthesis

    async def run_full_synthesis(
        self,
        case_id: str,
        llm_call: Callable,
    ) -> SynthesisResult:
        """Run pattern detection + timeline building."""
        result = SynthesisResult()

        try:
            # Clear old synthesis results before re-running
            self.store.clear_patterns(case_id)
            self.store.clear_timeline(case_id)

            # Pattern detection
            patterns_count = await self._synthesize_patterns(case_id, llm_call)
            result.patterns_found = patterns_count

            # Timeline building
            timeline_count = await self._build_timeline(case_id, llm_call)
            result.timeline_events = timeline_count

        except Exception as exc:
            log.error("Synthesis failed for case %s: %s", case_id[:8], exc)
            result.error = str(exc)

        return result

    # -- Pattern synthesis ---------------------------------------------------

    async def _synthesize_patterns(self, case_id: str, llm_call: Callable) -> int:
        claims = self.store.get_claims(case_id, limit=self.max_claims)
        if not claims:
            return 0

        # Group by category for the prompt
        by_category: dict[str, list[dict[str, Any]]] = {}
        for c in claims:
            cat = c.get("category", "other")
            by_category.setdefault(cat, []).append(c)

        formatted = self._format_claims_by_category(by_category)

        prompt = PATTERN_SYNTHESIS_USER.format(
            count=len(claims),
            claims_by_category=formatted,
        )

        response = await llm_call(
            system=PATTERN_SYNTHESIS_SYSTEM,
            prompt=prompt,
        )

        raw_patterns = self._parse_json_array(response)
        count = 0

        for rp in raw_patterns:
            claim_ids = rp.get("claim_ids", [])
            if not isinstance(claim_ids, list):
                claim_ids = []

            # Compute strength from actual claim data
            evidence_claims = [c for c in claims if c.get("id") in claim_ids]
            if not evidence_claims:
                evidence_claims = [c for c in claims][:1]  # fallback

            avg_severity = (
                sum(c.get("severity", 0) for c in evidence_claims) / len(evidence_claims) if evidence_claims else 0
            )
            avg_confidence = (
                sum(c.get("confidence", 0.7) for c in evidence_claims) / len(evidence_claims)
                if evidence_claims
                else 0.7
            )

            # Date span
            dates = [c.get("date_referenced") for c in evidence_claims if c.get("date_referenced")]
            date_span = self._date_span_days(dates) if dates else None
            first_seen = min(dates) if dates else rp.get("first_seen")
            last_seen = max(dates) if dates else rp.get("last_seen")

            strength = compute_pattern_strength(
                evidence_count=len(claim_ids) or len(evidence_claims),
                avg_severity=avg_severity,
                date_span_days=date_span,
                avg_confidence=avg_confidence,
            )

            pattern = Pattern(
                case_id=case_id,
                pattern_text=rp.get("pattern_text", ""),
                category=rp.get("category", "other"),
                evidence_count=len(claim_ids),
                claim_ids=claim_ids,
                first_seen=first_seen,
                last_seen=last_seen,
                strength=strength,
            )
            if pattern.pattern_text.strip():
                self.store.add_pattern(pattern)
                count += 1

        return count

    # -- Timeline building ---------------------------------------------------

    async def _build_timeline(self, case_id: str, llm_call: Callable) -> int:
        # Get all claims with dates
        all_claims = self.store.get_claims(case_id, limit=self.max_claims)
        dated_claims = [c for c in all_claims if c.get("date_referenced")]

        if not dated_claims:
            return 0

        # Sort by date
        dated_claims.sort(key=lambda c: c.get("date_referenced", ""))

        formatted = self._format_dated_claims(dated_claims)

        prompt = TIMELINE_SYNTHESIS_USER.format(dated_claims=formatted)

        response = await llm_call(
            system=TIMELINE_SYNTHESIS_SYSTEM,
            prompt=prompt,
        )

        raw_events = self._parse_json_array(response)
        count = 0

        for re_ in raw_events:
            event = TimelineEvent(
                case_id=case_id,
                event_date=re_.get("event_date", ""),
                event_summary=re_.get("event_summary", ""),
                category=re_.get("category"),
                doc_ids=re_.get("doc_ids", []),
                claim_ids=re_.get("claim_ids", []),
                severity=int(re_.get("severity", 0)),
            )
            if event.event_date and event.event_summary:
                self.store.add_timeline_event(event)
                count += 1

        return count

    # -- Formatting helpers --------------------------------------------------

    @staticmethod
    def _format_claims_by_category(by_category: dict[str, list[dict[str, Any]]]) -> str:
        parts: list[str] = []
        for cat, claims in sorted(by_category.items()):
            parts.append(f"\n### {cat.upper()} ({len(claims)} claims)")
            for c in claims:
                date_str = f" [{c.get('date_referenced', '?')}]" if c.get("date_referenced") else ""
                parts.append(
                    f"  ID={c['id']}{date_str} severity={c.get('severity', 0)}: " f"{c.get('claim_text', '')[:200]}"
                )
        return "\n".join(parts)

    @staticmethod
    def _format_dated_claims(claims: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for c in claims:
            lines.append(
                f"ID={c['id']} date={c.get('date_referenced', '?')} "
                f"category={c.get('category', '?')} severity={c.get('severity', 0)}: "
                f"{c.get('claim_text', '')[:200]}"
            )
        return "\n".join(lines)

    @staticmethod
    def _date_span_days(dates: list[str]) -> int | None:
        """Compute days between earliest and latest ISO date strings."""
        from datetime import datetime

        valid = []
        for d in dates:
            try:
                valid.append(datetime.fromisoformat(d))
            except (ValueError, TypeError):
                continue
        if len(valid) < 2:
            return None
        return (max(valid) - min(valid)).days

    @staticmethod
    def _parse_json_array(response: str) -> list[dict[str, Any]]:
        """Parse JSON array from LLM response, robust to extra text."""
        if not response:
            return []

        try:
            data = json.loads(response)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        match = re.search(r"\[.*\]", response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        return []
