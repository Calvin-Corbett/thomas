"""SWEEP: instruction fidelity — does Thomas build the thing the user ACTUALLY
asked for, not a neighbouring turn's request?

The user hit both failure directions:
  - OVER-attach: "Build me a Pong game" inherited a prior "starfield" request via the
    conversation handoff and shipped the wrong deliverable.
  - UNDER-attach: "now add a high score" was treated as a fresh self-contained task,
    so the worker had no idea WHAT to add a score to.

Frontier standard (Claude Code): the model always has the conversation, and resolves
references precisely — a self-contained spec is built literally; a contextual
follow-up is resolved against the prior turn. This sweep drives the REAL
`prompt_needs_handoff` gate that decides whether prior-turn context is attached.
"""

from __future__ import annotations

from _harness import Recorder

from thomas.server.chat_delegation_deliverable import prompt_needs_handoff

A = "instruction-fidelity"

# (prompt, must_attach_handoff, severity, why)
CASES = [
    # Self-contained build specs MUST NOT pull prior context (wrong-deliverable bleed).
    ("Build me a playable Pong web game as a single self-contained index.html", False, "critical", "fresh build spec"),
    ("Build me a colorful animated starfield web page", False, "critical", "fresh build spec"),
    ("now build me a snake game", False, "critical", "fresh build after adverb"),
    ("then create a landing page for my startup", False, "high", "fresh build after adverb"),
    ("write a python script that sorts a CSV by date", False, "high", "fresh self-contained"),
    ("add a dark mode toggle to the site", False, "high", "modification with named target"),
    # Contextual follow-ups MUST pull prior context (else the worker is blind).
    ("make it blue", True, "high", "bare reference"),
    ("change it to use arrow keys", True, "high", "bare reference"),
    ("now add a high score", True, "high", "continuation, no target — needs prior turn"),
    ("also include a restart button", True, "high", "continuation modification"),
    ("then remove the sidebar", True, "high", "continuation modification"),
    ("do the same again but bigger", True, "high", "explicit back-reference"),
]


def run() -> Recorder:
    rec = Recorder("instruction_fidelity")
    for prompt, expect, severity, why in CASES:
        got = prompt_needs_handoff(prompt)
        rec.add(
            case=f"handoff decision for: {prompt!r}",
            dimension=A,
            expected=f"attach_handoff={expect} ({why})",
            actual=f"attach_handoff={got}",
            passed=(got == expect),
            severity=severity,
            evidence="prompt_needs_handoff (chat_delegation_deliverable.py)",
        )
    return rec


if __name__ == "__main__":
    r = run()
    for row in r.rows:
        print(("PASS" if row.passed else "FAIL"), "|", row.case, "->", row.actual)
