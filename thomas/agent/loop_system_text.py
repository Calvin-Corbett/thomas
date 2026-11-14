"""Text the agent loop adds to its system message: the per-turn required text and the cached startup brief."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from thomas.agent.guidance import load_cached_purpose_brief

log = logging.getLogger(__name__)


def with_required_system_text(system_msg: dict[str, Any], required_system_text: str) -> dict[str, Any]:
    """Append required per-turn context (the acceptance contract) to the system message.

    Unlike memory, it goes out on every iteration and is never dropped to make room:
    the wire fitter refuses rather than cutting system text.
    """
    text = str(required_system_text or "").strip()
    if not text:
        return system_msg
    content = str(system_msg.get("content") or "")
    return {**system_msg, "content": f"{content}\n\n{text}" if content else text}


@lru_cache(maxsize=1)
def load_purpose_text() -> str:
    """Load cached startup guidance brief (best effort)."""
    try:
        return load_cached_purpose_brief()
    except Exception:  # REVIEWED: swallow — optional feature, fallback to empty string
        # Broad catch: purpose brief is decorative context; any load failure must not break agent startup.
        log.debug("Purpose brief load failed; continuing without it.", exc_info=True)
        return ""
