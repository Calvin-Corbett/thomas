"""Per-(provider, model) worker tuning overrides.

The provider-agnostic worker (``thomas/server/worker_runtime.py``) runs the
*same* ``AgentLoop`` for every provider.  This module is the single, declarative
place to nudge that loop per model — without forking the core.

A model with no entry runs the unmodified loop (``ModelOverride()`` is all
defaults), so adding a new provider needs **zero** override work: overrides are
purely opt-in polish.  Tune a model by editing one dict entry below.

Overrides are applied at the loop's already-existing injection edges:
  * ``prompt_suffix``   -> appended to the worker's system prompt
  * ``tool_deny``       -> tool names/prefixes pruned from the registry
  * ``max_iterations``  -> passed to ``AgentLoop.run(max_iterations=...)``
  * ``reasoning_effort``-> set on the ModelConfig when that field exists
  * ``request_overrides``-> forwarded to ``LLMClient(request_overrides=...)``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelOverride:
    """Opt-in per-model tuning for the background worker. All-default = no-op."""

    prompt_suffix: str | None = None
    tool_deny: frozenset[str] = frozenset()
    max_iterations: int | None = None
    reasoning_effort: str | None = None
    request_overrides: dict[str, Any] = field(default_factory=dict)


def _norm_provider(provider: Any) -> str:
    """Normalize a provider name the way the rest of Thomas does."""
    return str(provider or "").strip().lower().replace("-", "_")


# Keyed by (normalized_provider, model_or_None). A (provider, None) entry is the
# provider-wide default; a (provider, model) entry wins over it.
WORKER_OVERRIDES: dict[tuple[str, str | None], ModelOverride] = {
    # gpt-5.5 over the ChatGPT OAuth path -- Calvin's first tuning target.
    ("openai_codex", "gpt-5.5"): ModelOverride(reasoning_effort="high", max_iterations=40),
    ("openai_codex", None): ModelOverride(reasoning_effort="medium", max_iterations=30),
    # Small local models: smaller context, prune heavy tools, firmer nudge.
    ("ollama", None): ModelOverride(
        prompt_suffix="\nUse one tool at a time. Verify each file write before continuing.",
        tool_deny=frozenset({"ssh", "notebook"}),
        max_iterations=20,
    ),
    ("local", None): ModelOverride(
        prompt_suffix="\nUse one tool at a time. Verify each file write before continuing.",
        tool_deny=frozenset({"ssh", "notebook"}),
        max_iterations=20,
    ),
}


def resolve_override(provider: Any, model: Any) -> ModelOverride:
    """Return the override for ``(provider, model)``, most specific first.

    Falls back to the provider-wide entry, then to an all-default no-op.
    """
    p = _norm_provider(provider)
    m = str(model or "").strip() or None
    return WORKER_OVERRIDES.get((p, m)) or WORKER_OVERRIDES.get((p, None)) or ModelOverride()
