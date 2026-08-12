"""Per-module chat context -- the starting-router preamble each workspace injects.

When the user talks to Thomas from inside a workspace module (Evolution,
Marketplace, ...), the chat is still the FULL Thomas -- the module is a starting
*context*, not a cage. We give the model a short system preamble so it knows
where it's standing and what the module's vocabulary means, plus an explicit
"break out" instruction so an off-topic request is handled normally instead of
being forced back to the module. This is organic, prompt-only steering -- no
keyword routing, no action classifier (see the project's no-keyword-chat rule).

Add one entry per module as modules adopt the scoped-chat pattern. Everything
else (session scope, memory tagging, the UI) keys off the same ``module`` string.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleContext:
    key: str
    system_preamble: str


_MODULES: dict[str, ModuleContext] = {
    "evolve": ModuleContext(
        key="evolve",
        system_preamble=(
            "You are Thomas, standing inside the Evolution workspace -- where "
            "Thomas improves its own codebase (refactors, hardening, reliability, "
            "tests, features). All work happens in a safe mirror; nothing touches "
            "the real project until a change passes its tests and is promoted.\n"
            "Explain this vocabulary plainly whenever the user asks: a 'step' is "
            "one round of work (look at the code, make a move, check the result); "
            "a 'change' is an edit Thomas keeps after it passes tests; 'max "
            "changes' and 'max steps' are safety stops so a run can't run away. "
            "Autonomy has three plain levels -- Ask first (changes nothing without "
            "approval), Auto-safe (makes safe changes itself, asks before risky "
            "ones), and Full autonomy (keeps going until done or the limit you "
            "set). Anything risky or irreversible waits in 'Awaiting your "
            "approval'.\n"
            "You are still the full Thomas. If the user's request is outside "
            "evolution, just help with it normally and say so briefly -- never "
            "refuse or force the topic back to evolution."
        ),
    ),
}


def module_preamble(module: str) -> str:
    """Return the starting-router preamble for a module key, or '' if unknown."""
    ctx = _MODULES.get((module or "").strip().lower())
    return ctx.system_preamble if ctx else ""


def known_module(module: str) -> bool:
    """True if the module key has a registered scoped-chat context."""
    return (module or "").strip().lower() in _MODULES
