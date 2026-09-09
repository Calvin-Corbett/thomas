"""Caller-defined, schema-validated summary-only return channel.

Subagents and delegated runs otherwise return their full working transcript.
This module gives a caller an *automatic* way to instead receive only a compact,
schema-validated summary object — never the raw body.

The caller supplies a summary schema (for example
``{status, key_findings[], artifacts[], next_step}``). :func:`return_summary`:

1. Uses the caller schema, or a built-in :data:`DEFAULT_SUMMARY_SCHEMA` when the
   caller supplies none (this is what makes the channel *automatic* — a caller
   gets a validated summary even with zero configuration).
2. Instructs the model to return ONLY the summary fields — not the full working
   transcript, reasoning, or intermediate steps.
3. Validates the model output against the caller schema and self-repairs within
   a bounded loop, by delegating to
   :func:`thomas.core.structured_output.request_structured` (the validator and
   repair loop are reused, never duplicated here).
4. Returns a :class:`SummaryResult`: the validated summary object plus a tiny
   envelope (``schema_id`` and ``attempts``/``repaired`` bookkeeping). The raw
   model body is intentionally absent from the returned summary payload.

This module is core-clean: stdlib plus :mod:`thomas.core.structured_output`
(itself stdlib + optional ``jsonschema``) only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from thomas.core.structured_output import (
    DEFAULT_MAX_REPAIR_ATTEMPTS,
    LLMAdapter,
    StructuredResult,
    request_structured,
    validate_schema,
)

__all__ = [
    "DEFAULT_SUMMARY_SCHEMA",
    "SummaryResult",
    "schema_id_for",
    "return_summary",
]

# A sensible general-purpose summary schema for callers who define none. Kept
# permissive on presence (only ``status`` + ``key_findings`` required) but strict
# on shape (``additionalProperties`` false keeps the raw body out of the object).
DEFAULT_SUMMARY_SCHEMA: dict[str, Any] = {
    "title": "thomas.default_summary",
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success", "partial", "failed"]},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "next_step": {"type": "string"},
    },
    "required": ["status", "key_findings"],
    "additionalProperties": False,
}


@dataclass
class SummaryResult:
    """A validated summary-only response plus a tiny provenance envelope.

    Attributes:
        summary: the parsed, schema-valid summary object. This is the summary
            ONLY — the model's full working body is never carried here.
        schema_id: stable identifier of the summary schema that was enforced
            (the schema's ``$id``/``title`` when present, else a content hash).
        attempts: total model calls made (1 = valid on first try).
        repaired: True when at least one repair round-trip was needed.
        trace: per-attempt list of dicts with keys
            ``attempt``, ``raw``, ``errors``, ``valid``.
    """

    summary: Any
    schema_id: str
    attempts: int
    repaired: bool
    trace: list[dict[str, Any]] = field(default_factory=list)


def schema_id_for(schema: Mapping[str, Any]) -> str:
    """Return a stable identifier for ``schema``.

    Prefers the schema's own ``$id`` or ``title``; otherwise a short, stable
    content hash so identical schemas always resolve to the same id.
    """
    if isinstance(schema, Mapping):
        for key in ("$id", "title"):
            value = schema.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    canonical = json.dumps(schema, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"summary:{digest}"


def _summary_instruction() -> str:
    return (
        "You are producing a SUMMARY-ONLY return value for the caller. "
        "Do NOT return the full working transcript, your reasoning, or any "
        "intermediate steps. Condense everything into ONLY the fields defined by "
        "the summary schema that follows. Each field must be a concise "
        "distillation; omit the raw body entirely."
    )


def _with_summary_directive(
    messages: str | Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(messages, str):
        convo: list[dict[str, Any]] = [{"role": "user", "content": messages}]
    else:
        convo = [dict(m) for m in messages]
    convo.append({"role": "user", "content": _summary_instruction()})
    return convo


async def return_summary(
    adapter: LLMAdapter,
    messages: str | Sequence[Mapping[str, Any]],
    summary_schema: Mapping[str, Any] | None = None,
    *,
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
) -> SummaryResult:
    """Get a caller-defined, schema-validated summary-only object from an LLM.

    Args:
        adapter: LLM call adapter (see
            :data:`thomas.core.structured_output.LLMAdapter`). Injectable so
            tests run without a live model.
        messages: a plain prompt string or an OpenAI-style message list — the
            working context to be summarized.
        summary_schema: the caller's summary schema. When ``None``,
            :data:`DEFAULT_SUMMARY_SCHEMA` is used, making the channel automatic.
        max_repair_attempts: repair round-trips allowed after the initial call
            (total model calls = ``1 + max_repair_attempts``).

    Returns:
        SummaryResult with the validated summary object and the schema-id /
        attempt envelope. The full model body is NOT included.

    Raises:
        SchemaValidationError: ``summary_schema`` is not a sane JSON Schema.
        ValueError: ``max_repair_attempts`` is negative or not an integer.
        StructuredOutputError: no conforming summary within the bound; the
            exception carries the full per-attempt trace.
    """
    schema = DEFAULT_SUMMARY_SCHEMA if summary_schema is None else summary_schema
    # Validate the caller schema up front so schema_id reflects a real schema
    # and a malformed schema is rejected before any model call. request_structured
    # revalidates (idempotent) and owns the validation + bounded self-repair loop.
    validate_schema(schema)
    sid = schema_id_for(schema)

    result: StructuredResult = await request_structured(
        adapter,
        _with_summary_directive(messages),
        schema,
        max_repair_attempts=max_repair_attempts,
    )
    return SummaryResult(
        summary=result.data,
        schema_id=sid,
        attempts=result.attempts,
        repaired=result.repaired,
        trace=result.trace,
    )
