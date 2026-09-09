"""CAP-079: schema-validated structured output with bounded self-repair.

Acceptance line: "Accept a caller schema, validate it, and self-repair
invalid output within a bounded loop."

All tests use injected fake adapters — no live model calls.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from thomas.core import structured_output as so
from thomas.core.config import ModelConfig
from thomas.core.llm_client import LLMClient
from thomas.core.structured_output import (
    SchemaValidationError,
    StructuredOutputError,
    StructuredResult,
    extract_json,
    request_structured,
    validate_instance,
    validate_schema,
)

PERSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
        "role": {"type": "string", "enum": ["admin", "user"]},
    },
    "required": ["name", "age"],
    "additionalProperties": False,
}


class ScriptedAdapter:
    """Fake LLM adapter returning scripted outputs, recording every call."""

    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls: list[list[dict[str, Any]]] = []

    async def __call__(self, messages: list[dict[str, Any]]) -> str:
        self.calls.append(messages)
        if not self.outputs:
            raise AssertionError("adapter called more times than scripted")
        return self.outputs.pop(0)


# ---------------------------------------------------------------------------
# 1. Caller schema is itself validated
# ---------------------------------------------------------------------------


def test_non_mapping_schema_rejected():
    with pytest.raises(SchemaValidationError, match="mapping"):
        validate_schema(["not", "a", "schema"])


def test_invalid_schema_rejected_with_clear_error():
    bad = {"type": "object", "properties": {"x": {"type": "not-a-type"}}}
    with pytest.raises(SchemaValidationError, match="not-a-type"):
        validate_schema(bad)


def test_invalid_schema_rejected_before_any_model_call():
    adapter = ScriptedAdapter(['{"name": "a", "age": 1}'])
    with pytest.raises(SchemaValidationError):
        asyncio.run(request_structured(adapter, "hi", {"type": "nope"}))
    assert adapter.calls == []


def test_valid_schema_accepted():
    validate_schema(PERSON_SCHEMA)  # must not raise


# ---------------------------------------------------------------------------
# 2 + 3. Prompts for schema-conforming JSON and validates the output
# ---------------------------------------------------------------------------


def test_valid_first_attempt_returns_data_and_trace():
    adapter = ScriptedAdapter(['{"name": "Ada", "age": 36}'])
    result = asyncio.run(request_structured(adapter, "Describe Ada", PERSON_SCHEMA))
    assert isinstance(result, StructuredResult)
    assert result.data == {"name": "Ada", "age": 36}
    assert result.attempts == 1
    assert result.repaired is False
    assert len(result.trace) == 1
    assert result.trace[0]["valid"] is True
    assert result.trace[0]["errors"] == []


def test_schema_is_included_in_the_prompt():
    adapter = ScriptedAdapter(['{"name": "Ada", "age": 36}'])
    asyncio.run(request_structured(adapter, "Describe Ada", PERSON_SCHEMA))
    sent = adapter.calls[0]
    assert sent[0] == {"role": "user", "content": "Describe Ada"}
    schema_msg = sent[-1]["content"]
    assert "JSON Schema" in schema_msg
    assert '"required"' in schema_msg  # schema body serialized into the prompt


def test_message_list_input_is_preserved():
    adapter = ScriptedAdapter(['{"name": "Ada", "age": 36}'])
    messages = [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "Describe Ada"},
    ]
    asyncio.run(request_structured(adapter, messages, PERSON_SCHEMA))
    sent = adapter.calls[0]
    assert sent[0]["role"] == "system"
    assert sent[1]["content"] == "Describe Ada"
    assert len(sent) == 3  # original two + schema instruction


# ---------------------------------------------------------------------------
# 4. Self-repair: validation errors are fed back, bounded retries
# ---------------------------------------------------------------------------


def test_invalid_then_valid_output_is_repaired():
    adapter = ScriptedAdapter(
        [
            '{"name": "Ada", "age": "thirty-six"}',  # wrong type for age
            '{"name": "Ada", "age": 36}',
        ]
    )
    result = asyncio.run(request_structured(adapter, "Describe Ada", PERSON_SCHEMA))
    assert result.data == {"name": "Ada", "age": 36}
    assert result.attempts == 2
    assert result.repaired is True
    assert result.trace[0]["valid"] is False
    assert result.trace[1]["valid"] is True
    # The repair round-trip contains the previous output and the specific errors.
    second_call = adapter.calls[1]
    assert second_call[-2]["role"] == "assistant"
    assert "thirty-six" in second_call[-2]["content"]
    repair_msg = second_call[-1]["content"]
    assert "did not conform" in repair_msg
    assert "age" in repair_msg


def test_unparseable_json_is_repaired():
    adapter = ScriptedAdapter(
        [
            "Sure! Here you go: name=Ada age=36",
            '{"name": "Ada", "age": 36}',
        ]
    )
    result = asyncio.run(request_structured(adapter, "Describe Ada", PERSON_SCHEMA))
    assert result.attempts == 2
    assert "not valid JSON" in result.trace[0]["errors"][0] or "JSON" in result.trace[0]["errors"][0]


def test_repair_loop_is_bounded_and_raises_with_trace():
    adapter = ScriptedAdapter(["not json"] * 10)
    with pytest.raises(StructuredOutputError) as excinfo:
        asyncio.run(request_structured(adapter, "hi", PERSON_SCHEMA, max_repair_attempts=2))
    assert len(adapter.calls) == 3  # 1 initial + 2 repairs, never more
    assert len(excinfo.value.trace) == 3
    assert all(entry["valid"] is False for entry in excinfo.value.trace)


def test_zero_repair_attempts_means_exactly_one_call():
    adapter = ScriptedAdapter(["not json"] * 5)
    with pytest.raises(StructuredOutputError):
        asyncio.run(request_structured(adapter, "hi", PERSON_SCHEMA, max_repair_attempts=0))
    assert len(adapter.calls) == 1


def test_negative_repair_attempts_rejected():
    adapter = ScriptedAdapter([])
    with pytest.raises(ValueError, match=">= 0"):
        asyncio.run(request_structured(adapter, "hi", PERSON_SCHEMA, max_repair_attempts=-1))


# ---------------------------------------------------------------------------
# JSON extraction tolerance (fences / surrounding prose)
# ---------------------------------------------------------------------------


def test_extract_json_handles_markdown_fences():
    value, err = extract_json('```json\n{"name": "Ada", "age": 36}\n```')
    assert err is None
    assert value == {"name": "Ada", "age": 36}


def test_extract_json_handles_surrounding_prose():
    value, err = extract_json('Here is the JSON: {"name": "Ada", "age": 36} hope it helps')
    assert err is None
    assert value == {"name": "Ada", "age": 36}


def test_extract_json_reports_failure():
    value, err = extract_json("no json here at all")
    assert value is None
    assert err is not None


# ---------------------------------------------------------------------------
# Fallback validator (jsonschema absent)
# ---------------------------------------------------------------------------


@pytest.fixture
def no_jsonschema(monkeypatch):
    monkeypatch.setattr(so, "_jsonschema", None)


def test_fallback_schema_check_rejects_bad_type(no_jsonschema):
    with pytest.raises(SchemaValidationError, match="unknown type"):
        validate_schema({"type": "objectt"})


def test_fallback_schema_check_rejects_bad_required(no_jsonschema):
    with pytest.raises(SchemaValidationError, match="required"):
        validate_schema({"type": "object", "required": "name"})


def test_fallback_validator_covers_core_keywords(no_jsonschema):
    errors = validate_instance(
        {"name": 7, "role": "root", "extra": True, "tags": ["a", 3]},
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "role": {"type": "string", "enum": ["admin", "user"]},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name", "age"],
            "additionalProperties": False,
        },
    )
    joined = "\n".join(errors)
    assert "missing required property 'age'" in joined
    assert "$.name" in joined  # type error
    assert "not one of the allowed values" in joined  # enum
    assert "unexpected property 'extra'" in joined  # additionalProperties
    assert "$.tags[1]" in joined  # items


def test_fallback_rejects_bool_for_integer(no_jsonschema):
    assert validate_instance(True, {"type": "integer"})
    assert validate_instance(3, {"type": "integer"}) == []


def test_full_repair_loop_with_fallback_validator(no_jsonschema):
    adapter = ScriptedAdapter(
        [
            '{"name": "Ada"}',  # missing required age
            '{"name": "Ada", "age": 36}',
        ]
    )
    result = asyncio.run(request_structured(adapter, "Describe Ada", PERSON_SCHEMA))
    assert result.data == {"name": "Ada", "age": 36}
    assert result.repaired is True
    assert any("age" in e for e in result.trace[0]["errors"])


# ---------------------------------------------------------------------------
# jsonschema-backed validation (installed in this venv)
# ---------------------------------------------------------------------------


def test_jsonschema_backend_is_used_when_installed():
    assert so._jsonschema is not None, "venv is expected to have jsonschema installed"
    errors = validate_instance({"name": "Ada"}, PERSON_SCHEMA)
    assert errors and any("age" in e for e in errors)
    assert validate_instance({"name": "Ada", "age": 36}, PERSON_SCHEMA) == []


# ---------------------------------------------------------------------------
# Adapter flexibility
# ---------------------------------------------------------------------------


def test_sync_adapter_and_mapping_return_supported():
    calls: list[Any] = []

    def adapter(messages):
        calls.append(messages)
        return {"text": '{"name": "Ada", "age": 36}', "tool_calls": [], "usage": None}

    result = asyncio.run(request_structured(adapter, "hi", PERSON_SCHEMA))
    assert result.data["name"] == "Ada"
    assert len(calls) == 1


def test_adapter_bad_return_type_raises_type_error():
    with pytest.raises(TypeError, match="adapter"):
        asyncio.run(request_structured(lambda m: 42, "hi", PERSON_SCHEMA))


# ---------------------------------------------------------------------------
# LLMClient wiring
# ---------------------------------------------------------------------------


def test_llm_client_chat_structured_repairs_via_chat(monkeypatch):
    client = LLMClient(ModelConfig(name="test-profile"))
    outputs = ['{"name": "Ada", "age": "old"}', '{"name": "Ada", "age": 36}']
    seen: list[list[dict[str, Any]]] = []

    async def fake_chat(messages, tools=None):
        seen.append(messages)
        return {"text": outputs.pop(0), "tool_calls": [], "usage": None}

    monkeypatch.setattr(client, "chat", fake_chat)
    result = asyncio.run(
        client.chat_structured(
            [{"role": "user", "content": "Describe Ada"}],
            PERSON_SCHEMA,
            max_repair_attempts=2,
        )
    )
    assert result.data == {"name": "Ada", "age": 36}
    assert result.attempts == 2
    assert result.repaired is True
    assert len(seen) == 2
    # Repair round included the validation feedback.
    assert "did not conform" in seen[1][-1]["content"]


def test_llm_client_chat_structured_bounded_failure(monkeypatch):
    client = LLMClient(ModelConfig(name="test-profile"))
    calls = {"n": 0}

    async def fake_chat(messages, tools=None):
        calls["n"] += 1
        return {"text": "garbage", "tool_calls": [], "usage": None}

    monkeypatch.setattr(client, "chat", fake_chat)
    with pytest.raises(StructuredOutputError):
        asyncio.run(
            client.chat_structured(
                [{"role": "user", "content": "hi"}],
                PERSON_SCHEMA,
                max_repair_attempts=1,
            )
        )
    assert calls["n"] == 2


def test_llm_client_chat_structured_rejects_bad_schema():
    client = LLMClient(ModelConfig(name="test-profile"))
    with pytest.raises(SchemaValidationError):
        asyncio.run(client.chat_structured([{"role": "user", "content": "hi"}], {"type": "bogus"}))


def test_trace_is_json_serializable():
    adapter = ScriptedAdapter(["nope", '{"name": "Ada", "age": 36}'])
    result = asyncio.run(request_structured(adapter, "hi", PERSON_SCHEMA))
    json.dumps(result.trace)  # must not raise
