"""Tests for the chat conversation fixes.

Covers:
1. Control intent guard (don't hijack normal conversation)
2. Response tone filter (less aggressive stripping)
3. Chat logger (pipeline event logging)
4. Training mode (behavior observation and flagging)
5. Integration tests (routing + control guard together)

Note: Quick reply tests that need aiohttp/server imports are skipped
when those dependencies aren't available.
"""

from __future__ import annotations

import json

# ===================================================================
# 1. Control Intent Guard Tests
# ===================================================================


class TestControlIntentGuard:
    """Verify that conversational messages are NOT hijacked by the control resolver."""

    def test_conversational_not_control_helper(self):
        """The _is_conversational_not_control helper works."""
        from thomas.models.chat_controls import _is_conversational_not_control

        # These are clearly conversational
        assert _is_conversational_not_control("Can you help me write a function?")
        assert _is_conversational_not_control("Please help me debug this error")
        assert _is_conversational_not_control("How do I set up a database connection?")
        assert _is_conversational_not_control("What is the best way to handle errors in Python?")
        assert _is_conversational_not_control("Could you explain how async/await works?")
        assert _is_conversational_not_control("Would you mind looking at my code?")

        # These mention control targets — should NOT be blocked
        assert not _is_conversational_not_control("Can you switch mode to thinking?")
        assert not _is_conversational_not_control("set mode to fast")
        assert not _is_conversational_not_control("full auto")

    def test_normal_question_not_control(self):
        """A normal 'can you help me' should NOT be treated as a control request."""
        from thomas.models.chat_controls import resolve_ui_control_request

        result = resolve_ui_control_request("Can you help me write a function?")
        assert result is None, "Normal question was wrongly intercepted as control"

    def test_please_help_not_control(self):
        """'Please help me with X' should NOT trigger control."""
        from thomas.models.chat_controls import resolve_ui_control_request

        result = resolve_ui_control_request("Please help me debug this error")
        assert result is None, "'Please help' was wrongly intercepted"

    def test_i_want_help_not_control(self):
        """'I want to build X' should NOT trigger control."""
        from thomas.models.chat_controls import resolve_ui_control_request

        result = resolve_ui_control_request("I want to build a web scraper")
        assert result is None, "'I want to build' was wrongly intercepted"

    def test_what_question_not_control(self):
        """'What is X?' should NOT trigger control."""
        from thomas.models.chat_controls import resolve_ui_control_request

        result = resolve_ui_control_request("What is the best way to handle errors in Python?")
        assert result is None, "What question was wrongly intercepted"

    def test_how_question_not_control(self):
        """'How do I X?' should NOT trigger control."""
        from thomas.models.chat_controls import resolve_ui_control_request

        result = resolve_ui_control_request("How do I set up a database connection?")
        assert result is None, "How question was wrongly intercepted"

    def test_actual_mode_switch_still_works(self):
        """Actual mode switch commands should still work."""
        from thomas.models.chat_controls import resolve_ui_control_request

        result = resolve_ui_control_request("set mode to thinking")
        assert result is not None, "Legitimate mode switch was blocked"
        assert result.patch.get("mode") == "thinking"

    def test_actual_theme_switch_still_works(self):
        """Theme switches should still work."""
        from thomas.models.chat_controls import resolve_ui_control_request

        result = resolve_ui_control_request("switch theme to dark")
        assert result is not None, "Legitimate theme switch was blocked"
        settings = result.patch.get("settings", {})
        assert settings.get("theme") == "dark"

    def test_autonomy_shorthand_still_works(self):
        """Autonomy shorthands like 'full auto' should still work."""
        from thomas.models.chat_controls import resolve_ui_control_request

        result = resolve_ui_control_request("full auto")
        assert result is not None, "Autonomy shorthand was blocked"

    def test_mode_switch_still_works(self):
        """'switch mode to fast' should be treated as control."""
        from thomas.models.chat_controls import resolve_ui_control_request

        result = resolve_ui_control_request("switch mode to fast")
        assert result is not None

    def test_could_you_explain_not_control(self):
        """'Could you explain how X works?' should NOT be control."""
        from thomas.models.chat_controls import resolve_ui_control_request

        result = resolve_ui_control_request("Could you explain how async/await works in Python?")
        assert result is None

    def test_bulk_normal_messages_not_intercepted(self):
        """Various normal sentences should flow through to the LLM."""
        from thomas.models.chat_controls import resolve_ui_control_request

        normal_messages = [
            "Can you help me understand recursion?",
            "Please write me a Python script",
            "I want to learn about machine learning",
            "Could you explain how databases work?",
            "Would you mind looking at my code?",
            "How does the internet work?",
            "What are the best practices for API design?",
            "Can you show me an example of a decorator?",
        ]

        for msg in normal_messages:
            result = resolve_ui_control_request(msg)
            assert result is None, f"Normal message intercepted: '{msg}'"

    def test_bulk_control_commands_still_work(self):
        """Actual control commands should still be intercepted."""
        from thomas.models.chat_controls import resolve_ui_control_request

        control_messages = [
            ("set mode to thinking", "mode"),
            ("switch theme to dark", "settings"),
            ("full auto", "settings"),
            ("enable tool details", "settings"),
        ]

        for msg, expected_key in control_messages:
            result = resolve_ui_control_request(msg)
            assert result is not None, f"Control command not intercepted: '{msg}'"
            assert expected_key in result.patch, f"Expected '{expected_key}' in patch for: '{msg}'"


# ===================================================================
# 2. Response Tone Tests
# ===================================================================


class TestResponseToneFixes:
    """Verify that the tone filter is less aggressive."""

    def test_got_it_preserved(self):
        """'Got it' should NOT be stripped — it's natural."""
        from thomas.agent.response_tone import strip_robotic_opener

        text = "Got it, here's what I found."
        result, changed = strip_robotic_opener(text)
        assert "got it" in result.lower(), "Natural 'Got it' was stripped"

    def test_sure_preserved(self):
        """'Sure' should NOT be stripped — it's natural."""
        from thomas.agent.response_tone import strip_robotic_opener

        text = "Sure, let me take a look."
        result, changed = strip_robotic_opener(text)
        assert "sure" in result.lower(), "Natural 'Sure' was stripped"

    def test_understood_preserved(self):
        """'Understood' should NOT be stripped."""
        from thomas.agent.response_tone import strip_robotic_opener

        text = "Understood, here's the fix."
        result, changed = strip_robotic_opener(text)
        assert "understood" in result.lower(), "'Understood' was stripped"

    def test_certainly_still_stripped(self):
        """'Certainly!' IS robotic and should still be stripped."""
        from thomas.agent.response_tone import strip_robotic_opener

        text = "Certainly! I would be delighted to help."
        result, changed = strip_robotic_opener(text)
        assert not result.lower().startswith("certainly"), "'Certainly' was not stripped"
        assert changed is True

    def test_absolutely_still_stripped(self):
        """'Absolutely!' IS robotic and should still be stripped."""
        from thomas.agent.response_tone import strip_robotic_opener

        text = "Absolutely, let me help you with that."
        result, changed = strip_robotic_opener(text)
        assert not result.lower().startswith("absolutely"), "'Absolutely' was not stripped"
        assert changed is True

    def test_understood_preserved_in_mid_text(self):
        """'Understood' mid-sentence should be preserved."""
        from thomas.agent.response_tone import apply_social_tone_adjustments

        text = "I understood the issue. The fix is to update the config."
        result, changed = apply_social_tone_adjustments(text, prompt_text="fix my config")
        assert "understood" in result.lower(), "'understood' was wrongly stripped from mid-sentence"

    def test_code_output_not_mangled(self):
        """Code output should never have tone adjustments."""
        from thomas.agent.response_tone import apply_social_tone_adjustments

        text = "def hello():\n    print('hello world')"
        result, changed = apply_social_tone_adjustments(text, prompt_text="write a hello function")
        assert result == text, "Code output was mangled by tone filter"

    def test_newlines_preserved_in_tone_filter(self):
        """Newlines must NOT be collapsed to spaces by tone adjustments."""
        from thomas.agent.response_tone import apply_social_tone_adjustments

        text = "Here is the answer:\n\n1. First point\n2. Second point\n3. Third point"
        result, _ = apply_social_tone_adjustments(text, prompt_text="explain something")
        assert "\n" in result, "Newlines were collapsed by tone filter"
        assert "1. First point" in result
        assert "2. Second point" in result

    def test_newlines_preserved_in_workspace_strip(self):
        """Newlines must survive workspace reference stripping."""
        from thomas.agent.response_tone import strip_unprompted_workspace_references

        text = "I found the file in this workspace.\n\nHere are the results:\n- Item A\n- Item B"
        result, changed = strip_unprompted_workspace_references(text, prompt_text="show results")
        assert "\n" in result, "Newlines were destroyed by workspace stripping"
        assert "Item A" in result
        assert "Item B" in result

    def test_candidate_selection_extracts_reply(self):
        """Candidate selection block should extract the quoted final reply."""
        from thomas.agent.response_tone import strip_internal_reasoning_narration

        text = (
            "Selected candidate: 3\n"
            "Rationale (tone + safety): It's the warmest and clearest option, "
            "stays playful without endorsing insults, and redirects to friendly "
            "banter in a non-escalating way.\n"
            'Final selected reply: "Nice one, you got me grinning. What are we joking about next?"'
        )
        result, changed = strip_internal_reasoning_narration(text)
        assert changed, "Candidate selection block was not detected"
        assert "Selected candidate" not in result
        assert "Rationale" not in result
        assert "Nice one" in result, "Final reply was not extracted"
        assert "joking about next" in result

    def test_garbled_nospace_candidate_extracts_reply(self):
        """Garbled no-space candidate selection should still extract the quoted reply."""
        from thomas.agent.response_tone import strip_internal_reasoning_narration

        text = (
            "Selectedcandidate:3Rationale(tone+safety):It'sthewarmestandclearestoption,"
            "staysplayfulwithoutendorsinginsults,andredirectstofriendlybanterinannon-"
            'escalatingway.Finalselectedreply:"Nice one, you got me grinning. '
            'What are we joking about next?"'
        )
        result, changed = strip_internal_reasoning_narration(text)
        assert changed, "Garbled candidate block was not detected"
        assert "Selectedcandidate" not in result
        assert "Nice one" in result, "Final reply was not extracted from garbled text"

    def test_candidate_line_stripped(self):
        """Individual candidate/rationale lines should be stripped."""
        from thomas.agent.response_tone import strip_internal_reasoning_narration

        text = "candidate 2: This is a good option\nHere is my actual answer."
        result, changed = strip_internal_reasoning_narration(text)
        assert "candidate 2" not in result
        assert "actual answer" in result

    def test_scoring_rubric_lines_stripped(self):
        """Scoring rubric lines like 'Impact(30)|Feasibility(25)' should be stripped."""
        from thomas.agent.response_tone import strip_internal_reasoning_narration

        text = "Impact(30)|Feasibility(25)|StrategicFit(20)\nHere is the real answer."
        result, changed = strip_internal_reasoning_narration(text)
        # The rubric line should be gone
        assert "Impact(30)" not in result
        assert "real answer" in result

    def test_normal_text_not_stripped_as_reasoning(self):
        """Normal conversation that mentions 'candidate' should not be stripped."""
        from thomas.agent.response_tone import strip_internal_reasoning_narration

        text = "The candidate for the job has strong qualifications."
        result, changed = strip_internal_reasoning_narration(text)
        assert "candidate for the job" in result

    def test_codex_work_summary_garbled(self):
        """Exact garbled output from live Codex: no spaces, work-summary format."""
        from thomas.agent.response_tone import strip_internal_reasoning_narration

        # This is the EXACT output from the user's live Thomas session
        text = (
            "yo!what'sup?WhatcanIhelpyouwith?"
            "Finalresponsetouser:`yo!what'sup?WhatcanIhelpyouwith?`"
            "Demoscript:`bash#Inputyoyoyo#Expectedassistantoutput"
            "yo!what'sup?WhatcanIhelpyouwith?`"
            "Fileschanged/created:-None."
            "Tests:-Nocodechangesweremade,sonotestrunisrequired."
        )
        result, changed = strip_internal_reasoning_narration(text)
        assert changed, "Garbled work-summary was not detected"
        # Should NOT contain work-summary debris
        assert "Demoscript" not in result
        assert "Fileschanged" not in result
        assert "Tests:" not in result or "Nocodechanges" not in result
        # Should contain something recognizable as a greeting
        assert len(result) < len(text), "Garbled text was not trimmed"

    def test_codex_work_summary_spaced(self):
        """Spaced version of Codex work-summary format."""
        from thomas.agent.response_tone import strip_internal_reasoning_narration

        text = (
            "yo! what's up? What can I help you with?\n"
            "Final response to user: `yo! what's up? What can I help you with?`\n"
            "Demo script: `bash\n# Input\nyo yo yo\n`\n"
            "Files changed/created: - None.\n"
            "Tests: - No code changes were made, so no test run is required."
        )
        result, changed = strip_internal_reasoning_narration(text)
        assert changed, "Spaced work-summary was not detected"
        assert "Demo script" not in result
        assert "Files changed" not in result
        # The reply should be extracted
        assert "what's up" in result.lower() or "yo!" in result.lower()

    def test_codex_final_response_to_user_extracts(self):
        """'Final response to user: `reply`' should extract the backtick-quoted reply."""
        from thomas.agent.response_tone import strip_internal_reasoning_narration

        text = "Prefix garbage text. Final response to user: `Hey there! How can I help?` More garbage."
        result, changed = strip_internal_reasoning_narration(text)
        assert changed
        assert result == "Hey there! How can I help?"

    def test_garbled_nospace_detected(self):
        """Garbled text with no spaces should be detected and handled."""
        from thomas.agent.response_tone import _looks_garbled

        assert _looks_garbled("yo!what'sup?WhatcanIhelpyouwith?")
        assert not _looks_garbled("yo! what's up?")
        assert not _looks_garbled("Hello there, how are you doing today?")

    def test_work_summary_lines_stripped(self):
        """Individual work-summary lines should be stripped from multi-line output."""
        from thomas.agent.response_tone import strip_internal_reasoning_narration

        text = (
            "Here is my answer.\n"
            "Final response to user: Here is my answer.\n"
            "Demo script: bash echo hello\n"
            "Files changed/created: - None.\n"
            "Tests: - No test run needed."
        )
        result, changed = strip_internal_reasoning_narration(text)
        assert changed
        assert "Here is my answer" in result
        assert "Demo script" not in result
        assert "Files changed" not in result


# ===================================================================
# 3. Chat Logger Tests
# ===================================================================


class TestChatLogger:
    """Verify the chat pipeline logger works correctly."""

    def test_logger_creation(self):
        """Chat logger singleton exists."""
        from thomas.chat_logger import chat_logger

        assert chat_logger is not None

    def test_log_event(self):
        """Events are logged to the in-memory buffer."""
        from thomas.chat_logger import ChatEventKind, ChatLogger

        logger = ChatLogger()
        logger.configure(enabled=True)
        logger.set_session("test-session", "test-run")

        evt = logger.log_event(ChatEventKind.REQUEST_IN, {"text": "hello"})
        assert evt.kind == ChatEventKind.REQUEST_IN
        assert evt.session_id == "test-session"
        assert evt.data["text"] == "hello"

    def test_get_recent_events(self):
        """Recent events are retrievable from buffer."""
        from thomas.chat_logger import ChatEventKind, ChatLogger

        logger = ChatLogger()
        logger.configure(enabled=True)

        logger.log_event(ChatEventKind.REQUEST_IN, {"text": "hi"}, session_id="s1")
        logger.log_event(ChatEventKind.ROUTING, {"path": "casual"}, session_id="s1")
        logger.log_event(ChatEventKind.RESPONSE_OUT, {"text": "hey"}, session_id="s1")

        events = logger.get_recent_events(10)
        assert len(events) >= 3

    def test_get_session_events(self):
        """Events filtered by session ID."""
        from thomas.chat_logger import ChatEventKind, ChatLogger

        logger = ChatLogger()
        logger.configure(enabled=True)

        logger.log_event(ChatEventKind.REQUEST_IN, {"text": "a"}, session_id="s1")
        logger.log_event(ChatEventKind.REQUEST_IN, {"text": "b"}, session_id="s2")

        s1_events = logger.get_session_events("s1")
        assert all(e.session_id == "s1" for e in s1_events)

    def test_filter_by_kind(self):
        """Events can be filtered by kind."""
        from thomas.chat_logger import ChatEventKind, ChatLogger

        logger = ChatLogger()
        logger.configure(enabled=True)

        logger.log_event(ChatEventKind.REQUEST_IN, {"text": "a"})
        logger.log_event(ChatEventKind.ROUTING, {"path": "casual"})
        logger.log_event(ChatEventKind.REQUEST_IN, {"text": "b"})

        req_events = logger.get_recent_events(10, kind=ChatEventKind.REQUEST_IN)
        assert all(e.kind == ChatEventKind.REQUEST_IN for e in req_events)

    def test_event_to_json(self):
        """Events serialize to JSON."""
        from thomas.chat_logger import ChatEvent

        evt = ChatEvent(kind="test", session_id="s1", data={"key": "value"})
        j = evt.to_json()
        parsed = json.loads(j)
        assert parsed["kind"] == "test"
        assert parsed["data"]["key"] == "value"
        assert "ts" in parsed
        assert "iso" in parsed

    def test_observer_notified(self):
        """Observers receive events."""
        from thomas.chat_logger import ChatEventKind, ChatLogger

        logger = ChatLogger()
        logger.configure(enabled=True)

        received = []
        logger.add_observer(lambda e: received.append(e))

        logger.log_event(ChatEventKind.REQUEST_IN, {"text": "hi"})
        assert len(received) == 1
        assert received[0].kind == ChatEventKind.REQUEST_IN

    def test_observer_removal(self):
        """Observers can be removed."""
        from thomas.chat_logger import ChatEventKind, ChatLogger

        logger = ChatLogger()
        logger.configure(enabled=True)

        received = []
        cb = lambda e: received.append(e)
        logger.add_observer(cb)
        logger.log_event(ChatEventKind.REQUEST_IN, {"text": "a"})
        logger.remove_observer(cb)
        logger.log_event(ChatEventKind.REQUEST_IN, {"text": "b"})

        assert len(received) == 1  # only first event

    def test_summary(self):
        """Summary generation works."""
        from thomas.chat_logger import ChatEventKind, ChatLogger

        logger = ChatLogger()
        logger.configure(enabled=True)

        logger.log_event(ChatEventKind.REQUEST_IN, {}, session_id="s1")
        logger.log_event(ChatEventKind.ERROR, {}, session_id="s1")
        logger.log_event(ChatEventKind.TRAINING_FLAG, {}, session_id="s1")

        summary = logger.summary("s1")
        assert summary["total_events"] >= 3
        assert summary["errors"] >= 1
        assert summary["training_flags"] >= 1

    def test_buffer_max_size(self):
        """Buffer doesn't grow unbounded."""
        from thomas.chat_logger import ChatEventKind, ChatLogger

        logger = ChatLogger()
        logger.configure(enabled=True)
        logger._max_buffer = 10

        for i in range(20):
            logger.log_event(ChatEventKind.REQUEST_IN, {"i": i})

        assert len(logger._event_buffer) <= 10

    def test_disabled_logger_still_returns_event(self):
        """Disabled logger returns event without recording."""
        from thomas.chat_logger import ChatEventKind, ChatLogger

        logger = ChatLogger()
        logger.configure(enabled=False)

        evt = logger.log_event(ChatEventKind.REQUEST_IN, {"text": "test"})
        assert evt.kind == ChatEventKind.REQUEST_IN
        assert len(logger._event_buffer) == 0


# ===================================================================
# 4. Training Mode Tests
# ===================================================================


class TestTrainingMode:
    """Verify training mode observation and flagging."""

    def setup_method(self):
        """Enable training mode for each test."""
        from thomas.chat_logger import TrainingMode

        TrainingMode.enable()

    def teardown_method(self):
        """Reset after each test."""
        from thomas.chat_logger import TrainingMode

        TrainingMode.reset()
        TrainingMode.disable()

    def test_good_response_not_flagged(self):
        """A natural, appropriate response should not be flagged."""
        from thomas.chat_logger import TrainingMode

        obs = TrainingMode.observe_response(
            user_text="What's the capital of France?",
            assistant_text="Paris.",
            route_path="general",
            confidence=0.8,
        )
        assert not obs.flagged, f"Good response was flagged: {obs.reasons}"

    def test_robotic_response_flagged(self):
        """A robotic response should be flagged."""
        from thomas.chat_logger import TrainingMode

        obs = TrainingMode.observe_response(
            user_text="What's Python?",
            assistant_text="Certainly! I would be delighted to help! Python is a programming language.",
            route_path="general",
            confidence=0.8,
        )
        assert obs.flagged, "Robotic response was not flagged"
        assert any("Robotic" in r for r in obs.reasons)

    def test_oververbose_response_flagged(self):
        """Extremely verbose response to a simple question should be flagged."""
        from thomas.chat_logger import TrainingMode

        long_response = "Well, let me break this down for you. " * 30
        obs = TrainingMode.observe_response(
            user_text="What time?",
            assistant_text=long_response,
            route_path="general",
            confidence=0.8,
        )
        assert obs.flagged, "Over-verbose response was not flagged"

    def test_empty_response_flagged(self):
        """Empty response should be flagged as bad."""
        from thomas.chat_logger import TrainingMode

        obs = TrainingMode.observe_response(
            user_text="Help me",
            assistant_text="",
            route_path="general",
            confidence=0.8,
        )
        assert obs.flagged
        assert obs.quality == "bad"

    def test_internal_detail_leak_flagged(self):
        """Leaking internal details should be flagged."""
        from thomas.chat_logger import TrainingMode

        obs = TrainingMode.observe_response(
            user_text="Hello",
            assistant_text="Hello! My agent loop is configured with token economy settings.",
            route_path="casual_chat",
            confidence=0.8,
        )
        assert obs.flagged
        assert any("internal" in r.lower() or "Leaking" in r for r in obs.reasons)

    def test_low_confidence_noted(self):
        """Low routing confidence should be noted."""
        from thomas.chat_logger import TrainingMode

        obs = TrainingMode.observe_response(
            user_text="Do the thing",
            assistant_text="Sure, working on it.",
            route_path="coding_task",
            confidence=0.3,
        )
        assert any("confidence" in r.lower() for r in obs.reasons)

    def test_verbose_opener_flagged(self):
        """Verbose openers like 'Let me help you' should be flagged."""
        from thomas.chat_logger import TrainingMode

        obs = TrainingMode.observe_response(
            user_text="Fix this",
            assistant_text="Let me help you with that. The issue is in the config file.",
            route_path="coding_task",
            confidence=0.8,
        )
        assert obs.flagged
        assert any("verbose" in r.lower() or "opener" in r.lower() for r in obs.reasons)

    def test_question_restatement_flagged(self):
        """Response starting with question restatement should be flagged."""
        from thomas.chat_logger import TrainingMode

        obs = TrainingMode.observe_response(
            user_text="What is the capital of France and why is it important?",
            assistant_text="What is the capital of France and why is it important? Well, Paris is...",
            route_path="general",
            confidence=0.8,
        )
        assert obs.flagged
        assert any("restat" in r.lower() for r in obs.reasons)

    def test_correction_recording(self):
        """Corrections are recorded."""
        from thomas.chat_logger import TrainingMode

        TrainingMode.add_correction(
            user_text="Hi",
            bad_response="Hello. I am Thomas AI Assistant version 2.0.",
            corrected_response="Hey! What's up?",
            reason="Too formal and robotic",
        )
        report = TrainingMode.get_report()
        assert report["corrections_recorded"] >= 1

    def test_report_generation(self):
        """Report generation works with observations."""
        from thomas.chat_logger import TrainingMode

        # Generate some observations
        TrainingMode.observe_response("hi", "Hello!", "casual", 0.8)
        TrainingMode.observe_response("hi", "Certainly! I'd be happy to help!", "casual", 0.8)

        report = TrainingMode.get_report()
        assert report["total_observations"] >= 2
        assert "quality_distribution" in report
        assert "top_issues" in report

    def test_reset_clears_data(self):
        """Reset clears all observations and corrections."""
        from thomas.chat_logger import TrainingMode

        TrainingMode.observe_response("hi", "hey", "casual", 0.8)
        TrainingMode.add_correction("a", "b", "c")
        TrainingMode.reset()

        report = TrainingMode.get_report()
        assert report["total"] == 0
        assert report["corrections_recorded"] == 0

    def test_disabled_mode_no_observation(self):
        """When disabled, observe_response returns empty observation."""
        from thomas.chat_logger import TrainingMode

        TrainingMode.disable()
        obs = TrainingMode.observe_response("hi", "hey", "casual", 0.8)
        assert not obs.flagged
        assert len(obs.reasons) == 0

    def test_metrics_recorded(self):
        """Observation includes metrics about the response."""
        from thomas.chat_logger import TrainingMode

        obs = TrainingMode.observe_response(
            user_text="test",
            assistant_text="response",
            route_path="general",
            confidence=0.85,
            mode="auto",
            elapsed_ms=150.0,
            tool_calls=2,
            session_id="s1",
        )
        assert obs.metrics["route"] == "general"
        assert obs.metrics["confidence"] == 0.85
        assert obs.metrics["elapsed_ms"] == 150.0
        assert obs.metrics["tool_calls"] == 2


# ===================================================================
# 5. Routing Integration Tests
# ===================================================================


class TestRoutingIntegration:
    """Test that routing works correctly with conversation types."""

    def test_greeting_routes_to_casual(self):
        """Greetings should route to casual_chat path."""
        from thomas.agent.routing import IntentRouter

        router = IntentRouter()
        result = router.decide("hey, how's it going?")
        assert result.path == "casual_chat", f"Greeting routed to {result.path}"

    def test_code_question_routes_to_coding(self):
        """Code questions should route to coding_task."""
        from thomas.agent.routing import IntentRouter

        router = IntentRouter()
        result = router.decide("fix the bug in main.py line 42")
        assert result.path in ("coding_task", "debug_audit"), f"Code question routed to {result.path}"

    def test_behavior_feedback_routes_to_meta(self):
        """Feedback about Thomas's behavior should route to assistant_meta."""
        from thomas.agent.routing import IntentRouter

        router = IntentRouter()
        result = router.decide("you sound too robotic, talk better")
        assert result.path == "assistant_meta", f"Behavior feedback routed to {result.path}"

    def test_debug_routes_correctly(self):
        """Debug-related messages route to debug_audit."""
        from thomas.agent.routing import IntentRouter

        router = IntentRouter()
        result = router.decide("getting a traceback error when running tests")
        assert result.path == "debug_audit", f"Debug routed to {result.path}"

    def test_research_routes_correctly(self):
        """Research requests route to research."""
        from thomas.agent.routing import IntentRouter

        router = IntentRouter()
        result = router.decide("research the latest news about Python 3.13")
        assert result.path == "research", f"Research routed to {result.path}"

    def test_frustration_detected(self):
        """Frustration signals should be detected."""
        from thomas.agent.response_tone import prompt_has_frustration_signal

        assert prompt_has_frustration_signal("this is so frustrating")
        assert prompt_has_frustration_signal("you're not working properly")
        assert not prompt_has_frustration_signal("can you help me with this?")

    def test_followup_continuity(self):
        """Follow-up messages should bias toward the previous route."""
        from thomas.agent.routing import IntentRouter

        router = IntentRouter()
        result = router.decide(
            "and also add error handling",
            is_followup=True,
            prior_route="coding_task",
        )
        assert result.path == "coding_task", f"Follow-up routed to {result.path} instead of coding_task"

    def test_liveness_check(self):
        """'Are you there?' type messages should route casual."""
        from thomas.agent.routing import IntentRouter

        router = IntentRouter()
        result = router.decide("are you there?")
        assert result.path == "casual_chat"

    def test_no_execution_intent(self):
        """'Just chatting' should route casual."""
        from thomas.agent.routing import IntentRouter

        router = IntentRouter()
        result = router.decide("I'm just chatting, no task")
        assert result.path == "casual_chat"
