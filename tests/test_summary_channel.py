"""CAP-028: caller-defined, schema-validated summary-only return channel.

Acceptance line: "Add an automatic caller-defined, schema-validated
summary-only return channel."

All tests use injected fake adapters — no live model calls.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from thomas.core.structured_output import SchemaValidationError, StructuredOutputError
from thomas.core.summary_channel import (
    DEFAULT_SUMMARY_SCHEMA,
    SummaryResult,
    return_summary,
    schema_id_for,
)

# A caller-defined summary schema distinct from the built-in default.
CALLER_SCHEMA: dict[str, Any] = {
    "title": "review.summary.v1",
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok", "blocked"]},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "next_step": {"type": "string"},
    },
    "required": ["status", "key_findings", "next_step"],
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
# 1. A caller-defined schema is honored and validated
# ---------------------------------------------------------------------------


def test_caller_defined_schema_is_honored_and_validated():
    summary_json = json.dumps(
        {
            "status": "ok",
            "key_findings": ["auth works", "no leaks"],
            "artifacts": ["report.md"],
            "next_step": "ship it",
        }
    )
    adapter = ScriptedAdapter([summary_json])
    result = asyncio.run(return_summary(adapter, "Review the diff", CALLER_SCHEMA))

    assert isinstance(result, SummaryResult)
    assert result.summary["status"] == "ok"
    assert result.summary["key_findings"] == ["auth works", "no leaks"]
    assert result.attempts == 1
    assert result.repaired is False
    # Envelope carries the caller schema's own id (its title).
    assert result.schema_id == "review.summary.v1"
    # The caller schema (not the default) was serialized into the prompt.
    schema_msg = adapter.calls[0][-1]["content"]
    assert "review.summary.v1" in schema_msg
    # The summary-only directive was injected before the schema instruction.
    directive = adapter.calls[0][-2]["content"]
    assert "SUMMARY-ONLY" in directive


def test_output_violating_caller_schema_is_rejected_and_repaired():
    # First reply omits the caller-required next_step; repair supplies it.
    bad = json.dumps({"status": "ok", "key_findings": ["a"]})
    good = json.dumps({"status": "ok", "key_findings": ["a"], "next_step": "done"})
    adapter = ScriptedAdapter([bad, good])
    result = asyncio.run(return_summary(adapter, "Summarize", CALLER_SCHEMA))

    assert result.summary["next_step"] == "done"
    assert result.attempts == 2
    assert result.repaired is True
    assert result.trace[0]["valid"] is False
    assert any("next_step" in e for e in result.trace[0]["errors"])
    assert result.trace[1]["valid"] is True


# ---------------------------------------------------------------------------
# 2. The default schema applies automatically when none is given
# ---------------------------------------------------------------------------


def test_default_schema_applies_when_none_supplied():
    summary_json = json.dumps({"status": "success", "key_findings": ["did the thing"]})
    adapter = ScriptedAdapter([summary_json])
    result = asyncio.run(return_summary(adapter, "Do the thing"))  # no schema

    assert result.summary == {"status": "success", "key_findings": ["did the thing"]}
    assert result.schema_id == "thomas.default_summary"
    assert result.schema_id == schema_id_for(DEFAULT_SUMMARY_SCHEMA)
    # The default schema body was serialized into the prompt.
    assert "thomas.default_summary" in adapter.calls[0][-1]["content"]


def test_default_schema_enum_is_enforced():
    # "maybe" is not an allowed status under the default schema; unrepaired -> raise.
    adapter = ScriptedAdapter([json.dumps({"status": "maybe", "key_findings": []})] * 5)
    with pytest.raises(StructuredOutputError) as excinfo:
        asyncio.run(return_summary(adapter, "Do the thing", max_repair_attempts=1))
    assert any("status" in e for entry in excinfo.value.trace for e in entry["errors"])


# ---------------------------------------------------------------------------
# 3. An over-long model answer is reduced to the summary-only object; the full
#    working body is NOT present in the returned payload.
# ---------------------------------------------------------------------------


def test_overlong_answer_is_reduced_to_summary_only():
    body_marker = "SECRET_WORKING_TRANSCRIPT_" + "x" * 5000
    # The model, following the summary-only directive, returns just the summary
    # object even though the underlying work was huge. The schema's
    # additionalProperties:false guarantees the body cannot ride along.
    summary_json = json.dumps(
        {
            "status": "ok",
            "key_findings": ["condensed finding"],
            "artifacts": [],
            "next_step": "none",
        }
    )
    adapter = ScriptedAdapter([summary_json])
    # The long body lives in the *input* context, proving it is dropped on return.
    result = asyncio.run(
        return_summary(
            adapter,
            f"Here is the full transcript to summarize: {body_marker}",
            CALLER_SCHEMA,
        )
    )

    assert set(result.summary.keys()) == {"status", "key_findings", "artifacts", "next_step"}
    payload = json.dumps(result.summary)
    assert body_marker not in payload
    assert "SECRET_WORKING_TRANSCRIPT_" not in payload


def test_summary_only_object_excludes_extra_body_field_via_repair():
    # Model tries to smuggle the full body in an extra field; additionalProperties
    # rejects it, and the repair returns the clean summary-only object.
    smuggled = json.dumps(
        {
            "status": "ok",
            "key_findings": ["f"],
            "next_step": "n",
            "full_body": "the entire 10k-token transcript goes here",
        }
    )
    clean = json.dumps({"status": "ok", "key_findings": ["f"], "next_step": "n"})
    adapter = ScriptedAdapter([smuggled, clean])
    result = asyncio.run(return_summary(adapter, "Summarize", CALLER_SCHEMA))

    assert "full_body" not in result.summary
    assert json.dumps(result.summary).find("transcript") == -1
    assert result.repaired is True


# ---------------------------------------------------------------------------
# 4. Invalid summary self-repairs within the bound, then raises with trace.
# ---------------------------------------------------------------------------


def test_invalid_summary_repairs_within_bound():
    bad = "not json at all"
    good = json.dumps({"status": "success", "key_findings": ["ok"]})
    adapter = ScriptedAdapter([bad, good])
    result = asyncio.run(return_summary(adapter, "Do it", max_repair_attempts=2))
    assert result.attempts == 2
    assert result.repaired is True
    assert result.trace[0]["valid"] is False


def test_unrepairable_summary_raises_with_trace_and_is_bounded():
    adapter = ScriptedAdapter(["still not json"] * 10)
    with pytest.raises(StructuredOutputError) as excinfo:
        asyncio.run(return_summary(adapter, "Do it", max_repair_attempts=2))
    # 1 initial + 2 repairs, never more.
    assert len(adapter.calls) == 3
    assert len(excinfo.value.trace) == 3
    assert all(entry["valid"] is False for entry in excinfo.value.trace)


def test_malformed_caller_schema_rejected_before_any_model_call():
    adapter = ScriptedAdapter([json.dumps({"status": "ok", "key_findings": []})])
    with pytest.raises(SchemaValidationError):
        asyncio.run(return_summary(adapter, "hi", {"type": "not-a-type"}))
    assert adapter.calls == []


# ---------------------------------------------------------------------------
# Envelope + provenance
# ---------------------------------------------------------------------------


def test_schema_id_falls_back_to_content_hash_when_untitled():
    untitled = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    sid = schema_id_for(untitled)
    assert sid.startswith("summary:")
    # Stable across identical schemas.
    assert sid == schema_id_for(dict(untitled))


def test_result_trace_is_json_serializable():
    adapter = ScriptedAdapter(["nope", json.dumps({"status": "success", "key_findings": []})])
    result = asyncio.run(return_summary(adapter, "hi"))
    json.dumps(result.trace)  # must not raise
