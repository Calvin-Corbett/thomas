"""Two oversize files were split by moving small helpers into their own modules; the helpers behave as they did."""

from thomas.agent import loop_core
from thomas.agent.loop_system_text import load_purpose_text, with_required_system_text
from thomas.core.llm_stream_args import coerce_args_fragment


def test_stream_arguments_become_text_whatever_shape_they_arrive_in():
    assert coerce_args_fragment(None) == ""
    assert coerce_args_fragment('{"a": 1}') == '{"a": 1}'
    assert coerce_args_fragment({"a": "é"}) == '{"a": "é"}'
    assert coerce_args_fragment({1, 2}) == str({1, 2})


def test_required_text_is_appended_to_the_system_message_every_turn():
    system = {"role": "system", "content": "base"}
    assert with_required_system_text(system, "  must ship  ") == {"role": "system", "content": "base\n\nmust ship"}
    assert with_required_system_text({"role": "system", "content": ""}, "only") == {"role": "system", "content": "only"}
    assert with_required_system_text(system, "   ") is system


def test_the_purpose_brief_loads_once_and_an_unreadable_one_is_empty(monkeypatch):
    load_purpose_text.cache_clear()
    monkeypatch.setattr("thomas.agent.loop_system_text.load_cached_purpose_brief", lambda: "brief")
    assert load_purpose_text() == "brief"
    load_purpose_text.cache_clear()

    def broken():
        raise OSError("gone")

    monkeypatch.setattr("thomas.agent.loop_system_text.load_cached_purpose_brief", broken)
    assert load_purpose_text() == ""
    load_purpose_text.cache_clear()


def test_the_loop_still_exposes_the_names_other_code_patches():
    assert loop_core._load_purpose_text is load_purpose_text
    assert loop_core._with_required_system_text is with_required_system_text
