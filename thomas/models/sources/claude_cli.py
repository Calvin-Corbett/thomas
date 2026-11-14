"""Claude through the Claude CLI, for a Claude Code sign-in with no API key.

``opus``, ``sonnet`` and ``haiku`` are names the CLI resolves privately, so this
list offers them and says only what has been checked about each. It used to call
``opus`` "Claude Opus (newest)"; on Claude Code 2.1.278 that name starts
``claude-opus-5`` while ``claude-opus-5-5`` exists, so the label was a claim no
one here had tested. ``thomas/core/claude_alias_ids.py`` owns the wording and
the two things that can be checked — what the engine reported it started, and
what Anthropic's own list carries. Chat runs these too, not only Build, since
2026-09-25 (``thomas/core/llm_streaming_claude_cli.py``).

The labels are built PER CALL rather than once at import, because the first
Build run on a fresh machine is what teaches Thomas which exact model the alias
starts — a constant computed at import would still be saying "unchecked" long
after the run that checked it.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable

from thomas.core.claude_alias_ids import alias_label
from thomas.core.claude_plan import CLAUDE_PLAN_MODEL_IDS
from thomas.models.sources import ListedModel, SourceAnswer


def claude_cli_aliases() -> tuple[ListedModel, ...]:
    """The alias rows for the menu, each labelled with what is known right now.

    Built from the names the transport accepts (thomas/core/claude_plan.py), so
    the list the menu offers for this profile and the list that actually starts
    the CLI cannot drift into offering a model the turn would send somewhere else.
    """
    rows = []
    for order, name in enumerate(CLAUDE_PLAN_MODEL_IDS, start=1):
        display_name, description = alias_label(name)
        rows.append(ListedModel(id=name, display_name=display_name, description=description, order=order))
    return tuple(rows)


def list_claude_cli_models(*, which: Callable[[str], str | None] | None = None) -> SourceAnswer:
    if not (which or shutil.which)("claude"):
        return SourceAnswer(
            ok=False, source="claude-cli", error="no Anthropic API key and no Claude CLI on this machine"
        )
    return SourceAnswer(ok=True, source="claude-cli", models=claude_cli_aliases())
