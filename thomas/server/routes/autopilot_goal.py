"""The goal Autopilot holds a Build to: everything you asked for, not only your latest message.

You said: "your done check takes my latest message as the whole goal and forgets what I asked for first."
Measured 2026-09-25: a Thomas project the server restarted was sent "Carry on from where you stopped..."
and from that turn on the goal in every continuation, resume, repair and done-check message was the words
"carry on" -- the cleanup you had actually asked for first was gone. The goal was one turn, read straight
out of ``evolve_agent_autopilot``: the last user turn Autopilot had not written itself. This module is what
that read became.

The goal is now every instruction you gave in that conversation, oldest first (:func:`instructions`), read
as one text (:func:`goal_text`) that says outright a later message wins where two of them conflict. So "A",
then "carry on", then "also B" is a goal of A and B, and the done check has to hold the work to both.

What counts as an instruction from you:

* a user turn Autopilot did not write -- anything not starting with :data:`CONTINUATION_PREFIX`. Autopilot's
  own rounds (continuations, done checks, resumes after a usage limit, repair rounds) all start with it;
* the steering you send from Chat mid-round (:func:`steers_in`). That rides inside a round Autopilot wrote,
  in its second paragraph exactly (``thomas_project.steering_message``), so it survives its own round.

A goal of two or more instructions is written as a numbered list with each item flattened, so the whole
goal stays one paragraph: a run message your steering is spliced into is split on its first blank line
(``thomas_project.steering_message``), and a goal carrying blank lines would swallow that splice point.
A goal of one instruction is that instruction word for word, exactly as every Autopilot message read
before there was ever a second one to hold.
"""

from __future__ import annotations

from typing import Any

# Marks a user turn Autopilot wrote itself. `evolve_agent_autopilot` builds its REVIEW_PREFIX,
# RESUME_PREFIX, STEER_PREFIX and REPAIR_PREFIX on top of this one, so each is skipped here too.
CONTINUATION_PREFIX = "Autopilot: continuing"
# The line `thomas_project.steering_message` writes for the steering you sent from Chat.
STEER_LINE = "Steering update: "
# What the goal says about itself once there is more than one instruction in it.
GOAL_HEAD = "everything you asked for here, in order -- where two of these conflict, the later one wins:"


def steers_in(text: str) -> list[str]:
    """The steering you sent that a round Autopilot wrote carries, oldest first; ``[]`` for a round with none.

    The steering sits in the second paragraph and nowhere else (``thomas_project.steering_message`` puts it
    right after the paragraph naming what the round is). Matching :data:`STEER_LINE` anywhere in the text
    instead would count a transcript tail that merely quotes an earlier steer -- which every continuation
    message carries -- as steering of its own, on every round.
    """
    parts = str(text or "").split("\n\n", 2)
    if len(parts) < 2 or not parts[1].startswith(STEER_LINE):
        return []
    block = parts[1][len(STEER_LINE) :].strip()
    if block.startswith("- "):  # two or more steers held for the same round, one per line
        return [line.strip()[2:].strip() for line in block.splitlines() if line.strip()[2:].strip()]
    return [block] if block else []


def instructions(turns: list[dict[str, Any]]) -> list[str]:
    """Everything you asked for in this conversation, oldest first: your typed turns, plus your steering."""
    asked: list[str] = []
    for turn in turns:
        if not isinstance(turn, dict) or turn.get("role") != "user":
            continue
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        if text.startswith(CONTINUATION_PREFIX):
            asked.extend(steers_in(text))  # a round Autopilot wrote is not an instruction; the steer in it is
            continue
        asked.append(text)
    return asked


def _item(number: int, text: str) -> str:
    """One numbered instruction, flattened to a single paragraph so the goal as a whole stays one."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    head = lines[0] if lines else ""
    return "\n".join([f"{number}. {head}", *(f"   {line}" for line in lines[1:])])


def goal_text(turns: list[dict[str, Any]]) -> str:
    """The whole goal as one text: your first request plus what your later messages add or change.

    A conversation with one instruction reads as that instruction, word for word -- the shape every
    Autopilot message had before there was ever a second one to hold.
    """
    asked = instructions(turns)
    if len(asked) <= 1:
        return asked[0] if asked else ""
    return "\n".join([GOAL_HEAD, *(_item(number, text) for number, text in enumerate(asked, start=1))])


__all__ = ["CONTINUATION_PREFIX", "GOAL_HEAD", "STEER_LINE", "goal_text", "instructions", "steers_in"]
