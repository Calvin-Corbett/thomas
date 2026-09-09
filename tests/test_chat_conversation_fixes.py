"""Tests for the chat conversation fixes.

Covers:
1. Chat logger (pipeline event logging)
2. Training mode (behavior observation and flagging)
3. Model-owned routing integration

Note: Quick reply tests that need aiohttp/server imports are skipped
when those dependencies aren't available.
"""

from __future__ import annotations

import json

# ===================================================================
# 1. Chat Logger Tests
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

        def cb(e):
            return received.append(e)

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
# 2. Training Mode Tests
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
# 3. Routing Integration Tests
# ===================================================================


class TestRoutingIntegration:
    """Natural-language wording cannot select an execution path."""

    def test_different_topics_share_one_model_owned_path(self):
        from thomas.agent.routing import IntentRouter

        router = IntentRouter()
        prompts = [
            "hey, how's it going?",
            "fix the bug in main.py line 42",
            "you sound too robotic, talk better",
            "research the latest news about Python 3.13",
            "I'm just chatting, no task",
        ]
        assert {router.decide(prompt).path for prompt in prompts} == {"model_owned"}

    def test_explicit_followup_metadata_does_not_restore_prior_semantic_route(self):
        from thomas.agent.routing import IntentRouter

        router = IntentRouter()
        result = router.decide(
            "and also add error handling",
            is_followup=True,
            prior_route="coding_task",
        )
        assert result.path == "model_owned"
        assert result.is_followup is True
