from thomas.marketplace.orchestrator.brain_v3 import _load_dispatch


def test_load_dispatch_module_for_casual_routing() -> None:
    dispatch = _load_dispatch()

    assert dispatch is not None
    assert dispatch.should_dispatch("yo").action == "casual"
    assert dispatch.should_dispatch("fix the login bug").action == "dispatch"
