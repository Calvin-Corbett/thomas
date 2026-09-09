from thomas.core.config import ModelConfig
from thomas.models.batching import (
    build_completion_request,
    extract_result_error,
    extract_result_text,
    parse_batch_state,
)


def test_parse_batch_state_marks_done_when_pending_zero() -> None:
    payload = {
        "batch_id": "batch_1",
        "state": {
            "num_requests": 3,
            "num_pending": 0,
            "num_success": 3,
            "num_error": 0,
            "num_cancelled": 0,
        },
    }
    state = parse_batch_state(payload)
    assert state["done"] is True
    assert state["status"] in ("completed", "complete", "done", "running")
    assert int(state["num_success"]) == 3


def test_extract_result_text_from_completion_response_choices() -> None:
    result = {
        "batch_request_id": "r1",
        "response": {"completion_response": {"choices": [{"message": {"content": "BATCH_OK"}}]}},
    }
    assert extract_result_text(result) == "BATCH_OK"


def test_extract_result_error_prefers_message() -> None:
    result = {
        "batch_request_id": "r1",
        "error": {"code": 13, "message": "model overload"},
    }
    assert extract_result_error(result) == "model overload"


def test_build_completion_request_uses_model_config() -> None:
    cfg = ModelConfig(
        name="xai",
        provider="openai_compat",
        model="grok-4-1-fast-reasoning",
        max_tokens=2048,
        temperature=0.2,
        top_p=0.9,
    )
    req = build_completion_request(
        model_cfg=cfg,
        messages=[{"role": "user", "content": "hello"}],
    )
    assert req["model"] == "grok-4-1-fast-reasoning"
    assert req["max_tokens"] == 2048
    assert req["temperature"] == 0.2
    assert req["top_p"] == 0.9
    assert req["messages"][0]["content"] == "hello"
