"""Mood: whether a sentence of the request asks for something, or reports what the person saw.

Moved out of ``acceptance_contract`` on 2026-09-27, when a command rule took that module past the size rule. The
contract asks it two things: whether a sentence is a requirement, and whether a command is only reported on.
"""

from __future__ import annotations

import re

_REQUIREMENT_RE = re.compile(
    r"\b(?:must|should|every|all|each|exactly|deterministic|required|ensure|only"
    r"|needs?|need to|has to|have to|wants?|requires?|at least|includes?|including)\b",
    re.I,
)
# A requirement is what the user ASKS for. Two builds were sent back over sentences nobody could meet: a bug report ("So
# the human controls do not drive the karts.") chosen for its "do not", and the user's own narration ("Driving works on
# all four circuits now, I played each one...") chosen for its "all", while "Fix the keyboard driving..." and "Prove
# they work." were not requirements at all. Mood decides: an imperative addressed to Thomas is a requirement, narration
# is not, and "do not" counts only when it opens one.
_NARRATION_RE = re.compile(
    r"^(?:I|I've|I'd|I'm|So|With|Then|Earlier|Meanwhile|Here's|Before|After|Now|Today|Yesterday|Last time)\b"
    r"|\bI (?:played|tried|tested|ran|saw|noticed|found|checked|opened|clicked|pressed|drove|used|did|got|had)\b"
    r"|\b(?:the screen|the page|the hud|the results?|the timer|the console|it) (?:says|said|shows|showed|reads|read|reported)\b",
    re.I,
)
_WANT_RE = re.compile(r"\b(?:need|needs|want|wants|must|should|require|requires|expect|expects)\b", re.I)
_IMPERATIVE_RE = re.compile(
    r"^(?:please\s+)?(?:do not|don't|never|always|fix|prove|show|make|add|build|keep|use|play|ensure|write|create"
    r"|implement|remove|change|report|tell|give|run|test|verify|check|drive|include|return|produce|generate|render"
    r"|handle|support|avoid|stop|start|open|read|update|rename|move|delete|convert|install|document|explain|list"
    r"|compare|measure|count|sort|filter|validate|refactor|rewrite|replace|let|put|set|save|export|print|draw"
    r"|display|send|call|wire|hook|record|log|emit|serve|load|fetch|parse|compute|calculate|treat|prefer|only)\b",
    re.I,
)
_LEAD_CLAUSE_RE = re.compile(
    r"^(?:if|when|unless|once|whenever|after|before|otherwise)\b[^,;:]*[,;:]\s*(?P<rest>.+)$", re.I
)
_CLAUSE_SPLIT_RE = re.compile(r"[;:]\s+")
_PAST_LEAD_RE = re.compile(
    r"^(?:when|after|once|as|while)\s+I\s+(?:\w+ed|saw|ran|got|went|tried|hit|played|did|was|had)\b", re.I
)


# A command that is the subject of a report: "`python .../monolith_guard.py` (the whole-repo run) prints "...FAILED..."
# on dev today". Asked for nothing, it was made a command that had to exit 0 (2026-09-27); mood decides, as for
# requirements.
_REPORTED_RE = re.compile(
    r"\s*(?:\([^)]{0,120}\)\s*)?(?:prints|printed|fails|failed|reports|reported|lists|listed|shows|showed|says|said"
    r"|returns|returned|exits|exited|outputs|gives|gave)\b",
    re.I,
)


def _sentence_at(text: str, position: int) -> str:
    """The sentence (or line) of *text* around *position*."""
    before, after = text[:position], text[position:]
    marks = (". ", "! ", "? ")
    start = max([before.rfind("\n") + 1] + [i + 2 for i in (before.rfind(m) for m in marks) if i >= 0])
    ends = [i for i in (after.find("\n"), *(after.find(m) for m in marks)) if i >= 0]
    return text[start : position + (min(ends) + 1 if ends else len(after))]


def is_requirement_sentence(sentence: str) -> bool:
    text = sentence.strip()
    # An instruction wins first: "Before you finish, run the tests" opens like narration and is not.
    if _IMPERATIVE_RE.match(text):
        return True
    lead = _LEAD_CLAUSE_RE.match(text)
    if lead:
        # "When I enter a world it is only the HUD..., nothing renders": the condition clause lends none of
        # its words; the clause after it is the sentence that is judged.
        if _IMPERATIVE_RE.match(lead.group("rest")):
            return True
        text = lead.group("rest").strip()
        # "When I opened it, it only showed the HUD": a first-person past-tense
        # condition is a report of what happened; only a stated want survives it.
        if _PAST_LEAD_RE.match(sentence.strip()):
            return bool(_WANT_RE.search(text))
    if any(_IMPERATIVE_RE.match(clause.strip()) for clause in _CLAUSE_SPLIT_RE.split(text)[1:]):
        return True
    if _NARRATION_RE.search(text) and not _WANT_RE.search(text):
        return False
    return bool(_REQUIREMENT_RE.search(text))


def reported_only(text: str, start: int, end: int) -> bool:
    """True when the command spanning ``text[start:end]`` is the subject of a report in a sentence that asks for
    nothing: "`cmd` prints ... on dev today" is what the request saw, not a check."""
    return bool(_REPORTED_RE.match(text, end)) and not is_requirement_sentence(_sentence_at(text, start))


__all__ = ["is_requirement_sentence", "reported_only"]
