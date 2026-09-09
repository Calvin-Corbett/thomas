import pytest

from thomas.server.routes.gateway.p142_openai_tool_call_passthrough_mapping import (
    ToolCallIdMapError,
    build_openai_tool_call_passthrough_mapping,
)


def test_success_remaps_invalid_tool_call_ids_and_results():
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "functions.read:0", "type": "function", "function": {"name": "read", "arguments": "{}"}},
                {"id": " functions.exec:11", "type": "function", "function": {"name": "exec", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "functions.read:0", "content": "ok"},
        # This one uses the stripped form, ensuring mapping tolerates provider normalization differences.
        {"role": "tool", "tool_call_id": "functions.exec:11", "content": "ok"},
    ]

    result = build_openai_tool_call_passthrough_mapping(messages)

    tool_ids = [tc["id"] for tc in result.messages[0]["tool_calls"]]
    assert tool_ids[0] == "functions_read_0"
    assert tool_ids[1] == "functions_exec_11"

    assert result.messages[1]["tool_call_id"] == "functions_read_0"
    assert result.messages[2]["tool_call_id"] == "functions_exec_11"

    assert result.changed is True
    assert result.stats["total_tool_calls"] == 2
    assert result.stats["remapped_tool_calls"] == 2
    assert result.stats["total_tool_results"] == 2
    assert result.stats["remapped_tool_results"] == 2

    assert result.tool_call_id_map["functions.read:0"] == "functions_read_0"
    assert result.tool_call_id_map["functions.exec:11"] == "functions_exec_11"


def test_success_collision_gets_stable_hash_suffix():
    # Both sanitize to "a_b" -> collision must be resolved deterministically.
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "a.b", "type": "function", "function": {"name": "t1", "arguments": "{}"}},
                {"id": "a:b", "type": "function", "function": {"name": "t2", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "a.b", "content": "ok"},
        {"role": "tool", "tool_call_id": "a:b", "content": "ok"},
    ]

    result = build_openai_tool_call_passthrough_mapping(messages)
    ids = [tc["id"] for tc in result.messages[0]["tool_calls"]]
    assert ids[0] == "a_b"
    assert ids[1].startswith("a_b_")
    # Tool results should match the remapped ids.
    assert result.messages[1]["tool_call_id"] == ids[0]
    assert result.messages[2]["tool_call_id"] == ids[1]


def test_failure_unknown_tool_call_id_is_deterministic():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "functions.read:0", "type": "function", "function": {"name": "read", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "functions.exec:99", "content": "ok"},
    ]

    with pytest.raises(ToolCallIdMapError) as exc:
        build_openai_tool_call_passthrough_mapping(messages)

    err = exc.value
    assert err.code == "unknown_tool_call_id"
    assert err.http_status == 400
    assert "functions.exec:99" in str(err)


def test_failure_rejects_invalid_shapes():
    messages = [{"role": "assistant", "tool_calls": {"id": "x"}}]
    with pytest.raises(ToolCallIdMapError) as exc:
        build_openai_tool_call_passthrough_mapping(messages)
    assert exc.value.code == "invalid_request"
