"""A queued or refused self-continuation cannot spend a run from Autopilot's fuse."""

from __future__ import annotations

import pytest

from thomas.server.routes import evolve_agent_autopilot as ap

FAILED = {
    "role": "agent",
    "outcome": "failed",
    "reason": "worker exited 2",
    "ok": False,
    "transcript": '{"fc":"reason","text":"Inspecting the requested change"}',
}
CONTINUE = {"role": "user", "text": ap.CONTINUATION_PREFIX + " keep going"}
RUNS = 12  # a long run of self-continuations; there is no limit that it could reach


def _conversation(turns: list[dict]) -> dict:
    return {"settings": {"requested": {"autonomy_level": 5}}, "turns": turns}


def test_fragmented_quota_refusal_does_not_spend_a_run() -> None:
    import json

    transcript = "\n".join(
        json.dumps({"fc": "say", "source": "model", "delta": True, "text": piece})
        for piece in ["You've hit your ", "session limit"]
    )
    turns = [CONTINUE, {**FAILED, "transcript": transcript, "diff": ""}]
    assert ap._continuation_count(turns) == 0


@pytest.mark.parametrize("banner_source", [None, "process"])
@pytest.mark.parametrize("refusal", ["You've hit your session limit", "Not logged in. Please run /login"])
def test_process_banner_before_fragmented_refusal_does_not_count(banner_source, refusal) -> None:
    import json

    events = [
        {"fc": "say", "text": "CLI ready\n", "source": banner_source},
        {"fc": "say", "text": refusal[:8], "source": "model"},
        {"fc": "say", "text": refusal[8:], "source": "model"},
    ]
    attempt = {**FAILED, "transcript": "\n".join(map(json.dumps, events)), "diff": ""}
    assert ap._continuation_count([CONTINUE, attempt]) == 0


def test_queued_continuations_are_not_counted_as_runs() -> None:
    turns = [{"role": "user", "text": "make a game"}, FAILED]
    turns.extend([CONTINUE] * (RUNS + 3))
    assert ap._continuation_count(turns) == 0
    assert ap.decide(_conversation(turns)).action == "continue"


def test_only_started_runs_count_and_every_ending_is_still_explained() -> None:
    turns = [{"role": "user", "text": "make a game"}, FAILED]
    for number in range(RUNS - 1):
        turns.extend((CONTINUE, {**FAILED, "reason": f"run {number} exited"}))
    turns.extend((CONTINUE, CONTINUE))  # both requests were queued, neither ran
    assert ap._continuation_count(turns) == RUNS - 1
    assert ap.decide(_conversation(turns)).action == "continue"
    turns.append({**FAILED, "reason": "last run exited"})
    decision = ap.decide(_conversation(turns))
    assert decision.action == "continue"  # twelve runs in, it still carries on
    explanation = ap._cap_explanation(turns)
    assert f"{RUNS} self-continuation runs" in explanation
    for number in range(RUNS - 1):
        assert f"run {number} exited" in explanation
    assert "last run exited" in explanation
    assert explanation.count("failed:") == RUNS


def test_the_ledger_helper_still_records_each_counted_run_separately(monkeypatch) -> None:
    issues = []
    monkeypatch.setattr(ap, "record_issue", lambda **issue: issues.append(issue))
    turns = [{"role": "user", "text": "make a game"}, FAILED]
    for number in range(RUNS):
        turns.extend((CONTINUE, {**FAILED, "reason": f"ending {number}"}))
    ap._record_cap({"turns": turns}, "project-id", ap._cap_explanation(turns))
    assert len(issues) == RUNS + 1
    assert issues[0]["kind"] == "autopilot_cap"
    for number, issue in enumerate(issues[1:]):
        assert issue["kind"] == "autopilot_cap_run"
        assert issue["context"]["run"] == str(number + 1)
        assert issue["context"]["outcome"] == "failed"
        assert issue["context"]["reason"] == f"ending {number}"


def test_claude_quota_resume_preserves_the_budget_and_counts_executed_work() -> None:
    turns = [
        {"role": "user", "text": "make a game"},
        CONTINUE,
        FAILED,
        CONTINUE,
        {**FAILED, "transcript": '{"fc":"error","text":"usage limit"}'},
        {"role": "user", "text": f"{ap.CONTINUATION_PREFIX}: resuming after the Claude plan's usage limit"},
        {**FAILED, "reason": "quota resume ended"},
    ]
    assert ap._continuation_count(turns) == 2
    assert "quota resume ended" in ap._cap_explanation(turns)


def test_steering_in_restart_or_resume_resets_the_previous_budget() -> None:
    from thomas.server.routes.autopilot_goal import STEER_LINE

    for text in (
        f"{ap.RESUME_PREFIX} toward the goal: make a game\n\n{STEER_LINE}make it blue",
        f"{ap.RESTART_PREFIX} {ap.RESTART_MARK}{CONTINUE['text']}\n\n{STEER_LINE}make it blue",
    ):
        turns = [CONTINUE, FAILED, {"role": "user", "text": text}, FAILED]
        assert ap._continuation_count(turns) == 0
        turns.extend((CONTINUE, {**FAILED, "reason": "blue run ended"}))
        assert ap._continuation_count(turns) == 1
        assert "worker exited 2" not in ap._cap_explanation(turns)


def test_new_instruction_resets_count_and_restart_keeps_the_run() -> None:
    turns = [
        {"role": "user", "text": "make a game"},
        FAILED,
        CONTINUE,
        FAILED,
        {"role": "user", "text": "actually make it blue"},
        FAILED,
        {"role": "user", "text": ap.RESTART_PREFIX + " carrying on " + ap.CONTINUATION_PREFIX + " again"},
        FAILED,
        CONTINUE,
        {**FAILED, "reason": "new run ended"},
    ]
    assert ap._continuation_count(turns) == 1
    assert "new run ended" in ap._cap_explanation(turns)
    assert "worker exited 2" not in ap._cap_explanation(turns)


def test_restart_of_a_stopped_continuation_does_not_spend_two_runs() -> None:
    turns = [
        {"role": "user", "text": "make a game"},
        FAILED,
        CONTINUE,
        {**FAILED, "outcome": "stopped", "reason": "server restarted"},
        {"role": "user", "text": ap.RESTART_PREFIX + " " + ap.RESTART_MARK + CONTINUE["text"]},
        {**FAILED, "reason": "resumed run ended"},
    ]
    assert ap._continuation_count(turns) == 2
    assert "server restarted" in ap._cap_explanation(turns)
    assert "resumed run ended" in ap._cap_explanation(turns)


def test_restart_of_a_queued_continuation_counts_only_the_run_that_started() -> None:
    turns = [
        {"role": "user", "text": "make a game"},
        FAILED,
        CONTINUE,
        {"role": "user", "text": ap.RESTART_PREFIX + " " + ap.RESTART_MARK + CONTINUE["text"]},
        {**FAILED, "reason": "resumed run ended"},
    ]
    assert ap._continuation_count(turns) == 1
    assert "resumed run ended" in ap._cap_explanation(turns)


def test_done_check_is_self_work_not_a_new_instruction() -> None:
    turns = [
        {"role": "user", "text": "make a game"},
        CONTINUE,
        FAILED,
        {"role": "user", "text": ap.REVIEW_PREFIX + " make a game"},
        {**FAILED, "reason": "done check found a missing feature"},
    ]
    assert ap._continuation_count(turns) == 2
    assert "done check found a missing feature" in ap._cap_explanation(turns)


def test_restart_of_a_first_run_does_not_count_as_a_continuation() -> None:
    turns = [
        {"role": "user", "text": "make a game"},
        {"role": "user", "text": ap.RESTART_PREFIX + " " + ap.RESTART_MARK + "make a game"},
        FAILED,
    ]
    assert ap._continuation_count(turns) == 0


@pytest.mark.parametrize("resume", [ap.RESUME_PREFIX, ap.TROUBLE_RESUME_PREFIX])
@pytest.mark.parametrize("is_continuation", [False, True])
def test_restarting_a_resume_preserves_its_original_budget_context(resume, is_continuation) -> None:
    turns = [CONTINUE if is_continuation else {"role": "user", "text": "make a game"}]
    turns.append({**FAILED, "transcript": '{"fc":"error","text":"usage limit reached"}'})
    message = resume + " carry on"
    turns.extend(
        [
            {"role": "user", "text": message},
            {"role": "user", "text": ap.RESTART_PREFIX + ap.RESTART_MARK + message},
            {**FAILED, "run_id": "resumed"},
        ]
    )
    assert ap._continuation_count(turns) == int(is_continuation)


def test_executed_reload_yield_keeps_its_count_and_ending() -> None:
    from thomas.server.routes.autopilot_continuation_history import continuation_history

    turns = [
        CONTINUE,
        {**FAILED, "run_id": "yielded", "outcome": "reload_yielded", "reason": "yielded for reload"},
        {"role": "user", "text": ap.RESTART_PREFIX + ap.RESTART_MARK + CONTINUE["text"]},
        {**FAILED, "run_id": "resumed"},
    ]
    history = continuation_history({"turns": turns})
    assert history["count"] == 2
    assert history["runs"][0]["reason"] == "yielded for reload"
    assert history["runs"][1]["run_id"] == "resumed"


def test_saved_startup_failures_are_not_counted_as_runs() -> None:
    import json

    for transcript in (
        "usage: thomas-forge-code-runner: invalid choice",
        "Traceback: module could not be imported",
        json.dumps({"fc": "error", "text": "not logged in"}),
        json.dumps({"fc": "meta", "ok": False, "reason": "machine busy"}),
        json.dumps({"fc": "say", "text": "usage: invalid runner configuration"}),
        json.dumps({"fc": "say", "text": "runner banner", "source": "process_output"}),
        "",
    ):
        turns = [{"role": "user", "text": "make a game"}, FAILED]
        for _ in range(RUNS + 3):
            turns.extend([CONTINUE, {**FAILED, "transcript": transcript}])
        assert ap._continuation_count(turns) == 0, transcript
        # Authentication may correctly pause the project; nothing here can end it.
        assert ap.decide(_conversation(turns)).action in {"continue", "wait"}, transcript


@pytest.mark.parametrize("executed", [(False, False), (True, False), (False, True), (True, True)])
def test_stall_fuse_requires_two_executed_runs(executed: tuple[bool, bool]) -> None:
    turns = [{"role": "user", "text": "make a game"}]
    for ran in executed:
        turn = {
            **FAILED,
            "transcript": FAILED["transcript"] if ran else '{"fc":"error","text":"runner could not start"}',
            "changed_files": [],
            "report": {"open_risks": [{"risk": ap._NO_RUN_ACTIVITY_RISK}]},
        }
        turns.extend([CONTINUE, turn])
    assert ap._continuation_count(turns) == sum(executed)
    assert ap.decide(_conversation(turns)).action == ("stall" if all(executed) else "continue")


@pytest.mark.parametrize("instruction", ["make it blue", ap.CONTINUATION_PREFIX + "\n\n{steer}make it blue"])
def test_new_instruction_does_not_inherit_a_previous_runs_stall(instruction: str) -> None:
    from thomas.server.routes.autopilot_goal import STEER_LINE

    crash = {
        **FAILED,
        "changed_files": [],
        "report": {"open_risks": [{"risk": ap._NO_RUN_ACTIVITY_RISK}]},
    }
    turns = [
        {"role": "user", "text": "make a game"},
        crash,
        {"role": "user", "text": instruction.format(steer=STEER_LINE)},
        crash,
    ]
    assert ap._continuation_count(turns) == 0
    assert ap.decide(_conversation(turns)).action == "continue"
    turns.extend([CONTINUE, crash])
    assert ap._continuation_count(turns) == 1
    assert ap.decide(_conversation(turns)).action == "stall"


def test_stall_report_names_the_executed_runs_that_triggered_it(monkeypatch) -> None:
    crash = {**FAILED, "changed_files": [], "report": {"open_risks": [{"risk": ap._NO_RUN_ACTIVITY_RISK}]}}
    turns = [
        CONTINUE,
        {**crash, "run_id": "first", "reason": "worker exited 2"},
        CONTINUE,
        {**FAILED, "reason": "runner could not start", "transcript": ""},
        CONTINUE,
        {**crash, "run_id": "second", "reason": "worker exited 3"},
    ]
    assert ap.decide(_conversation(turns)).action == "stall"
    recorded = []
    monkeypatch.setattr(ap, "record_issue", lambda **issue: recorded.append(issue))
    ap._record_stall(_conversation(turns), "project")
    assert recorded[0]["context"]["reason_1"] == "worker exited 2"
    assert recorded[0]["context"]["reason_2"] == "worker exited 3"


def test_actual_work_counts_even_when_it_ends_in_an_error_or_no_files_change() -> None:
    import json

    for event in (
        {"fc": "say", "text": "Inspecting the game", "source": "model"},
        {"fc": "tool_result", "name": "fs.read_file", "ok": False},
        {"fc": "reason", "text": "Checking the collision logic"},
        {"fc": "tool", "name": "fs.read_file"},
        {"fc": "final", "text": "The existing game passes its checks"},
    ):
        turns = [CONTINUE, {**FAILED, "transcript": json.dumps(event)}]
        assert ap._continuation_count(turns) == 1, event
    # A dirty worktree can predate the launch: paths alone must not prove execution.
    assert ap._continuation_count([CONTINUE, {**FAILED, "transcript": "", "changed_files": ["game.js"]}]) == 0


def test_quota_resume_counts_only_when_it_does_work() -> None:
    turns = [CONTINUE, {**FAILED, "transcript": '{"fc":"error","text":"usage limit reached"}'}]
    turns.extend([{"role": "user", "text": ap.RESUME_PREFIX + " carry on"}, FAILED])
    assert ap._continuation_count(turns) == 1


def test_history_preserves_each_runs_identity_and_ending_without_mutating_it() -> None:
    from thomas.server.routes.autopilot_continuation_history import continuation_history

    turn = {**FAILED, "run_id": "run-2", "ts": "2026-10-01T17:03:00Z"}
    conversation = _conversation([CONTINUE, {**FAILED, "transcript": ""}, CONTINUE, turn])
    history = continuation_history(conversation)
    assert history == {
        "count": 1,
        "runs": [{"run": 1, "run_id": "run-2", "ts": turn["ts"], "outcome": "failed", "reason": "worker exited 2"}],
    }
    assert "continuation_history" not in conversation


def test_startup_receipt_cannot_charge_an_unrelated_agent_turn() -> None:
    turns = [CONTINUE, {**FAILED, "transcript": ""}, FAILED]
    assert ap._continuation_count(turns) == 0


def test_run_id_is_counted_once_even_if_its_ending_is_repeated() -> None:
    turn = {**FAILED, "run_id": "same-run"}
    assert ap._continuation_count([CONTINUE, turn, CONTINUE, turn]) == 1


@pytest.mark.parametrize("flag", ["error", "isApiErrorMessage", "is_api_error_message"])
@pytest.mark.parametrize("prior_work", [False, True])
@pytest.mark.parametrize(
    "pieces", [("API Error: ", "503 service unavailable"), ("API", " ", "Error: 503 service unavailable")]
)
def test_streamed_provider_errors_do_not_prove_execution(flag: str, prior_work: bool, pieces: tuple[str, ...]) -> None:
    import json

    from thomas.forge.anvil.forge_event_stream import ClaudeStreamTranslator
    from thomas.server.routes.autopilot_continuation_history import actually_ran

    translator = ClaudeStreamTranslator()
    events = []
    if prior_work:
        events.extend(
            translator(
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "I checked it."}]}})
            )
        )
    for piece in pieces:
        events.extend(
            translator(
                json.dumps(
                    {
                        "type": "stream_event",
                        "event": {
                            "type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": piece},
                        },
                    }
                )
            )
        )
    events.extend(
        translator(
            json.dumps(
                {
                    "type": "assistant",
                    flag: True,
                    "message": {"content": [{"type": "text", "text": "API Error: 503 service unavailable"}]},
                }
            )
        )
    )
    assert actually_ran({"transcript": "\n".join(json.dumps(event) for event in events)}) is prior_work


@pytest.mark.parametrize("prior_work", [False, True])
@pytest.mark.parametrize("refusal", ["Not logged in", "You've hit your session limit"])
@pytest.mark.parametrize("streamed", [False, True])
def test_terminal_refusal_preserves_earlier_execution(prior_work: bool, refusal: str, streamed: bool) -> None:
    import json

    from thomas.forge.anvil.forge_event_stream import ClaudeStreamTranslator
    from thomas.server.routes.autopilot_continuation_history import actually_ran

    translator = ClaudeStreamTranslator()
    events = []
    if prior_work:
        events.extend(
            translator(
                json.dumps(
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Inspecting the game"}]}}
                )
            )
        )
    if streamed:
        for piece in (refusal[:5], refusal[5:]):
            events.extend(
                translator(
                    json.dumps(
                        {
                            "type": "stream_event",
                            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}},
                        }
                    )
                )
            )
    else:
        events.extend(
            translator(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": refusal}]}}))
        )
    events.extend(translator(json.dumps({"type": "result", "is_error": True, "result": refusal})))
    assert actually_ran({"transcript": "\n".join(map(json.dumps, events))}) is prior_work


def test_trouble_resume_of_the_first_request_is_not_a_self_continuation() -> None:
    turns = [
        {"role": "user", "text": "make a game"},
        FAILED,
        {"role": "user", "text": ap.TROUBLE_RESUME_PREFIX + " toward the goal: make a game"},
        FAILED,
    ]
    assert ap._continuation_count(turns) == 0


def test_resume_after_an_unstarted_continuation_still_counts_its_execution() -> None:
    turns = [
        CONTINUE,
        {**FAILED, "transcript": "", "outcome": "provider_down"},
        {"role": "user", "text": ap.TROUBLE_RESUME_PREFIX + " toward the goal: make a game"},
        FAILED,
    ]
    assert ap._continuation_count(turns) == 1


def test_execution_evidence_uses_the_stores_legacy_transcript_shapes() -> None:
    from thomas.server.routes.autopilot_continuation_history import continuation_history

    transcript = FAILED["transcript"]
    for persisted in (transcript.splitlines(), list(transcript)):
        history = continuation_history({"turns": [CONTINUE, {**FAILED, "transcript": persisted}]})
        assert history["count"] == 1
        assert history["runs"][0]["reason"] == "worker exited 2"


def test_duplicate_receipt_keeps_the_recorded_ending_when_new_fields_are_empty() -> None:
    from thomas.server.routes.autopilot_continuation_history import continuation_history

    first = {**FAILED, "run_id": "ran-once"}
    receipt = {**first, "transcript": "", "outcome": "", "reason": ""}
    history = continuation_history({"turns": [CONTINUE, first, receipt]})
    assert history["count"] == 1
    assert history["runs"][0]["outcome"] == "failed"
    assert history["runs"][0]["reason"] == "worker exited 2"


def test_executed_runs_never_block_a_quota_resume_or_repair(monkeypatch) -> None:
    turns = [item for _ in range(RUNS) for item in (CONTINUE, FAILED)]
    pauses = {
        "quota_pause": ap.autopilot_park.QuotaPause("Anthropic", 4e9, True),
        "trouble_pause": ap.autopilot_park.TroublePause("Anthropic", 4e9, "overloaded"),
    }
    for pause, made in pauses.items():
        with monkeypatch.context() as patch:
            patch.setattr(ap.autopilot_park, pause, lambda *args, _made=made, **kwargs: _made)
            assert ap.decide(_conversation(turns)).action == "wait", pause
    monkeypatch.setattr(ap.thomas_project, "repair_due", lambda conversation: {"round": 1})
    assert ap.decide(_conversation(turns)).action == "repair"


def test_a_successful_final_review_is_done_after_many_runs() -> None:
    turns = [item for _ in range(RUNS - 1) for item in (CONTINUE, FAILED)]
    turns.extend(
        (
            {"role": "user", "text": ap.REVIEW_PREFIX + " check it"},
            {**FAILED, "ok": True, "outcome": "completed", "changed_files": []},
        )
    )
    assert ap._continuation_count(turns) == RUNS
    assert ap.decide(_conversation(turns)).action == "done"


def test_provider_error_assistant_text_does_not_prove_execution() -> None:
    import json

    from thomas.forge.anvil.forge_event_stream import translate_claude_event

    for flag in ({"error": "rate_limit"}, {"isApiErrorMessage": True}, {"is_api_error_message": True}):
        event = {
            "type": "assistant",
            **flag,
            "message": {"content": [{"type": "text", "text": "Not available"}]},
        }
        streamed = {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Not available"}},
        }
        events = translate_claude_event(json.dumps(streamed)) + translate_claude_event(json.dumps(event))
        transcript = "\n".join(json.dumps(row) for row in events)
        assert ap._continuation_count([CONTINUE, {**FAILED, "transcript": transcript}]) == 0
        assert '"fc": "error"' in transcript


@pytest.mark.parametrize("streamed_refusal", [False, True])
@pytest.mark.parametrize("earlier_output", ["", "Not available", "I checked the implementation."])
def test_refusal_retracts_only_its_own_streamed_message(earlier_output, streamed_refusal) -> None:
    import json

    from thomas.forge.anvil.forge_event_stream import _StreamState, translate_claude_event

    state = _StreamState()
    events = []
    if earlier_output:
        events.extend(
            translate_claude_event(
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": earlier_output}]}}),
                state,
            )
        )
    if streamed_refusal:
        for piece in ("Not ", "available"):
            events.extend(
                translate_claude_event(
                    json.dumps(
                        {
                            "type": "stream_event",
                            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}},
                        }
                    ),
                    state,
                )
            )
    events.extend(
        translate_claude_event(
            json.dumps(
                {
                    "type": "assistant",
                    "error": "rate_limit",
                    "message": {"content": [{"type": "text", "text": "Not available"}]},
                }
            ),
            state,
        )
    )
    transcript = "\n".join(map(json.dumps, events))
    assert ap._continuation_count([CONTINUE, {**FAILED, "transcript": transcript}]) == int(bool(earlier_output))


@pytest.mark.parametrize("terminal", ["assistant", "result"])
@pytest.mark.parametrize("earlier_streamed_work", [False, True])
@pytest.mark.parametrize("streamed_refusal", [False, True])
def test_terminal_provider_refusal_only_retracts_pending_deltas(
    terminal, earlier_streamed_work, streamed_refusal
) -> None:
    import json

    from thomas.forge.anvil.forge_event_stream import ClaudeStreamTranslator

    translator = ClaudeStreamTranslator()
    events = []

    def send(message):
        events.extend(translator(json.dumps(message)))

    def stream():
        for piece in ("Not ", "available"):
            send(
                {
                    "type": "stream_event",
                    "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}},
                }
            )

    content = {"content": [{"type": "text", "text": "Not available"}]}
    if earlier_streamed_work:
        stream()
        send({"type": "assistant", "message": content})
    if streamed_refusal:
        stream()
    if terminal == "assistant":
        send({"type": "assistant", "error": "rate_limit", "message": content})
    send({"type": "result", "is_error": True, "subtype": "rate_limit_error", "result": "Not available"})
    transcript = "\n".join(map(json.dumps, events))
    assert ap._continuation_count([CONTINUE, {**FAILED, "transcript": transcript}]) == int(earlier_streamed_work)


def test_separate_genuine_speech_before_quota_refusal_still_counts() -> None:
    import json

    events = [{"fc": "say", "text": "I inspected the change.", "source": "model"}]
    events.extend(
        {"fc": "say", "text": piece, "source": "model", "delta": True}
        for piece in ["You've hit your ", "session limit"]
    )
    transcript = "\n".join(map(json.dumps, events))
    assert ap._continuation_count([CONTINUE, {**FAILED, "transcript": transcript}]) == 1


def test_done_checks_are_counted_as_runs_and_keep_earlier_endings() -> None:
    turns = [CONTINUE, FAILED]
    for index in range(11):
        turns.extend(
            [
                {"role": "user", "text": ap.REVIEW_PREFIX + " toward the goal: make a game"},
                {**FAILED, "run_id": f"review-{index}", "reason": f"review ended {index}"},
            ]
        )
    decision = ap.decide(_conversation(turns))
    assert ap._continuation_count(turns) == 12
    assert decision.action == "review"  # a failed done check is checked again, never capped
    explanation = ap._cap_explanation(turns)
    assert "worker exited 2" in explanation
    assert "review ended 10" in explanation


def test_quota_fragment_sources_do_not_change_execution_accounting() -> None:
    import json

    from thomas.server.routes.autopilot_continuation_history import actually_ran

    events = [
        {"fc": "say", "text": "You've hit your session limit", "source": "process"},
        {"fc": "say", "text": ". Try again later.", "source": "model"},
    ]
    assert not actually_ran({"transcript": "\n".join(json.dumps(event) for event in events)})


def test_duplicate_receipt_can_add_execution_and_refresh_its_ending() -> None:
    from thomas.server.routes.autopilot_continuation_history import continuation_history

    initial = {**FAILED, "run_id": "same-run", "transcript": ""}
    executed = {**FAILED, "run_id": "same-run"}
    latest = {**executed, "reason": "server restarted", "outcome": "interrupted", "transcript": ""}
    history = continuation_history({"turns": [CONTINUE, initial, executed, latest]})
    assert history["count"] == 1
    assert history["runs"][0]["reason"] == "server restarted"
    assert history["runs"][0]["outcome"] == "interrupted"


def test_duplicate_endings_keep_execution_evidence_for_the_stall_fuse() -> None:
    crashed = {**FAILED, "changed_files": [], "report": {"open_risks": [{"risk": "no run activity was recorded"}]}}
    turns = [
        CONTINUE,
        {**crashed, "run_id": "first"},
        {**crashed, "run_id": "first", "transcript": ""},
        CONTINUE,
        {**crashed, "run_id": "second"},
        {**crashed, "run_id": "second", "transcript": ""},
    ]
    assert ap._continuation_count(turns) == 2
    assert ap.decide(_conversation(turns)).action == "stall"


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize(
    "message",
    [
        "I fixed the not logged in handling and added regression coverage.",
        "The CLI says please run /login when the session expires.",
        "Not logged in handling is now fixed, and I added regression coverage.",
        "Please run /login handling tests before handing in the change.",
    ],
)
def test_model_discussion_of_a_login_failure_still_proves_execution(message, streamed) -> None:
    import json

    from thomas.forge.anvil.forge_event_stream import ClaudeStreamTranslator

    translator = ClaudeStreamTranslator()
    if streamed:
        output = {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": message}},
        }
    else:
        output = {"type": "assistant", "message": {"content": [{"type": "text", "text": message}]}}
    events = translator(json.dumps(output))
    transcript = "\n".join(map(json.dumps, events))
    assert ap._continuation_count([CONTINUE, {**FAILED, "transcript": transcript}]) == 1
    historical = json.dumps({"fc": "say", "source": "model", "text": message})
    assert ap._continuation_count([CONTINUE, {**FAILED, "transcript": historical}]) == 1


def test_restarted_original_instruction_resets_the_previous_goal_budget() -> None:
    from thomas.server.routes.autopilot_continuation_history import continuation_history
    from thomas.server.routes.autopilot_messages import RESTART_MARK, RESTART_PREFIX

    turns = [CONTINUE, FAILED]
    turns.append({"role": "user", "text": RESTART_PREFIX + RESTART_MARK + "Build something else"})
    turns.append({**FAILED, "run_id": "new-goal"})
    assert continuation_history({"turns": turns}) == {"count": 0, "runs": []}
    turns.extend([CONTINUE, {**FAILED, "run_id": "new-continuation"}])
    assert ap._continuation_count(turns) == 1
