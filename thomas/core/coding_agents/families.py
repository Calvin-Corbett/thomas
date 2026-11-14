"""Which family a model id belongs to — the one spelling of that question.

Build used to answer "which agent runs this task?" by reading the model's family
off the id, so the answer to *what to run with* also decided *what runs it*. The
agent picker (``thomas/core/coding_agents/registry.py``) separates those two
questions, and this module keeps the first one: a family is a property of the
model, and an agent declares which families it can serve.

``thomas/forge/anvil/forge_code_settings.py`` grew the Claude pattern first and
now delegates here, so there is one boundary rather than two that drift.
"""

from __future__ import annotations

import re

from thomas.core.listed_models import listed as _listed_models

#: Every family a coding agent can declare, in picker order.
FAMILIES: tuple[str, ...] = ("gpt", "claude")

#: A model id that is neither. Build refuses these rather than substituting.
UNKNOWN_FAMILY = "other"

# Models the Claude engines can actually serve. Keep the boundary structural: a
# value merely starting with "claude" (``claudeevil``/``claudette-local``) is not
# a Claude model, nor does the wire prefix make a foreign variant
# (``claude:qwen``) one.
_CLAUDE_MODEL = re.compile(
    r"^(?:"
    r"claude|"
    r"(?:sonnet|opus|haiku)(?:[-.]\d+(?:[-.]\d+)*)?|"
    r"claude-(?:instant-)?\d+(?:[-.]\d+)*|"
    r"claude-(?:\d+(?:[-.]\d+)*-)?(?:sonnet|opus|haiku)(?:[-.]\d+(?:[-.]\d+)*)?"
    r")$",
    re.I,
)

# The GPT side is a prefix rule because that is what Build has always applied:
# `gpt-` names the model, and `codex`/`chatgpt`/`openai_codex` name the account
# the in-process loop reaches it through.
_GPT_PREFIXES = ("gpt-", "codex", "chatgpt", "openai_codex")


def strip_wire_prefix(value: str) -> str:
    """Drop a ``claude:``/``codex:`` dispatch prefix, leaving the model itself."""
    text = str(value or "").strip()
    for prefix in ("claude:", "codex:"):
        if text.lower().startswith(prefix):
            return text.split(":", 1)[1]
    return text


def is_claude_model(value: str) -> bool:
    """A Claude model: one the pattern above knows, or one Anthropic listed on the
    catalog's last check (``thomas/models/catalog.py``), so a new family runs
    without a change here."""
    text = str(value or "").strip()
    return bool(_CLAUDE_MODEL.fullmatch(text)) or text.lower() in _listed_models("anthropic")


def is_gpt_model(value: str) -> bool:
    return str(value or "").strip().lower().startswith(_GPT_PREFIXES)


def model_family(model_id: str, *, model: str = "") -> str:
    """``"gpt"``, ``"claude"``, or ``UNKNOWN_FAMILY``.

    ``model`` is the second field Build's payload carries (the wire form, e.g.
    ``claude:sonnet``); either naming a family is enough, which is the rule
    ``forge_code_settings`` already applied when it read the family itself.
    """
    for candidate in (model_id, model):
        if is_gpt_model(candidate):
            return "gpt"
    for candidate in (model_id, model):
        if is_claude_model(strip_wire_prefix(candidate)):
            return "claude"
    return UNKNOWN_FAMILY
