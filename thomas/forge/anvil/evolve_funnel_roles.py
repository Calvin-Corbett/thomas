"""Roles, prompts, anonymization, and the one-shot model-call adapter for the funnel.

Every funnel agent is FRESH / one-shot / memoryless and knows NOTHING about
Thomas: prompts are neutral ("You are an AI"), handoffs say only "an AI made
this", and each call builds its own client (so there is no shared context to
leak). The single memory-bearing agent is the green-mirror builder, which lives
in ``run_evolve_session`` and is invoked once per goal by the orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# A model call: (system_prompt, user_prompt, profile) -> response text.
# Injected everywhere so the orchestration is fully testable without a real LLM.
ModelCall = Callable[[str, str, str], str]

# ---------------------------------------------------------------------------
# Frozen grading epistemics (injected into every reviewer/synthesizer/evaluator).
# ---------------------------------------------------------------------------
GRADING_EPISTEMICS = (
    "Grading epistemics (non-negotiable):\n"
    "- Unique, correct, load-bearing catches beat length. A short artifact that finds real "
    "structural problems beats a long one restating the obvious. Length is NOT quality.\n"
    "- Convergence across independent sources is the truth signal: a point multiple isolated "
    "agents independently reach is most likely true; weight it accordingly.\n"
    "- Count over feeling: prefer the measured judgment (how many distinct, correct, "
    "load-bearing points) over what merely feels impressive.\n"
    "- Caretaking/aggression tax: effort spent softening, flattering, OR mocking is effort not "
    "spent on the artifact. Judge the artifact, not the author.\n"
    "- Force per point: a catch must land with a clear mechanism (why it fails), not a gesture."
)

_NEUTRAL = (
    "You are an AI. You know nothing about who built the material or what system it belongs to; "
    "judge or produce work purely on its merits, reasoning only from the text you are given. "
    "Always reply with ONE fenced ```json block and nothing after it."
)

SYS_DEFINITION_LANE = (
    _NEUTRAL + "\n\nYou are given a software-improvement goal. Independently produce YOUR reading "
    "of what SUCCESS means for it: the distinct facets a good result must satisfy (the underlying "
    "objective, observable success criteria, what failure looks like, completion conditions, and a "
    "back-check). Be complete; completeness is the job here, not brevity-for-its-own-sake.\n"
    'JSON shape: {"items": [{"text": "the facet", "rationale": "why it serves the goal"}]}'
)

SYS_RUBRIC_LANE = (
    _NEUTRAL + "\n\n" + GRADING_EPISTEMICS + "\n\nGiven a goal and a definition of success, produce "
    "concrete CHECKS that would prove the definition is met (executable tests where possible, else "
    "observable criteria). Mark each essential or secondary.\n"
    'JSON shape: {"items": [{"text": "the check", "how_to_test": "...", "essential": true}]}'
)

SYS_PRODUCT_LANE = (
    _NEUTRAL + "\n\nGiven a goal, a definition of success, and a rubric, produce an implementation "
    "PLAN: what to change, where, the edge cases, and how it will be verified. Do not write final "
    "code; produce the plan a builder will implement.\n"
    'JSON shape: {"plan": "the full plan as prose", "items": [{"text": "a distinct load-bearing plan element"}]}'
)

SYS_REVIEWER = (
    _NEUTRAL + "\n\n" + GRADING_EPISTEMICS + "\n\nAdversarially grade the artifact against the goal "
    "(and rubric if given). Score 0..1 for how well it serves the goal.\n"
    'JSON shape: {"score": 0.0, "pass": false, "weaknesses": ["mechanism of failure"], "reason": "one line"}'
)

SYS_SYNTH_UNION = (
    _NEUTRAL + "\n\n" + GRADING_EPISTEMICS + "\n\nYou are a synthesizer bound to the goal, not your "
    "own taste. UNION THE GOOD: keep EVERY distinct load-bearing element any input identified. Do "
    "NOT reduce to common ground and do NOT strip a unique-but-sound element. Drop an element ONLY "
    "if it is fabricated (does not serve the goal) or directly contradicts the goal or another "
    "element. A genuine contradiction about what 'good' means must be SURFACED (kept as conditional "
    "'X in context A, Y in context B', or flagged), never silently resolved.\n"
    'JSON shape: {"merged": "the merged artifact as prose", "kept_items": ["..."], '
    '"contradictions": [{"a": "...", "b": "...", "note": "..."}], "dropped": [{"text": "...", "why": "..."}]}'
)

SYS_SIMPLIFY = (
    _NEUTRAL + "\n\nYou look ONLY for needless weight. Identify elements that can be removed without "
    "losing a guarantee, an invariant, a gate, or a load-bearing mechanism. For each proposed cut, "
    "state exactly what is lost; if nothing load-bearing is lost, mark it a safe cut. Do not force "
    "cuts — if everything earns its place, return none.\n"
    'JSON shape: {"cuts": [{"text": "element to remove", "what_is_lost": "...", "safe": true}]}'
)

SYS_EVALUATOR = (
    _NEUTRAL + "\n\n" + GRADING_EPISTEMICS + "\n\nYou are a genuinely INDEPENDENT evaluator. You are "
    "given ONLY a goal and a final result — no reasoning, no internal scores, no context. "
    "Adversarially try to BREAK the result against the goal: find where it fails to actually achieve "
    "the goal. Be skeptical; do not flatter.\n"
    'JSON shape: {"broke_it": false, "verdict": "pass", "findings": ["..."], "reason": "one line"}'
)


def anonymize(artifact: str, action: str) -> str:
    """Frozen handoff wording. ``action`` e.g. 'Review', 'Synthesize', 'Refine'."""
    return (
        f"The following was produced by an AI. {action} it.\n\n"
        f"===== BEGIN ARTIFACT =====\n{artifact}\n===== END ARTIFACT ====="
    )


def parse_json_block(text: str) -> dict[str, Any] | None:
    """Tolerant JSON extraction from a model reply (fenced or outermost braces)."""
    raw = str(text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    else:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def parse_items(text: str) -> list[dict[str, Any]]:
    """Extract an ``items`` list from a lane reply; tolerant of malformed output."""
    obj = parse_json_block(text)
    if not obj:
        return []
    items = obj.get("items")
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict) and str(it.get("text", "")).strip():
            out.append(it)
        elif isinstance(it, str) and it.strip():
            out.append({"text": it.strip()})
    return out


_INJECTION_MARKERS: tuple[str, ...] = (
    "ignore previous",
    "ignore the rubric",
    "disregard",
    "system prompt",
    "you are now",
    "override",
    "skip the tests",
    "disable the tests",
    "bypass",
    "exfiltrate",
    "reveal your",
    "auto-merge",
    "auto merge",
    "skip review",
    "ignore safety",
)


def detect_injection_markers(text: str) -> list[str]:
    """Return sorted unique markers from ``_INJECTION_MARKERS`` found in *text*.

    The check is case-insensitive substring matching — a marker is reported
    whenever it appears anywhere inside the lowercased input.  Returns an empty
    list when no markers are present.

    This is a pure function with no side effects; safe to call on every lane
    reply before it is forwarded to the next agent.
    """
    lowered = text.lower()
    return sorted({m for m in _INJECTION_MARKERS if m in lowered})


class DefaultModelCall:
    """Production ``ModelCall``: a fresh, one-shot, credential-resolved LLM call.

    Builds a new client per call (mirrors ``_build_llm``) so each lane is truly
    memoryless. Runs the async client in its own event loop, so it is safe to
    invoke from worker threads when lanes run concurrently.
    """

    def __init__(self, project_root: Path, default_profile: str = "") -> None:
        self.root = Path(project_root)
        self.default_profile = default_profile

    def __call__(self, system: str, user: str, profile: str = "") -> str:
        from thomas.core.config import load_config
        from thomas.core.llm_client import LLMClient

        cfg = load_config(self.root / "thomas.toml")
        model_cfg = cfg.get_model((profile or self.default_profile) or None)
        client = LLMClient(model_cfg)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return asyncio.run(_collect_text(client, messages))


async def _collect_text(client: Any, messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    try:
        async for event in client.stream_chat(messages):
            etype = getattr(event, "type", "")
            data = getattr(event, "data", {}) or {}
            if etype in ("token", "text"):
                parts.append(str(data.get("text", "")))
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            try:
                await close()
            # Best-effort cleanup, and it runs in a `finally`: anything raised here
            # would REPLACE a real streaming error from the try above, so the set is
            # deliberately generous. Closing an aiohttp-backed client after the loop
            # has gone gives RuntimeError, a socket/file teardown gives OSError, and
            # ``client`` is duck-typed (Any, injectable in tests) so a close() that
            # is not awaitable or takes arguments gives TypeError/AttributeError.
            # Logged at debug rather than swallowed silently -- a close failure is
            # noise on a healthy path but must still be discoverable.
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                log.debug("funnel model client close failed (non-fatal): %s", exc)
    return "".join(parts).strip()
