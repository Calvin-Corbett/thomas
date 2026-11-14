"""What Autopilot reports about the last run is Thomas's notes, never part of the request.

Every Autopilot round's message is the goal followed by Thomas's report on the last run: its outcome (the completion
gate's own failures among it), the files it changed, the tail of its transcript, a repair round's findings. The
contract read the whole message as the request, so every path in that report became a file to create. On 2026-09-27
three teams had created `auth.json` and another project's doc to get past a misread check; the next done check's
message said "Files changed: auth.json, docs/BUILD_PROJECT_FOLDER_ALIGNMENT.md", which made both required outputs
again, and a gate failure quoted in "Last outcome" asked for the same file on the round after.
"""

from __future__ import annotations

from pathlib import Path

from thomas.core.acceptance_contract import KIND_OUTPUT_PATH, build_contract
from thomas.server import thomas_project
from thomas.server.routes import autopilot_messages as am

GOAL = "Split thomas/server/web/settings.html and write the split up in notes/size.md."
TURN = {
    "outcome": "failed",
    "reason": "Completion gate blocked AGENT_DONE: - FAILED: `docs/other_project.md` exists and is non-empty",
    "changed_files": ["auth.json", "thomas/server/web/css/new_split.css"],
    "transcript": "...opened .thomas/scratch/probe_server.py and tests/test_probe_only.py...",
}


def _outputs(message: str, ws: Path) -> set[str]:
    return {i.item_id for i in build_contract(message, ws) if i.kind == KIND_OUTPUT_PATH}


def _only_the_goals_output(message: str, ws: Path) -> None:
    # The copy already has the file the goal splits and the test a repair round's steps name.
    for existing in ("thomas/server/web/settings.html", "tests/test_architecture.py"):
        (ws / existing).parent.mkdir(parents=True, exist_ok=True)
        (ws / existing).write_text("x", encoding="utf-8")
    assert _outputs(message, ws) == {"output:notes/size.md"}, message


def test_a_continuation_reports_the_last_run_as_notes(tmp_path: Path) -> None:
    _only_the_goals_output(am.continuation_message(GOAL, TURN), tmp_path)


def test_a_done_check_reports_the_files_changed_as_notes(tmp_path: Path) -> None:
    message = am.review_message(GOAL, {**TURN, "reason": "2 file(s) changed"}, "high")

    _only_the_goals_output(message, tmp_path)
    assert "Files changed: auth.json, thomas/server/web/css/new_split.css" in message  # the team still reads it


def test_a_resume_reports_the_files_changed_as_notes(tmp_path: Path) -> None:
    _only_the_goals_output(am.resume_message(GOAL, TURN, "OpenAI"), tmp_path)


OLD_CONTINUATION = (
    f"Autopilot: continuing toward the goal: {GOAL}\n\nLast outcome: failed -- Completion gate blocked AGENT_DONE: - "
    "FAILED: `docs/other_project.md` exists and is non-empty\n\nFiles changed so far: auth.json\n\nLast 1500 "
    "characters of the transcript:\n...tests/test_probe_only.py...\n\nDiagnose what went wrong, fix it, and carry on "
    "until the goal is met and its checks pass."
)
OLD_REVIEW = (
    f"Autopilot: continuing: done check on the goal: {GOAL}\n\nThe last run finished: 2 file(s) changed. Files "
    "changed: auth.json, docs/other_project.md.\n\nYou are on Autopilot. Decide whether the product is done."
)
OLD_REPAIR = (
    f"Autopilot: continuing: repair round 1 toward the goal: {GOAL}\n\nYour finished change came back.\n\n"
    "Why it came back, in full:\ntests/test_probe_only.py fails; docs/other_project.md"
)


def test_a_report_written_before_it_was_marked_is_still_notes(tmp_path: Path) -> None:
    for old in (OLD_CONTINUATION, OLD_REVIEW, OLD_REPAIR):
        _only_the_goals_output(old, tmp_path)
        _only_the_goals_output(am.restart_message(GOAL, old), tmp_path)  # a restart quotes the stopped run whole


def test_a_repair_rounds_findings_are_notes(tmp_path: Path) -> None:
    for why in (thomas_project.SENT_BACK, thomas_project.TOO_LARGE, "dev_moved"):
        due = {
            "round": 1,
            "why": why,
            "detail": "tests/test_probe_only.py fails; docs/other_project.md",
            "dev": "abc",
            "changed_files": ["docs/other_project.md"],
        }
        _only_the_goals_output(am.repair_message(GOAL, due), tmp_path)
        message = am.repair_message(GOAL, due)
        if why == thomas_project.SENT_BACK:
            assert "Files already changed in this copy: docs/other_project.md" in message
            assert message.index("Run the failing checks") < message.index("Re-run the checks")
        else:
            assert "Files already changed in this copy:" not in message
