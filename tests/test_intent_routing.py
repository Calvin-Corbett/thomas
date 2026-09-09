"""Contracts for model-owned AgentLoop routing behavior."""

from thomas.agent.routing import PATH_MODEL_OWNED, IntentRouter


def test_natural_language_never_changes_the_execution_route() -> None:
    router = IntentRouter()
    prompts = (
        "hey, how are you today?",
        "refactor src/app.py and add tests",
        "make me a graph of current trends",
        "I don't care, you pick",
        "don't use tools or start a project",
    )

    decisions = [router.decide(prompt) for prompt in prompts]

    assert {decision.path for decision in decisions} == {PATH_MODEL_OWNED}
    assert {tuple(decision.reasons) for decision in decisions} == {("model_owned",)}
    assert {decision.tools_policy for decision in decisions} == {"auto"}


def test_explicit_mode_and_tool_controls_are_preserved() -> None:
    decision = IntentRouter().decide(
        "wording is not inspected",
        requested_mode="thinking",
        requested_tools_policy="never",
    )

    assert decision.mode == "thinking"
    assert decision.tools_policy == "never"


def test_invalid_tool_control_fails_to_neutral_auto() -> None:
    decision = IntentRouter().decide("anything", requested_tools_policy="invented")

    assert decision.tools_policy == "auto"


def test_structured_followup_metadata_does_not_reclassify_the_turn() -> None:
    decision = IntentRouter().decide(
        "that one",
        is_followup=True,
        prior_route="coding_task",
    )

    assert decision.path == PATH_MODEL_OWNED
    assert decision.is_followup is True


def test_route_decision_is_serializable_and_has_memory_policy() -> None:
    decision = IntentRouter().decide("")
    payload = decision.to_dict()

    assert payload["path"] == PATH_MODEL_OWNED
    assert payload["confidence"] == 1.0
    assert payload["memory_include_global"] is True
    assert payload["memory_include_profile"] is True
    assert int(payload["memory_budget_tokens"]) > 0
