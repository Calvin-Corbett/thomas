"""Inkwell smart analysis: Thomas reads a note and sorts it.

Model resolution mirrors the chat pipeline (``resolve_effective_model``
+ user prefs + failover chain), so whatever model actually powers the
user's Thomas chat powers Inkwell. The model runs the full note-sorting
pass: what is this note, what's its purpose, what should be remembered,
what should become a reminder. Parsing is defensive — malformed model
output degrades to an empty analysis, never an error.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from typing import Any

log = logging.getLogger(__name__)

_ANALYZE_TIMEOUT_S = 60.0
_MAX_REMINDERS = 12
_MAX_SUGGESTIONS = 8
_MAX_OBSERVATIONS = 10
_VALID_SOUNDS = {"chime", "bell", "alarm", "pulse"}
_VALID_CATEGORIES = {"task", "idea", "event", "list", "journal", "reference", "mixed", "other"}

_SYSTEM_PROMPT = """You are Thomas, the engine behind the Inkwell smart notepad.
Every note the user writes runs through you to be understood and sorted.
Work through this pipeline for the note you are given:
1. What is this note? (category)
2. What is its purpose — what is the user trying to do with it?
3. What in it is time-bound and should become a reminder?
4. What is worth tracking or remembering about the user from it?
5. What short next steps would genuinely help?

Reply with ONLY a JSON object, no prose, in exactly this shape:
{
  "summary": "one plain-English sentence: what this note is",
  "category": "task|idea|event|list|journal|reference|mixed|other",
  "purpose": "one short sentence: what the user is trying to do",
  "reminders": [
    {"title": "what to remind", "when": "YYYY-MM-DDTHH:MM", "sound": "chime|bell|alarm|pulse", "repeat": "none|daily|weekly", "why": "the exact note text that triggered this"}
  ],
  "observations": [
    {"text": "something worth tracking about the user or their plans", "why": "the note text it came from"}
  ],
  "suggestions": ["short actionable next step", ...]
}

Rules:
- "when" is local time, YYYY-MM-DDTHH:MM. Resolve relative phrases
  ("tomorrow at 3", "friday morning", "in 2 hours") against the current
  local time you are given. Morning=09:00, afternoon=14:00, evening=18:00
  when no exact time is given.
- Phrases like "remind me ...", "don't forget ...", "need to ... by ..."
  are reminder requests — always convert them when any time can be
  inferred; if truly no time exists, surface them as observations instead.
- Every reminder and observation carries "why": the snippet of the user's
  own words it came from, so the user can see what you noticed.
- Only invent times for genuine time-bound items, never for ideas or lists.
- Sounds: "alarm" urgent, "bell" appointments, "chime" default, "pulse"
  gentle recurring nudges.
- Empty arrays are fine. Never return anything except the JSON object."""


class SmartAnalysisUnavailable(RuntimeError):
    """Raised when no model is configured or the call cannot complete."""


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply, tolerating fences."""
    text = (raw or "").strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _clean_reminder(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()[:300]
    when = str(raw.get("when") or "").strip()[:32]
    if not title or not when:
        return None
    sound = str(raw.get("sound") or "chime").strip().lower()
    repeat = str(raw.get("repeat") or "none").strip().lower()
    return {
        "title": title,
        "when": when,
        "sound": sound if sound in _VALID_SOUNDS else "chime",
        "repeat": repeat if repeat in {"none", "daily", "weekly"} else "none",
        "why": str(raw.get("why") or "").strip()[:300],
    }


def _clean_observation(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()[:300]
    if not text:
        return None
    return {"text": text, "why": str(raw.get("why") or "").strip()[:300]}


def normalize_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce a parsed model reply into the stable analysis shape."""
    reminders = []
    if isinstance(payload.get("reminders"), list):
        for raw in payload["reminders"][:_MAX_REMINDERS]:
            cleaned = _clean_reminder(raw)
            if cleaned is not None:
                reminders.append(cleaned)
    observations = []
    if isinstance(payload.get("observations"), list):
        for raw in payload["observations"][:_MAX_OBSERVATIONS]:
            cleaned = _clean_observation(raw)
            if cleaned is not None:
                observations.append(cleaned)
    suggestions = []
    if isinstance(payload.get("suggestions"), list):
        suggestions = [str(s).strip()[:300] for s in payload["suggestions"][:_MAX_SUGGESTIONS] if str(s).strip()]
    category = str(payload.get("category") or "").strip().lower()
    return {
        "summary": str(payload.get("summary") or "").strip()[:500],
        "category": category if category in _VALID_CATEGORIES else "other",
        "purpose": str(payload.get("purpose") or "").strip()[:300],
        "reminders": reminders,
        "observations": observations,
        "suggestions": suggestions,
    }


def _resolve_model(config: Any) -> tuple[Any, list[Any], bool]:
    """Resolve the model exactly like the chat pipeline: user prefs first,
    then project default, with the configured failover chain."""
    from thomas.core.model_resolution import resolve_effective_model

    try:
        profile, model_id = resolve_effective_model(config, user_id="default")
        model_cfg = config.get_model(profile)
        if model_id:
            model_cfg = replace(model_cfg, model=model_id)
        fallbacks = list(config.failover_chain(profile) or [])
        failover_enabled = bool(getattr(getattr(config, "failover", None), "enabled", False))
        log.info("Inkwell analysis using model profile '%s' (%s)", profile, model_cfg.provider)
        return model_cfg, fallbacks, failover_enabled
    except (KeyError, ValueError, RuntimeError, AttributeError) as e:
        raise SmartAnalysisUnavailable(
            "Thomas has no model configured yet, so smart analysis is offline. Notes and manual reminders still work."
        ) from e


async def analyze_text(config: Any, text: str, *, local_now: str = "") -> dict[str, Any]:
    """Ask the active Thomas model to sort a note (full pipeline pass)."""
    from thomas.core.llm_client import LLMClient

    model_cfg, fallbacks, failover_enabled = _resolve_model(config)
    # The full contract rides in the USER message: some providers (the codex
    # app-server path) treat system prompts as weak "instructions" or drop
    # them on fallback, then reply in prose instead of JSON.
    user_prompt = (
        f"{_SYSTEM_PROMPT}\n\n---\n"
        f"Current local date/time: {local_now or '(unknown — only extract explicit absolute times)'}\n\n"
        f"Note contents:\n{text}"
    )
    messages = [{"role": "user", "content": user_prompt}]
    llm = LLMClient(model_cfg, fallback_configs=fallbacks, failover_enabled=failover_enabled)
    try:
        result = await asyncio.wait_for(llm.chat(messages, tools=None), timeout=_ANALYZE_TIMEOUT_S)
    except asyncio.TimeoutError as e:
        raise SmartAnalysisUnavailable("Thomas took too long to analyze the note. Try again.") from e
    except Exception as e:  # provider/auth/network errors surface as 503, not 500
        log.warning("Inkwell analysis failed (%s): %s", getattr(model_cfg, "provider", "?"), e)
        raise SmartAnalysisUnavailable(f"Thomas could not analyze the note: {e}") from e
    finally:
        try:
            await llm.close()
        # Tearing down the HTTP session: a socket fault is OSError, closing an
        # already-closed/never-opened client is RuntimeError/AttributeError.
        # Close failures must not mask the result we already have.
        except (OSError, RuntimeError, AttributeError):
            log.debug("Inkwell LLM client close failed", exc_info=True)
    return normalize_analysis(_extract_json_object(str(result.get("text") or "")))
