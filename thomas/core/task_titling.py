"""Task titling — give a background task card a real, human-readable name.

Why this exists
---------------
The task card used to be titled with ``prompt[:200]`` — a raw truncation of
whatever the user typed ("hey thomas can you please build me a little pac man
game that..."). That is the "generic naming" Calvin called out: the card never
says *what the task actually is*.

The right answer is a model-written title. ``generate_task_title`` does exactly
that when given an LLM. But the title is needed the instant a task is dispatched,
sometimes on a path that has no LLM wired in yet, so ``derive_task_title``
provides a graceful, deterministic fallback that *cleans up* the prompt into an
imperative title — it strips conversational filler and keeps the action. This is
formatting, not intent classification: it never decides whether something is a
task and never produces a user-facing chat reply.
"""

from __future__ import annotations

import re

_MAX_TITLE_WORDS = 9

# Leading conversational scaffolding to peel off before we find the real ask.
# Order matters: longest / most-specific phrases first.
_LEADING_FILLER = (
    "i would like you to",
    "i'd like you to",
    "i want you to",
    "i need you to",
    "i was wondering if you could",
    "i was hoping you could",
    # "...to" variants MUST precede the bare ones below so "i want to build x"
    # peels to "build x", not "to build x".
    "i would like to",
    "i'd like to",
    "i want to",
    "i need to",
    "i would like",
    "i'd like",
    "i want",
    "i need",
    "can you please",
    "could you please",
    "would you please",
    "can you",
    "could you",
    "would you",
    "will you",
    "please go ahead and",
    "please",
    "go ahead and",
    "for me",
    "real quick",
    "if you don't mind",
    "when you get a chance",
    "hey thomas",
    "hi thomas",
    "hey there",
    "ok so",
    "okay so",
    "so basically",
    "basically",
    "hey",
    "hi",
    "hello",
    "yo",
    "thomas",
    "um",
    "uh",
)

# Imperative action verbs — if the cleaned ask starts with one, it already reads
# as a title ("Build a ...", "Fix the ...").
_ACTION_VERBS = frozenset(
    {
        "build",
        "create",
        "make",
        "implement",
        "fix",
        "update",
        "refactor",
        "write",
        "draft",
        "design",
        "test",
        "debug",
        "deploy",
        "benchmark",
        "compare",
        "analyze",
        "analyse",
        "investigate",
        "review",
        "ship",
        "run",
        "produce",
        "add",
        "remove",
        "set",
        "setup",
        "plan",
        "research",
        "find",
        "generate",
        "convert",
        "summarize",
        "summarise",
        "rewrite",
        "optimize",
        "optimise",
        "migrate",
        "scaffold",
        "wire",
    }
)


def _first_clause(text: str) -> str:
    """Return the first sentence/clause — the core ask, not the whole essay."""
    collapsed = " ".join(str(text or "").split())
    if not collapsed:
        return ""
    # Cut at the first strong terminator or a clause break that introduces detail.
    cut = re.split(r"(?<=[.!?])\s+|\s+(?:that also|and also|, then|; )", collapsed, maxsplit=1)
    return cut[0].strip() if cut else collapsed


def _strip_leading_filler(text: str) -> str:
    out = text.strip()
    changed = True
    # Peel repeatedly: "hey thomas can you please build..." -> "build..."
    while changed:
        changed = False
        low = out.lower()
        for phrase in _LEADING_FILLER:
            if low.startswith(phrase):
                rest = out[len(phrase) :]
                # Only strip if it's a whole-word boundary (next char non-alpha).
                if not rest[:1].isalpha():
                    out = rest.lstrip(" ,.:;-")
                    changed = True
                    break
    return out.strip()


def derive_task_title(prompt: str, *, max_words: int = _MAX_TITLE_WORDS) -> str:
    """Deterministic fallback title: clean the prompt into an imperative phrase.

    Not an LLM call and not intent classification — pure string formatting used
    only when no model is available to title the task.
    """
    core = _strip_leading_filler(_first_clause(prompt))
    if not core:
        return "New task"

    words = core.split()
    # "Build me a X" / "make us a Y" -> drop the indirect-object pronoun so the
    # title reads cleanly ("Build a X").
    if len(words) > 2 and words[0].lower() in _ACTION_VERBS and words[1].lower() in {"me", "us"}:
        del words[1]
    # Capitalize the first word (sentence case) without lowercasing acronyms/names.
    first = words[0]
    if first[:1].islower() and (first.lower() in _ACTION_VERBS or first.isalpha()):
        words[0] = first[:1].upper() + first[1:]

    truncated = words[: max(1, int(max_words))]
    title = " ".join(truncated).rstrip(" ,.:;-")
    if len(words) > len(truncated):
        title += "…"
    return title or "New task"


_LLM_TITLE_INSTRUCTION = (
    "Write a short, specific title (3-8 words) that names the task in this "
    "message. Use an imperative phrase like 'Build a Pac-Man browser game'. "
    "Do not add quotes, punctuation at the end, or any commentary — output only "
    "the title.\n\nMessage:\n"
)


async def generate_task_title(
    prompt: str,
    *,
    llm: object | None = None,
    max_words: int = _MAX_TITLE_WORDS,
) -> str:
    """Model-written task title, falling back to :func:`derive_task_title`.

    ``llm`` may be any object exposing an async ``generate(prompt) -> str`` (or
    ``complete``) method. Anything unexpected from the model is discarded in
    favor of the deterministic title so the card always gets a sane name.
    """
    text = str(prompt or "").strip()
    if not text:
        return "New task"
    if llm is None:
        return derive_task_title(text, max_words=max_words)

    raw = ""
    try:
        gen = getattr(llm, "generate", None) or getattr(llm, "complete", None)
        if gen is not None:
            result = await gen(_LLM_TITLE_INSTRUCTION + text)
            raw = str(getattr(result, "text", result) or "").strip()
    except Exception:
        raw = ""

    candidate = raw.strip().strip("\"'").splitlines()[0].strip() if raw else ""
    # Reject junk: empty, too long, or model narrating instead of titling.
    if (
        candidate
        and len(candidate.split()) <= max_words + 2
        and not candidate.lower().startswith(("here", "title:", "sure"))
    ):
        return candidate.rstrip(" .,:;-")
    return derive_task_title(text, max_words=max_words)


__all__ = ["derive_task_title", "generate_task_title"]
