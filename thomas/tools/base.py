"""Tool base class and result types for Thomas."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$")


def _schema_type(schema: Dict[str, Any]) -> Optional[str]:
    raw = schema.get("type")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        for v in raw:
            if isinstance(v, str) and v != "null":
                return v
        for v in raw:
            if isinstance(v, str):
                return v
    return None


def _allows_null(schema: Dict[str, Any]) -> bool:
    raw = schema.get("type")
    if raw == "null":
        return True
    if isinstance(raw, list):
        return any(v == "null" for v in raw)
    return False


def _coerce_integer(value: Any) -> Tuple[Any, Optional[str]]:
    if isinstance(value, bool):
        return value, "expected integer, got boolean"
    if isinstance(value, int):
        return value, None
    if isinstance(value, float):
        if value.is_integer():
            return int(value), None
        return value, "expected integer, got float"
    if isinstance(value, str):
        s = value.strip()
        if _INT_RE.match(s):
            try:
                return int(s), None
            except ValueError:
                return value, "expected integer, got out-of-range string"
        return value, "expected integer, got non-numeric string"
    return value, f"expected integer, got {type(value).__name__}"


def _coerce_number(value: Any) -> Tuple[Any, Optional[str]]:
    if isinstance(value, bool):
        return value, "expected number, got boolean"
    if isinstance(value, (int, float)):
        return float(value), None
    if isinstance(value, str):
        s = value.strip()
        if _FLOAT_RE.match(s):
            try:
                return float(s), None
            except ValueError:
                return value, "expected number, got out-of-range string"
        return value, "expected number, got non-numeric string"
    return value, f"expected number, got {type(value).__name__}"


def _coerce_boolean(value: Any) -> Tuple[Any, Optional[str]]:
    if isinstance(value, bool):
        return value, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value), None
        return value, "expected boolean, got non-boolean number"
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"true", "1", "yes", "on"}:
            return True, None
        if s in {"false", "0", "no", "off"}:
            return False, None
        return value, "expected boolean, got non-boolean string"
    return value, f"expected boolean, got {type(value).__name__}"


def _coerce_string(value: Any) -> Tuple[Any, Optional[str]]:
    if isinstance(value, str):
        return value, None
    if isinstance(value, (int, float, bool)):
        return str(value), None
    return value, f"expected string, got {type(value).__name__}"


def _coerce_with_schema(value: Any, schema: Dict[str, Any], path: str) -> Tuple[Any, List[str]]:
    errors: List[str] = []
    if value is None:
        if _allows_null(schema):
            return None, []
        return value, [f"{path}: value is null but null is not allowed"]

    kind = _schema_type(schema)
    if kind == "integer":
        coerced, err = _coerce_integer(value)
        if err:
            return value, [f"{path}: {err}"]
        return coerced, []

    if kind == "number":
        coerced, err = _coerce_number(value)
        if err:
            return value, [f"{path}: {err}"]
        return coerced, []

    if kind == "boolean":
        coerced, err = _coerce_boolean(value)
        if err:
            return value, [f"{path}: {err}"]
        return coerced, []

    if kind == "string":
        coerced, err = _coerce_string(value)
        if err:
            return value, [f"{path}: {err}"]
        return coerced, []

    if kind == "array":
        if not isinstance(value, list):
            return value, [f"{path}: expected array, got {type(value).__name__}"]
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            return value, []
        out: List[Any] = []
        for idx, item in enumerate(value):
            coerced_item, item_errs = _coerce_with_schema(item, item_schema, f"{path}[{idx}]")
            out.append(coerced_item)
            errors.extend(item_errs)
        return out, errors

    if kind == "object":
        if not isinstance(value, dict):
            return value, [f"{path}: expected object, got {type(value).__name__}"]
        out = dict(value)
        required = schema.get("required")
        if isinstance(required, list):
            for name in required:
                key = str(name)
                if key not in out:
                    errors.append(f"{path}.{key}: missing required field")
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        additional_schema = schema.get("additionalProperties")
        additional_schema = additional_schema if isinstance(additional_schema, dict) else None
        for key, current in list(out.items()):
            prop_schema = properties.get(key)
            if not isinstance(prop_schema, dict):
                prop_schema = additional_schema
            if not isinstance(prop_schema, dict):
                continue
            coerced_val, prop_errs = _coerce_with_schema(current, prop_schema, f"{path}.{key}")
            out[key] = coerced_val
            errors.extend(prop_errs)
        return out, errors

    # Unknown/missing schema type: leave as-is.
    return value, []


def _normalize_args(args: Any, schema: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    if args is None:
        raw_args: Any = {}
    else:
        raw_args = args
    if not isinstance(raw_args, dict):
        return None, [f"args: expected object, got {type(raw_args).__name__}"]
    if not isinstance(schema, dict) or not schema:
        return dict(raw_args), []
    coerced, errors = _coerce_with_schema(raw_args, schema, "args")
    if not isinstance(coerced, dict):
        return None, errors or ["args: expected object"]
    return coerced, errors


@dataclass
class ToolResult:
    """Result from a tool execution."""

    ok: bool
    data: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_content(self, max_len: int = 50_000) -> str:
        """Serialize to a string for inclusion in LLM messages."""
        if not self.ok:
            return json.dumps({"ok": False, "error": self.error or "unknown error"})
        if isinstance(self.data, str):
            text = self.data
        else:
            text = json.dumps(self.data, ensure_ascii=False, default=str)
        if len(text) > max_len:
            text = text[:max_len - 50] + f"\n... (truncated, {len(text)} chars total)"
        return text


@dataclass
class ToolSpec:
    """OpenAI-compatible tool specification for sending to LLMs."""

    name: str
    description: str
    parameters: Dict[str, Any]

    def to_openai(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class Tool:
    """Base class for Thomas tools.

    Subclass and implement execute() to create a tool.
    """

    name: str = ""
    category: str = "general"
    description: str = ""
    parameters: Dict[str, Any] = {}

    async def execute(self, args: Dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def get_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def safe_execute(self, args: Dict[str, Any]) -> ToolResult:
        """Execute with error handling and timing."""
        start = time.monotonic()
        try:
            normalized_args, arg_errors = _normalize_args(args, self.parameters)
            if arg_errors:
                return ToolResult(
                    ok=False,
                    error="Invalid tool arguments: " + "; ".join(arg_errors[:4]),
                    duration_ms=(time.monotonic() - start) * 1000,
                )
            result = await self.execute(normalized_args or {})
            result.duration_ms = (time.monotonic() - start) * 1000
            return result
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return ToolResult(
                ok=False,
                error=f"{type(e).__name__}: {e}",
                duration_ms=duration,
            )
