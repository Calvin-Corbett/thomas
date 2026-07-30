"""CAP-141 — structured post-run reports.

Acceptance line: "Add structured attempts, validations, open risks, attention
pointers, and rubric mapping." These tests build reports from synthetic run
event/result fixtures covering ALL FIVE sections, prove degenerate runs produce
honest minimal reports (no invented content), and prove the server completion
payload carries the report.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aiohttp import web

from tests.test_evolve_agent_routes import _new_repo
from thomas.forge.anvil import forge_code_git, forge_code_store
from thomas.forge.anvil.run_report import (
    build_run_report,
    parse_forge_events,
    report_from_dispatch_result,
)
from thomas.server.routes import evolve_agent_runtime

REPORT_SECTIONS = ("attempts", "validations", "open_risks", "attention_pointers", "rubric_mapping")

# A realistic two-pass run: edit -> failing engine check -> fix pass -> passing
# engine check -> final handoff. Shapes mirror forge_event_stream / build_verify.
_FULL_RUN_TRANSCRIPT = "\n".join(
    [
        '{"fc":"say","text":"Working on the widget."}',
        '{"fc":"tool","name":"Edit","text":"file_path: app.py"}',
        '{"fc":"tool_result","text":"ok","is_error":false}',
        '{"fc":"tool","name":"run","text":"static checks: syntax + parse + open (app.py)"}',
        '{"fc":"tool_result","text":"exit 1\\napp.py:3 SyntaxError: invalid syntax","is_error":true}',
        '{"fc":"meta","text":"verification failed (exit 1); fix pass 1/2"}',
        '{"fc":"tool","name":"Edit","text":"file_path: app.py"}',
        '{"fc":"tool","name":"run","text":"static checks: syntax + parse + open (app.py)"}',
        '{"fc":"tool_result","text":"exit 0\\ncompiled app.py","is_error":false}',
        '{"fc":"final","text":"Fixed and verified."}',
    ]
)

_GOAL_WITH_CRITERIA = "Build the widget.\n- render the widget header\n- persist widget state"


def _full_run_report() -> dict[str, Any]:
    return build_run_report(
        goal=_GOAL_WITH_CRITERIA,
        transcript=_FULL_RUN_TRANSCRIPT,
        changed_files=["app.py"],
        returncode=0,
        ok=True,
        outcome="completed",
        reason="1 file(s) changed",
    )


def test_report_has_all_five_sections() -> None:
    report = _full_run_report()
    assert tuple(sorted(report)) == tuple(sorted(REPORT_SECTIONS))


def test_attempts_capture_each_pass_goal_actions_and_exit_state() -> None:
    attempts = _full_run_report()["attempts"]
    assert len(attempts) == 2
    first, second = attempts
    assert first["pass"] == 1
    assert first["goal"].startswith("Build the widget.")
    assert first["outcome"] == "verification failed"
    assert any("Edit" in action for action in first["key_actions"])
    assert "exit 1" in first["exit_state"] and "fix pass 1" in first["exit_state"]
    assert second["pass"] == 2
    assert "fix pass 1/2" in second["goal"]
    assert second["outcome"] == "completed"
    assert second["exit_state"].startswith("exit 0")


def test_validations_carry_command_pass_fail_and_evidence() -> None:
    validations = _full_run_report()["validations"]
    assert len(validations) == 2
    assert validations[0]["kind"] == "engine_check"
    assert validations[0]["command"].startswith("static checks")
    assert validations[0]["passed"] is False
    assert "SyntaxError" in validations[0]["evidence"]
    assert validations[1]["passed"] is True
    assert "compiled app.py" in validations[1]["evidence"]


def test_agent_tool_results_are_not_counted_as_validations() -> None:
    # The Edit tool's own result is agent activity, not an engine check.
    validations = _full_run_report()["validations"]
    assert all(v["command"].startswith("static checks") for v in validations)


def test_repaired_and_verified_run_reports_no_open_risks() -> None:
    # Honest: the final check passed and the changed file appears in its
    # evidence, so there is NOTHING left to flag — no risk is invented.
    assert _full_run_report()["open_risks"] == []


def test_attention_pointers_rank_failure_sites_before_changed_files() -> None:
    pointers = _full_run_report()["attention_pointers"]
    assert pointers[0]["target"] == "app.py:3"
    assert pointers[0]["rank"] == 1
    assert "failing" in pointers[0]["why"]
    targets = [p["target"] for p in pointers]
    assert "app.py" in targets
    assert targets.index("app.py:3") < targets.index("app.py")
    assert [p["rank"] for p in pointers] == list(range(1, len(pointers) + 1))


def test_rubric_mapping_maps_outcome_onto_goal_and_acceptance_bullets() -> None:
    rubric = _full_run_report()["rubric_mapping"]
    assert rubric[0]["status"] == "met"
    # The goal moved from this row's CRITERION to its EVIDENCE. The row now says
    # "the run finished without error", because a zero exit code is all it can
    # actually see -- restating the whole ask beside "met" claimed every
    # requirement in it had been satisfied. The property this line protects is
    # unchanged: the rubric is bound to THIS conversation's goal.
    assert rubric[0]["criterion"] == "the run finished without error"
    assert "Build the widget." in rubric[0]["evidence"]
    assert "1 file(s) changed" in rubric[0]["evidence"]
    bullets = {entry["criterion"]: entry["status"] for entry in rubric[1:]}
    assert bullets == {
        "render the widget header": "unverified",
        "persist widget state": "unverified",
    }


def test_a_prose_goal_still_reports_its_requirements_as_unverified() -> None:
    """A goal nobody wrote as a checklist must not come back entirely met.

    ``_extract_criteria`` only matches bullet lines, so a goal typed as prose
    yields no sub-criteria and the rubric was a single "met" whose criterion
    text restated every requirement in the goal. Read by a person, that says
    each one was checked. Nothing checked any of them.

    Observed on a real run: this exact goal produced one rubric line, status
    ``met``, evidence ``1 file(s) changed; engine checks: 2 passed, 0 failed``
    -- while the browser smoke check inside those two had recorded "the pause
    may not have engaged". The verdict outran what any check examined.

    The point of the assertion is reachability: for a prose goal the
    ``unverified`` status was not merely absent, it was IMPOSSIBLE, so a clean
    rubric was guaranteed rather than earned.
    """

    report = build_run_report(
        goal=(
            "Build a single-page countdown timer in index.html. It counts down from 60 "
            "seconds, shows the remaining time in large text, and has Start, Pause and "
            "Reset buttons that all work."
        ),
        transcript=_FULL_RUN_TRANSCRIPT,
        changed_files=["index.html"],
        returncode=0,
        ok=True,
        outcome="completed",
        reason="1 file(s) changed",
    )
    rubric = report["rubric_mapping"]
    assert rubric[0]["status"] == "met"  # the RUN completed; that part is true
    statuses = [entry["status"] for entry in rubric]
    assert "unverified" in statuses, (
        f"a prose goal reported no unverified requirement: {rubric}"
    )
    unverified = next(entry for entry in rubric if entry["status"] == "unverified")
    # It must say WHY, not just carry the word.
    assert "not" in unverified["evidence"].lower()


def test_the_prose_catch_all_does_not_claim_the_run_passed() -> None:
    """The honest line must stay honest on a run that failed.

    Caught live rather than in review: a run rejected for an unsupported model
    id exited 1 and mapped ``not_met``, and the catch-all underneath it still
    read "the run finished and its engine checks passed". It was a canned
    sentence about the success case, not a reading of this run -- the same
    overclaiming this whole entry exists to prevent.
    """

    report = build_run_report(
        goal="Build a tip calculator that updates the total as you type.",
        transcript='{"fc":"error","text":"agent loop exited 1"}',
        changed_files=[],
        returncode=1,
        ok=False,
        outcome="failed",
        reason="exited 1",
    )
    rubric = report["rubric_mapping"]
    assert rubric[0]["status"] == "not_met"
    catch_all = next(entry for entry in rubric if entry["status"] == "unverified")
    lowered = catch_all["evidence"].lower()
    assert "passed" not in lowered, f"claims a pass on a failed run: {catch_all['evidence']}"
    assert "finished" not in lowered, f"claims completion on a failed run: {catch_all['evidence']}"


def test_a_goal_with_bullets_does_not_also_get_the_prose_catch_all() -> None:
    """The other direction: when requirements WERE extracted, say nothing extra.

    The catch-all exists because no requirement could be named. A bulleted goal
    names them, and each already reports its own ``unverified`` line -- adding a
    second, vaguer one would be noise that makes the honest lines easier to skip.
    """

    rubric = _full_run_report()["rubric_mapping"]
    criteria = [entry["criterion"] for entry in rubric]
    assert criteria[1:] == ["render the widget header", "persist widget state"]


def test_failed_run_reports_honest_risks_and_not_met_rubric() -> None:
    transcript = "\n".join(
        [
            '{"fc":"tool","name":"run","text":"static checks: syntax + parse + open (app.py)"}',
            '{"fc":"tool_result","text":"exit 1\\napp.py:3 SyntaxError","is_error":true}',
            '{"fc":"error","text":"build timed out after 300s — process killed"}',
        ]
    )
    report = build_run_report(
        goal="Fix the widget",
        transcript=transcript,
        changed_files=["app.py"],
        returncode=1,
        ok=False,
        outcome="failed",
        reason="exited 1",
    )
    risks = {r["risk"] for r in report["open_risks"]}
    assert "run exited non-zero (1)" in risks
    assert "final verification failed" in risks
    assert "files changed without a matching passing validation" in risks
    assert "error surfaced during the run" in risks
    assert report["rubric_mapping"][0]["status"] == "not_met"
    assert report["attempts"][0]["errors"] == ["build timed out after 300s — process killed"]


def test_refusal_reason_surfaces_as_open_risk() -> None:
    report = build_run_report(
        goal="Do the thing",
        transcript='{"fc":"say","text":"partial"}',
        changed_files=["half.py"],
        returncode=0,
        ok=False,
        outcome="failed",
        reason="Claude could not complete the requested action after leaving partial file changes",
    )
    risks = {r["risk"] for r in report["open_risks"]}
    assert "the agent reported it could not complete the action" in risks
    assert "changed files were never validated" in risks


def test_empty_run_produces_honest_minimal_report_with_no_invented_content() -> None:
    report = build_run_report(transcript="", returncode=0, ok=False, outcome="noop", reason="no change made")
    assert report["attempts"] == []
    assert report["validations"] == []
    assert report["attention_pointers"] == []
    assert report["rubric_mapping"] == []  # no goal -> nothing to map, nothing invented
    risks = {r["risk"] for r in report["open_risks"]}
    assert risks == {"no run activity was recorded", "run made no changes"}


def test_unconfirmed_exit_is_an_open_risk() -> None:
    report = build_run_report(transcript="", returncode=None, ok=False, outcome="failed", reason="unconfirmed")
    assert any(r["risk"] == "process exit could not be confirmed" for r in report["open_risks"])


def test_parse_forge_events_skips_noise_and_deltas() -> None:
    transcript = "\n".join(
        [
            "plain CLI echo line",
            "{not json",
            '{"fc":"say","text":"to","delta":true}',
            '{"fc":"say","text":"token stream complete"}',
            '{"no_fc_key":true}',
        ]
    )
    events = parse_forge_events(transcript)
    assert events == [{"fc": "say", "text": "token stream complete"}]


def test_report_from_dispatch_result_reads_cli_result_shape() -> None:
    result = SimpleNamespace(
        ok=True,
        reason="dispatched via claude CLI (1 file(s) changed; engine checks passed)",
        returncode=0,
        changed_files=["thomas/app.py"],
        stdout_tail='{"fc":"final","text":"done"}',
    )
    report = report_from_dispatch_result(result, goal="Ship it")
    assert tuple(sorted(report)) == tuple(sorted(REPORT_SECTIONS))
    assert report["rubric_mapping"][0]["status"] == "met"
    assert report["attention_pointers"][0]["target"] == "thomas/app.py"


# ── Seam: the server completion payload carries the report ──


class _EmptyStdout:
    async def readline(self) -> bytes:
        return b""


class _FinishedProcess:
    returncode = 0
    stdout = _EmptyStdout()

    async def wait(self) -> int:
        return 0


def test_completion_payload_and_persisted_turn_carry_the_report(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    forge_code_store.append_user_turn(repo, conversation["id"], "Build the report widget")
    transcript = repo / "run-transcript.txt"
    transcript.write_text(_FULL_RUN_TRANSCRIPT + "\n", encoding="utf-8")
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda *_args: ["app.py"])

    async def _run() -> None:
        result = await evolve_agent_runtime._drain_and_record(
            _FinishedProcess(),
            transcript,
            repo,
            conversation["id"],
            "test-model",
            {},
            web.Application(),
            run_id="run-report-seam",
        )
        assert result["ok"] is True
        report = result["report"]
        assert tuple(sorted(report)) == tuple(sorted(REPORT_SECTIONS))
        # The rubric maps the run onto the goal the USER gave this conversation.
        # Carried in the evidence rather than the criterion since the first row
        # stopped restating the goal as something "met" -- the binding to this
        # conversation's goal is what this asserts, and that is unchanged.
        assert "Build the report widget" in report["rubric_mapping"][0]["evidence"]
        assert len(report["attempts"]) == 2
        assert len(report["validations"]) == 2
        # Persisted turn re-renders the same report after a reload.
        saved = forge_code_store.load_conversation(repo, conversation["id"])
        assert saved["turns"][-1]["report"] == report

    asyncio.run(_run())


def test_append_agent_turn_without_report_stays_backward_compatible(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    persisted = forge_code_store.append_agent_turn(
        repo,
        conversation["id"],
        model="test-model",
        transcript="",
        changed_files=[],
        returncode=0,
        ok=False,
        noop=True,
        reason="no change made",
    )
    assert persisted is not None
    assert "report" not in persisted["turns"][-1]
