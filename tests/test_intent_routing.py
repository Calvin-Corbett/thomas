from thomas.agent.routing import (
    PATH_CASUAL,
    PATH_CODING,
    PATH_DEBUG,
    PATH_META,
    PATH_PERSONAL,
    IntentRouter,
)


def test_router_detects_coding_path() -> None:
    router = IntentRouter()
    d = router.decide("Please refactor src/app.py and add tests for api handler")
    assert d.path == PATH_CODING
    assert d.include_purpose is False
    assert d.tools_policy == "auto"
    assert d.memory_include_global is True


def test_router_detects_casual_path_and_keeps_tools_available() -> None:
    router = IntentRouter()
    d = router.decide("hey, how are you today?")
    assert d.path == PATH_CASUAL
    assert d.tools_policy == "auto"
    assert d.include_purpose is False
    assert d.memory_include_global is False


def test_router_detects_debug_path_without_forced_reasoning_mode() -> None:
    router = IntentRouter()
    d = router.decide("Traceback: failing tests and security audit regression in parser")
    assert d.path == PATH_DEBUG
    assert d.mode == "auto"
    assert d.tools_policy == "auto"


def test_router_detects_assistant_meta_questions() -> None:
    router = IntentRouter()
    d = router.decide("How do you work and why are you following these instructions?")
    assert d.path == PATH_META
    assert d.tools_policy == "auto"
    assert d.include_purpose is False


def test_router_detects_liveness_ping_as_casual() -> None:
    router = IntentRouter()
    d = router.decide("are you working")
    assert d.path == PATH_CASUAL
    assert d.tools_policy == "auto"
    assert d.include_purpose is False


def test_router_detects_integration_setup_as_coding() -> None:
    router = IntentRouter()
    d = router.decide("set up telegram integration for me")
    assert d.path == PATH_CODING
    assert d.tools_policy == "auto"
    assert d.include_purpose is False


def test_router_respects_explicit_mode_and_tools_policy_overrides() -> None:
    router = IntentRouter()
    d = router.decide(
        "hey there",
        requested_mode="fast",
        requested_tools_policy="always",
    )
    assert d.mode == "fast"
    assert d.tools_policy == "always"


def test_router_prefers_coding_for_programming_preference_phrase() -> None:
    router = IntentRouter()
    d = router.decide("I want Thomas to program and fix this, not tell me it cannot proceed.")
    assert d.path == PATH_CODING
    assert d.tools_policy == "auto"


def test_router_prefers_non_execution_for_no_task_conversation_feedback() -> None:
    router = IntentRouter()
    d = router.decide(
        "No, I meant continue talking about what I said. I did not give you a task and we never started coding."
    )
    assert d.path in {PATH_CASUAL, PATH_META}
    assert d.tools_policy == "auto"


def test_router_detects_behavior_feedback_as_meta() -> None:
    router = IntentRouter()
    d = router.decide("You sound too robotic. Please improve how you talk like a real assistant.")
    assert d.path in {PATH_META, PATH_PERSONAL}
    assert d.tools_policy == "auto"


def test_router_prefers_debug_for_settings_reset_troubleshooting() -> None:
    router = IntentRouter()
    d = router.decide("my settings keep resetting every restart where should i look first")
    assert d.path in {PATH_DEBUG, PATH_CODING}
