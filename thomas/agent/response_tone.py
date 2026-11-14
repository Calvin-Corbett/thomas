"""Model-neutral response and profile helpers.

Thomas's frontier model owns tone, brevity, structure, and presentation. This
module contains only deterministic policy selected through structured profile
settings plus cleanup for browser-inaccessible local links.
"""

from __future__ import annotations

import re

from thomas.agent.prompt_templates import format_input_continuity_hint
from thomas.core.sandbox_links import strip_sandbox_links

_SIMPLIFIED_REVIEW_HINT_TEXT = (
    "- Keep review feedback plain-language and concise.\n"
    "- Prefer a simple good/bad summary with concrete next action.\n"
    "- Avoid deep technical jargon unless the user explicitly asks for it."
)


def simplified_review_default_hint(
    review_depth: str,
    *,
    non_coder_profile: bool = False,
) -> str:
    """Build guidance from explicit profile settings, not prompt wording."""
    normalized = str(review_depth or "").strip().lower().replace("-", "_")
    if normalized in {"simple", "simplified", "plain", "non_technical"} or (
        normalized not in {"technical", "detailed", "deep"} and bool(non_coder_profile)
    ):
        return format_input_continuity_hint(_SIMPLIFIED_REVIEW_HINT_TEXT).strip()
    return ""


_BEST_PRACTICE_HINT_TEXT = (
    "- Use robust production-safe practices and state material tradeoffs.\n"
    "- Prefer one strongest recommendation with concrete execution steps.\n"
    "- Never claim execution or verification without evidence."
)


def best_practice_default_hint() -> str:
    """Return guidance enabled by the explicit non-coder profile setting."""
    return format_input_continuity_hint(_BEST_PRACTICE_HINT_TEXT).strip()
