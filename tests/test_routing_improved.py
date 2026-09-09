"""Adversarial checks that prose cannot seize Thomas's control plane."""

import inspect

from thomas.agent.routing import PATH_MODEL_OWNED, IntentRouter


def test_negations_and_keywords_cannot_toggle_hidden_routes() -> None:
    router = IntentRouter()
    pairs = (
        ("use tools", "do not use tools"),
        ("build the project", "do not build the project"),
        ("this is a coding task", "this is not a coding task"),
        ("research the latest news", "don't research anything"),
    )

    for positive, negative in pairs:
        assert router.decide(positive).path == PATH_MODEL_OWNED
        assert router.decide(negative).path == PATH_MODEL_OWNED
        assert router.decide(positive).tools_policy == "auto"
        assert router.decide(negative).tools_policy == "auto"


def test_router_source_contains_no_prompt_pattern_engine() -> None:
    source = inspect.getsource(IntentRouter)

    assert "re.compile" not in source
    assert ".search(" not in source
    assert "keyword" not in source.lower()
    assert "scores" not in source


def test_prompt_text_is_not_retained_as_a_routing_reason() -> None:
    prompt = "Traceback: build a graph, don't create a game"
    decision = IntentRouter().decide(prompt)

    assert decision.reasons == ["model_owned"]
    assert prompt not in repr(decision.to_dict())
