import asyncio

import pytest

from thomas.server.routes.gateway.p145_responses_create_non_stream import (
    GatewayError,
    ResponsesCreateNonStreamRequest,
    create_non_stream_response,
)


class _TextBackend:
    async def responses_create_non_stream(self, req: ResponsesCreateNonStreamRequest):
        assert req.model == "test-model"
        return "Hello from backend"


class _FailingBackend:
    async def responses_create_non_stream(self, req: ResponsesCreateNonStreamRequest):
        raise RuntimeError("boom")


class _WeirdBackend:
    async def responses_create_non_stream(self, req: ResponsesCreateNonStreamRequest):
        return {"not": "a supported shape"}


class _PassthroughBackend:
    async def responses_create_non_stream(self, req: ResponsesCreateNonStreamRequest):
        return {
            "id": "resp_test",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "instructions": None,
            "metadata": {},
            "model": req.model,
            "output": [
                {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "passthrough"}],
                }
            ],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }


def _arun(coro):
    return asyncio.run(coro)


def test_success_wraps_backend_text_into_response_payload():
    payload = {"model": "test-model", "input": "hi"}

    result = _arun(create_non_stream_response(payload, backend=_TextBackend()))

    assert result.payload["object"] == "response"
    assert result.payload["model"] == "test-model"
    assert result.payload["output"][0]["content"][0]["text"] == "Hello from backend"


def test_failure_rejects_stream_true_deterministically():
    payload = {"model": "test-model", "input": "hi", "stream": True}

    with pytest.raises(GatewayError) as excinfo:
        _arun(create_non_stream_response(payload, backend=_TextBackend()))

    assert excinfo.value.status == 400
    assert excinfo.value.code == "stream_not_supported"


def test_failure_missing_model_is_invalid_request_error():
    payload = {"input": "hi"}

    with pytest.raises(GatewayError) as excinfo:
        _arun(create_non_stream_response(payload, backend=_TextBackend()))

    assert excinfo.value.status == 400
    assert excinfo.value.code == "missing_model"


def test_failure_invalid_json_non_object():
    payload = ["not", "an", "object"]

    with pytest.raises(GatewayError) as excinfo:
        _arun(create_non_stream_response(payload, backend=_TextBackend()))

    assert excinfo.value.status == 400
    assert excinfo.value.code == "invalid_json"


def test_failure_backend_exception_becomes_deterministic_upstream_failure():
    payload = {"model": "test-model", "input": "hi"}

    with pytest.raises(GatewayError) as excinfo:
        _arun(create_non_stream_response(payload, backend=_FailingBackend()))

    assert excinfo.value.status == 502
    assert excinfo.value.code == "upstream_failure"
    assert excinfo.value.message == "Upstream request failed."


def test_failure_backend_unsupported_shape_is_deterministic():
    payload = {"model": "test-model", "input": "hi"}

    with pytest.raises(GatewayError) as excinfo:
        _arun(create_non_stream_response(payload, backend=_WeirdBackend()))

    assert excinfo.value.status == 502
    assert excinfo.value.code == "invalid_backend_response"


def test_success_backend_can_return_full_response_payload_passthrough():
    payload = {"model": "test-model", "input": "hi"}

    result = _arun(create_non_stream_response(payload, backend=_PassthroughBackend()))

    assert result.payload["id"] == "resp_test"
    assert result.payload["object"] == "response"
    assert result.payload["output"][0]["content"][0]["text"] == "passthrough"
