"""Structured completion evidence for delegated workers."""

from __future__ import annotations

from collections.abc import Sequence

from thomas.core.file_access import file_access_refusal_remedy
from thomas.server.chat_delegation_deliverable import _worker_answer_text


def result_with_policy_remedy(summary: object, policy_refusals: Sequence[str] | None) -> str:
    """Carry a policy refusal's own remedy sentence into the composed result.

    Measured (gauntlet g-desktopfile, live 2026-08-05): the file-access ladder
    refused a Desktop write with text that literally contained the fix — "Raise
    the file-access level (e.g. to 'Your PC') to write here." — but the reply
    the user saw only said the environment "can only write inside its
    workspace". The user-settable lever was known and withheld.

    So: for every refusal the run hit, extract the remedy sentence the refusal
    itself carries and append any the summary does not already state. Purely
    additive wording — this can neither pass nor fail a run, and a refusal
    without a remedy (the OS-system-dir one) adds nothing.
    """
    text = str(summary or "")
    remedies: list[str] = []
    for refusal in policy_refusals or []:
        remedy = file_access_refusal_remedy(refusal)
        if remedy and remedy not in remedies and remedy not in text:
            remedies.append(remedy)
    if not remedies:
        return text
    note = "A file write was refused by Thomas's file-access setting — a setting you control. " + " ".join(remedies)
    return f"{text}\n\n{note}" if text else note


def worker_text_is_confirmed_answer(
    result_text_parts: list[str],
    *,
    prompt: str = "",
    succeeded_tools: list[str] | None = None,
    failed_tools: list[str] | None = None,
) -> bool:
    """Accept an answer on a structured worker terminal event, with evidence.

    The caller invokes this only after the worker emits ``done`` or the
    exhaustive pipeline returns a reviewed result. Natural-language wording
    never changes that terminal status -- the prompt is deliberately unread.

    Text alone is NOT evidence. Reading only the text made "I'll get started on
    that" and "Created game.html with the snake game." -- with nothing written
    and no tool run -- both terminate as a green VERIFIED card carrying zero
    artifacts. That is the rubber-stamp failure this project keeps rediscovering,
    and it is worse than an honest failure because there is nothing to retry.

    So a run that produced no files must at least have DONE something: at least
    one tool call succeeded and none failed. That is execution telemetry from
    _record_tool_outcome, not a reading of anyone's wording, so it stays inside
    model-owned routing.

    ``succeeded_tools`` distinguishes absent from empty on purpose. ``None``
    means the caller has no tool telemetry to offer -- the exhaustive pipeline
    decides answer-only legitimacy from its rubric instead -- and the tool
    requirement is not applied. ``[]`` means the caller watched and the worker
    ran nothing, which is exactly the case to reject.
    """

    del prompt
    if not _worker_answer_text(result_text_parts):
        return False
    if succeeded_tools is None:
        # No telemetry offered; the caller judges legitimacy by its own rubric.
        return bool(not failed_tools)
    # A tool that failed and then succeeded was recovered from, and the run did the
    # thing this check exists to require. `if failed_tools: return False` used to
    # reject regardless: a research run whose first query 404s, searches again, gets
    # the answer and writes three good paragraphs was thrown away for the 404 -- the
    # recovery was already recorded in succeeded_tools and simply never consulted.
    #
    # The anti-rubber-stamp purpose is untouched, because it never rested on the
    # failure list. "I'll get started on that" with nothing run is still refused by
    # the answer-text check above and by the empty-succeeded_tools check below.
    unrecovered = [str(tool) for tool in (failed_tools or []) if str(tool) and str(tool) not in set(succeeded_tools)]
    if unrecovered:
        # A tool that failed and never once worked is still a real gap. Widening this
        # to "any success anywhere excuses any failure" would also excuse a worker
        # whose actual work failed and which then wrote an answer from nothing, so it
        # is left deliberately narrow.
        return False
    return bool(succeeded_tools)


__all__ = ["result_with_policy_remedy", "worker_text_is_confirmed_answer"]
