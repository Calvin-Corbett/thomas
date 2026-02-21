import pytest

from thomas.server.routes.gateway.p147_responses_tool_result_mapping import (
    DeterministicMappingError,
    map_tool_result_to_responses_tool_output,
)


def test_map_success_json_result():
    req = {"tool_call_id": "tc_123", "result": {"x": 1, "ok": True}}
    out = map_tool_result_to_responses_tool_output(req)
    tool_output = out["tool_output"]
    assert tool_output["type"] == "tool_output"
    assert tool_output["tool_call_id"] == "tc_123"
    assert tool_output["status"] == "completed"
    assert tool_output["output"] == {"x": 1, "ok": True}
    assert tool_output["content"][0]["type"] == "output_json"
    assert tool_output["content"][0]["json"] == {"x": 1, "ok": True}


def test_map_success_text_result():
    req = {"tool_call_id": "tc_abc", "result": "hello"}
    out = map_tool_result_to_responses_tool_output(req)
    tool_output = out["tool_output"]
    assert tool_output["status"] == "completed"
    assert tool_output["output"] == "hello"
    assert tool_output["content"][0]["type"] == "output_text"
    assert tool_output["content"][0]["text"] == "hello"


def test_map_error_result():
    req = {
        "tool_call_id": "tc_err",
        "is_error": True,
        "error_code": "tool_failed",
        "error_message": "boom",
    }
    out = map_tool_result_to_responses_tool_output(req)
    tool_output = out["tool_output"]
    assert tool_output["status"] == "failed"
    assert tool_output["error"]["code"] == "tool_failed"
    assert tool_output["error"]["message"] == "boom"
    assert tool_output["output"] == "boom"
    assert tool_output["content"][0]["type"] == "output_text"


def test_invalid_missing_tool_call_id():
    with pytest.raises(DeterministicMappingError) as e:
        map_tool_result_to_responses_tool_output({"result": {"x": 1}})
    assert e.value.code == "invalid_input"


def test_invalid_missing_result_when_not_error():
    with pytest.raises(DeterministicMappingError) as e:
        map_tool_result_to_responses_tool_output({"tool_call_id": "tc_1"})
    assert e.value.code == "invalid_input"
