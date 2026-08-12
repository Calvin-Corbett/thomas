"""Schema-validated structured LLM output with a bounded self-repair loop.

Callers supply a JSON Schema and an LLM adapter (any sync or async callable
taking an OpenAI-style message list and returning the model's text, or a
mapping with a ``"text"`` key — ``LLMClient.chat`` satisfies this directly).
:func:`request_structured` then:

1. Validates the caller-supplied schema itself (:class:`SchemaValidationError`
   on a malformed schema).
2. Prompts the model for JSON conforming to the schema.
3. Validates the model output against the schema.
4. On failure, feeds the specific validation errors back to the model and
   retries, bounded by ``max_repair_attempts`` (default 2 repairs, i.e. at
   most ``1 + max_repair_attempts`` model calls).
5. Returns the validated object plus a per-attempt repair trace
   (:class:`StructuredResult`), or raises :class:`StructuredOutputError`
   carrying the full trace once the bound is exhausted.

Validation backend: if the optional ``jsonschema`` package is importable it is
used for both schema self-validation and instance validation (full Draft
2020-12 / draft-07 coverage). Otherwise a focused stdlib-only fallback
validator is used covering exactly these keywords, applied recursively through
``properties`` and ``items``:

- ``type`` (single string or list of strings; JSON primitive types only;
  ``bool`` is never accepted for ``integer``/``number``)
- ``required``
- ``properties``
- ``enum``
- ``items`` (single-schema form)
- ``additionalProperties`` (``false`` or a sub-schema)

Other JSON Schema keywords (``pattern``, ``minimum``, ``anyOf``, ``$ref``,
format checks, tuple-form ``items``, …) are NOT enforced by the fallback.

This module is core-clean: stdlib plus optional ``jsonschema`` only.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

try:
    import jsonschema as _jsonschema
except ImportError:  # pragma: no cover - exercised via monkeypatch in tests
    _jsonschema = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

DEFAULT_MAX_REPAIR_ATTEMPTS = 2

# Adapter contract: called with an OpenAI-style message list, returns the
# model's raw text (str), a mapping containing a "text" key, or an awaitable
# resolving to either.
LLMAdapter = Callable[[list[dict[str, Any]]], Any]

_JSON_TYPE_NAMES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})


class SchemaValidationError(ValueError):
    """The caller-supplied JSON Schema is itself invalid."""


class StructuredOutputError(RuntimeError):
    """The model failed to produce schema-conforming output within the repair bound.

    Attributes:
        trace: per-attempt list of dicts with keys
            ``attempt``, ``raw``, ``errors``, ``valid``.
    """

    def __init__(self, message: str, trace: list[dict[str, Any]]):
        super().__init__(message)
        self.trace = trace


@dataclass
class StructuredResult:
    """A validated structured-output response.

    Attributes:
        data: the parsed, schema-valid JSON value.
        attempts: total model calls made (1 = valid on first try).
        repaired: True when at least one repair round-trip was needed.
        trace: per-attempt list of dicts with keys
            ``attempt``, ``raw``, ``errors``, ``valid``.
    """

    data: Any
    attempts: int
    repaired: bool
    trace: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Schema self-validation
# ---------------------------------------------------------------------------


def validate_schema(schema: Any) -> None:
    """Validate that ``schema`` is a sane JSON Schema.

    Raises SchemaValidationError with a clear message when it is not.
    """
    if not isinstance(schema, Mapping):
        raise SchemaValidationError(f"schema must be a JSON object (mapping), got {type(schema).__name__}")
    if _jsonschema is not None:
        validator_cls = _jsonschema.validators.validator_for(dict(schema))
        try:
            validator_cls.check_schema(dict(schema))
        except _jsonschema.exceptions.SchemaError as exc:
            raise SchemaValidationError(f"invalid JSON Schema: {exc.message}") from exc
        return
    _check_schema_fallback(schema, path="$")


def _check_schema_fallback(schema: Mapping[str, Any], path: str) -> None:
    """Stdlib-only sanity check mirroring the fallback validator's coverage."""
    declared_type = schema.get("type")
    if declared_type is not None:
        types = declared_type if isinstance(declared_type, list) else [declared_type]
        for t in types:
            if not isinstance(t, str) or t not in _JSON_TYPE_NAMES:
                raise SchemaValidationError(
                    f"invalid JSON Schema at {path}: unknown type {t!r} (expected one of {sorted(_JSON_TYPE_NAMES)})"
                )
    required = schema.get("required")
    if required is not None and (not isinstance(required, list) or not all(isinstance(k, str) for k in required)):
        raise SchemaValidationError(f"invalid JSON Schema at {path}: 'required' must be a list of strings")
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        raise SchemaValidationError(f"invalid JSON Schema at {path}: 'enum' must be a non-empty list")
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            raise SchemaValidationError(f"invalid JSON Schema at {path}: 'properties' must be an object")
        for key, sub in properties.items():
            if not isinstance(sub, Mapping):
                raise SchemaValidationError(
                    f"invalid JSON Schema at {path}.properties.{key}: sub-schema must be an object"
                )
            _check_schema_fallback(sub, path=f"{path}.properties.{key}")
    items = schema.get("items")
    if items is not None:
        if not isinstance(items, Mapping):
            raise SchemaValidationError(
                f"invalid JSON Schema at {path}: 'items' must be an object "
                "(tuple-form items is not supported by the fallback validator)"
            )
        _check_schema_fallback(items, path=f"{path}.items")
    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, (bool, Mapping)):
        raise SchemaValidationError(
            f"invalid JSON Schema at {path}: 'additionalProperties' must be a boolean or an object"
        )
    if isinstance(additional, Mapping):
        _check_schema_fallback(additional, path=f"{path}.additionalProperties")


# ---------------------------------------------------------------------------
# Instance validation
# ---------------------------------------------------------------------------


def validate_instance(instance: Any, schema: Mapping[str, Any]) -> list[str]:
    """Validate ``instance`` against ``schema``; return a list of error strings.

    Empty list means valid. Uses ``jsonschema`` when installed, otherwise the
    focused fallback validator documented in the module docstring.
    """
    if _jsonschema is not None:
        validator_cls = _jsonschema.validators.validator_for(dict(schema))
        validator = validator_cls(dict(schema))
        errors: list[str] = []
        for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
            errors.append(f"{_format_path(err.absolute_path)}: {err.message}")
        return errors
    return _validate_fallback(instance, schema, path="$")


def _format_path(parts: Any) -> str:
    out = "$"
    for part in parts:
        out += f".{part}" if isinstance(part, str) else f"[{part}]"
    return out


def _type_matches(instance: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(instance, Mapping)
    if type_name == "array":
        return isinstance(instance, list)
    if type_name == "string":
        return isinstance(instance, str)
    if type_name == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if type_name == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if type_name == "boolean":
        return isinstance(instance, bool)
    return instance is None  # "null"


def _validate_fallback(instance: Any, schema: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    declared_type = schema.get("type")
    if declared_type is not None:
        types = declared_type if isinstance(declared_type, list) else [declared_type]
        if not any(_type_matches(instance, t) for t in types):
            expected = " or ".join(str(t) for t in types)
            errors.append(f"{path}: expected type {expected}, got {type(instance).__name__}")
            return errors  # type mismatch makes deeper checks meaningless
    enum = schema.get("enum")
    if enum is not None and instance not in enum:
        errors.append(f"{path}: value {instance!r} is not one of the allowed values {enum!r}")
    if isinstance(instance, Mapping):
        properties = schema.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        for key in schema.get("required") or []:
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        for key, sub in properties.items():
            if key in instance and isinstance(sub, Mapping):
                errors.extend(_validate_fallback(instance[key], sub, f"{path}.{key}"))
        additional = schema.get("additionalProperties")
        if additional is False:
            extras = sorted(set(instance) - set(properties))
            for key in extras:
                errors.append(f"{path}: unexpected property {key!r} (additionalProperties is false)")
        elif isinstance(additional, Mapping):
            for key in sorted(set(instance) - set(properties)):
                errors.extend(_validate_fallback(instance[key], additional, f"{path}.{key}"))
    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, Mapping):
            for i, element in enumerate(instance):
                errors.extend(_validate_fallback(element, items, f"{path}[{i}]"))
    return errors


# ---------------------------------------------------------------------------
# JSON extraction from model text
# ---------------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    candidate = text.strip()
    if not candidate.startswith("```"):
        return candidate
    lines = candidate.splitlines()
    # Drop the opening fence line (``` or ```json) and a trailing fence if present.
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


def _scan_balanced(text: str, opener: str, closer: str) -> str | None:
    start = text.find(opener)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json(text: str) -> tuple[Any, str | None]:
    """Extract a JSON value from model output text.

    Returns (value, None) on success or (None, error_message) on failure.
    Tolerates surrounding prose and markdown code fences.
    """
    candidate = _strip_code_fences(text)
    if not candidate:
        return None, "output was empty; expected a JSON value"
    try:
        return json.loads(candidate), None
    except json.JSONDecodeError as exc:
        first_error = f"output was not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"
    for opener, closer in (("{", "}"), ("[", "]")):
        fragment = _scan_balanced(candidate, opener, closer)
        if fragment is None:
            continue
        try:
            return json.loads(fragment), None
        except json.JSONDecodeError:
            continue
    return None, first_error


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _schema_instruction(schema: Mapping[str, Any]) -> str:
    return (
        "Respond with a single JSON value that conforms to the following JSON Schema. "
        "Output ONLY the JSON — no prose, no explanations, no markdown code fences.\n\n"
        f"JSON Schema:\n{json.dumps(dict(schema), indent=2, ensure_ascii=False)}"
    )


def _repair_instruction(errors: Sequence[str]) -> str:
    bullets = "\n".join(f"- {e}" for e in errors)
    return (
        "Your previous response did not conform to the required JSON Schema. "
        f"Validation errors:\n{bullets}\n\n"
        "Return a corrected JSON value that fixes every error listed above. "
        "Output ONLY the JSON."
    )


def _normalize_messages(messages: str | Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]
    return [dict(m) for m in messages]


async def _call_adapter(adapter: LLMAdapter, messages: list[dict[str, Any]]) -> str:
    result = adapter([dict(m) for m in messages])
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, Mapping):
        result = result.get("text", "")
    if not isinstance(result, str):
        raise TypeError(f"llm adapter must return str or a mapping with a 'text' key, got {type(result).__name__}")
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def request_structured(
    adapter: LLMAdapter,
    messages: str | Sequence[Mapping[str, Any]],
    schema: Mapping[str, Any],
    *,
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
) -> StructuredResult:
    """Request schema-validated JSON from an LLM, self-repairing within a bound.

    Args:
        adapter: LLM call adapter (see :data:`LLMAdapter`). Injectable so
            tests run without a live model.
        messages: a plain prompt string or an OpenAI-style message list. The
            schema instruction is appended as an additional user message.
        schema: caller-supplied JSON Schema the output must conform to.
        max_repair_attempts: how many repair round-trips are allowed after the
            initial call (total model calls = 1 + max_repair_attempts).

    Returns:
        StructuredResult with the validated value and the attempt/repair trace.

    Raises:
        SchemaValidationError: ``schema`` is not a sane JSON Schema.
        ValueError: ``max_repair_attempts`` is negative or not an integer.
        StructuredOutputError: no conforming output within the bound; the
            exception carries the full per-attempt trace.
    """
    validate_schema(schema)
    if isinstance(max_repair_attempts, bool) or not isinstance(max_repair_attempts, int):
        raise ValueError(f"max_repair_attempts must be an integer, got {type(max_repair_attempts).__name__}")
    if max_repair_attempts < 0:
        raise ValueError(f"max_repair_attempts must be >= 0, got {max_repair_attempts}")

    convo = _normalize_messages(messages)
    convo.append({"role": "user", "content": _schema_instruction(schema)})

    trace: list[dict[str, Any]] = []
    total_calls = 1 + max_repair_attempts
    for attempt in range(1, total_calls + 1):
        raw = await _call_adapter(adapter, convo)
        value, parse_error = extract_json(raw)
        errors = [parse_error] if parse_error is not None else validate_instance(value, schema)
        trace.append(
            {
                "attempt": attempt,
                "raw": raw,
                "errors": list(errors),
                "valid": not errors,
            }
        )
        if not errors:
            return StructuredResult(data=value, attempts=attempt, repaired=attempt > 1, trace=trace)
        log.debug(
            "structured output attempt %d/%d failed validation: %s",
            attempt,
            total_calls,
            "; ".join(errors[:5]),
        )
        if attempt < total_calls:
            convo.append({"role": "assistant", "content": raw})
            convo.append({"role": "user", "content": _repair_instruction(errors)})

    summary = "; ".join(trace[-1]["errors"][:5]) if trace else "no attempts recorded"
    raise StructuredOutputError(
        f"model output failed schema validation after {total_calls} attempt(s); last errors: {summary}",
        trace,
    )
