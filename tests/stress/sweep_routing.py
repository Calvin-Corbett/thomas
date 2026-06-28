"""SWEEP: intent routing (should_dispatch).

Drives the real `thomas.agent.dispatch.should_dispatch` over a labeled corpus
and measures how often it misroutes. The dangerous class is FALSE-CASUAL: the
user asks for real work and the regex classifier treats it as small talk, so
nothing is dispatched (Thomas just chats back). Frontier systems interpret
intent with the model, not a keyword whitelist — this sweep quantifies the cost
of the whitelist.
"""

from __future__ import annotations

from _harness import Recorder

from thomas.agent.dispatch import should_dispatch

# (text, ground_truth_action, category, severity_if_wrong)
# ground_truth = what a competent assistant SHOULD do with this message.
CORPUS = [
    # --- clear tasks with canonical keywords (should dispatch) ---
    ("build me a snake game", "dispatch", "clear_task", "high"),
    ("fix the bug in the login route", "dispatch", "clear_task", "high"),
    ("write a python script to rename my files", "dispatch", "clear_task", "high"),
    ("create a report on Q3 revenue", "dispatch", "clear_task", "high"),
    ("debug the failing test in checkout", "dispatch", "clear_task", "high"),
    ("research the best CRM for small teams", "dispatch", "clear_task", "high"),
    ("deploy the site to production", "dispatch", "clear_task", "high"),
    ("refactor the auth module", "dispatch", "clear_task", "med"),
    # --- natural-language tasks that lack a whitelisted verb (should dispatch) ---
    ("put a file on my desktop that says hello", "dispatch", "natural_task", "critical"),
    ("can you throw together a quick logo for me", "dispatch", "natural_task", "high"),
    ("I need the quarterly numbers pulled into a spreadsheet", "dispatch", "natural_task", "high"),
    ("get me the latest sales figures", "dispatch", "natural_task", "high"),
    ("order more printer paper", "dispatch", "natural_task", "high"),
    ("book a flight to NYC next friday", "dispatch", "natural_task", "high"),
    ("turn the lights off in the living room", "dispatch", "natural_task", "high"),
    ("remind me to call mom at 5", "dispatch", "natural_task", "med"),
    ("schedule a meeting with the team tomorrow", "dispatch", "natural_task", "high"),
    ("draft a reply to this email and send it", "dispatch", "natural_task", "high"),
    ("summarize this article into 3 bullets and save it", "dispatch", "natural_task", "high"),
    ("translate the attached doc to spanish", "dispatch", "natural_task", "med"),
    ("rename all my screenshots to include the date", "dispatch", "natural_task", "med"),
    ("clean up my downloads folder", "dispatch", "natural_task", "med"),
    # --- genuine small talk / meta (should stay casual) ---
    ("hi", "casual", "small_talk", "low"),
    ("thanks!", "casual", "small_talk", "low"),
    ("ok", "casual", "small_talk", "low"),
    ("how's it going", "casual", "small_talk", "low"),
    ("what can you do", "casual", "small_talk", "low"),
    ("are you there", "casual", "small_talk", "low"),
    # --- information questions (should stay casual) ---
    ("what's the capital of France", "casual", "question", "low"),
    ("why is the sky blue", "casual", "question", "low"),
    ("should I use postgres or mysql for this", "casual", "question", "low"),
    ("what do you think about microservices for a small app", "casual", "question", "low"),
]


def run() -> Recorder:
    rec = Recorder("routing")
    for mode in ("auto", "max"):
        mode_arg = "" if mode == "auto" else "max"
        # an active task for the status-followup guard isn't needed here
        for text, truth, category, sev in CORPUS:
            decision = should_dispatch(text, mode=mode_arg)
            actual = decision.action
            passed = actual == truth
            # A false-casual on a real task is the costly miss; downgrade severity
            # for casual->dispatch on small talk (over-eager, less harmful).
            severity = sev if (truth == "dispatch" or not passed) else "low"
            rec.add(
                case=f"[{mode}] {category}: {text!r}",
                dimension="intent-routing",
                expected=f"{truth}",
                actual=f"{actual} (reason={decision.reason})",
                passed=passed,
                severity=severity,
                evidence=f"mode={mode}",
            )
    return rec


if __name__ == "__main__":
    run().console()
