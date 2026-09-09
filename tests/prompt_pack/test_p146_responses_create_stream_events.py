import json

import pytest

from thomas.cli.commands.gateway import p146_responses_create_stream_events as cli_impl
from thomas.server.routes.gateway import p146_responses_create_stream_events as impl


def test_stream_events_success_contract_and_order():
    req_payload = {"model": "gpt-test", "input": "hello world", "stream": True}
    parsed = impl.parse_create_response_request(req_payload)

    events = impl.build_stream_events(
        parsed,
        response_id="resp_test",
        message_id="msg_test",
        created_at=100,
        completed_at=101,
    )

    assert events[0]["type"] == "response.created"
    assert events[-1]["type"] == "response.completed"

    seq = [e["sequence_number"] for e in events]
    assert seq == list(range(1, len(events) + 1)), "sequence_number must be monotonically increasing"

    deltas = "".join(e["delta"] for e in events if e["type"] == "response.output_text.delta")
    done = next(e for e in events if e["type"] == "response.output_text.done")
    assert deltas == done["text"]

    completed = events[-1]["response"]
    assert completed["status"] == "completed"
    assert completed["output"][0]["content"][0]["text"] == deltas
    assert "usage" in completed and completed["usage"]["total_tokens"] >= 2


def test_sse_serialization_contains_event_and_data_lines():
    req_payload = {"model": "gpt-test", "input": "hi", "stream": True}
    parsed = impl.parse_create_response_request(req_payload)
    events = impl.build_stream_events(
        parsed,
        response_id="resp_test",
        message_id="msg_test",
        created_at=100,
        completed_at=101,
    )
    sse = impl.events_to_sse(events)
    assert "event: response.created" in sse
    assert "data:" in sse
    assert sse.endswith("\n\n")


def test_invalid_input_missing_model_is_deterministic():
    with pytest.raises(impl.GatewayError) as excinfo:
        impl.parse_create_response_request({"input": "hello", "stream": True})
    err = excinfo.value
    assert err.code == "invalid_request"
    assert err.http_status == 400


def test_proxy_mode_missing_upstream_url_raises_deterministic_error(monkeypatch):
    monkeypatch.setenv("THOMAS_GATEWAY_RESPONSES_MODE", "proxy")
    monkeypatch.delenv("THOMAS_GATEWAY_RESPONSES_UPSTREAM_URL", raising=False)

    with pytest.raises(impl.GatewayError) as excinfo:
        impl.load_runtime_config_from_env()
    err = excinfo.value
    assert err.code == "missing_config"
    assert err.http_status == 500


def test_external_failure_simulation_is_deterministic():
    req_payload = {"model": "thomas-fail", "input": "hello", "stream": True}
    parsed = impl.parse_create_response_request(req_payload)

    with pytest.raises(impl.GatewayError) as excinfo:
        impl.build_stream_events(
            parsed,
            response_id="resp_test",
            message_id="msg_test",
            created_at=100,
            completed_at=101,
        )
    err = excinfo.value
    assert err.code == "upstream_failure"
    assert err.http_status == 502


def test_cli_json_output_is_machine_readable(capsys):
    rc = cli_impl.main(["--model", "gpt-test", "--input", "hello", "--json"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert isinstance(data, list)
    assert data[0]["type"] == "response.created"
