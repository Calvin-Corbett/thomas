"""Guardrails posture helpers shared by preference routes and runtime loading."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ._types import (
    _GUARDRAIL_POSTURE_ORDER,
    _GUARDRAIL_RUNTIME_MIN_FIELDS,
    _GUARDRAIL_RUNTIME_MINIMA,
    _GUARDRAIL_TOOL_ALLOW_FIELDS,
    _GUARDRAIL_TOOL_MAXIMA,
    _GUARDRAIL_TOOL_MIN_FIELDS,
    _GUARDRAIL_TOOL_MINIMA,
)


def normalize_guardrails_posture(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "": "standard",
        "default": "standard",
        "standard": "standard",
        "normal": "standard",
        "guided": "standard",
        "safe": "standard",
        "protected": "locked",
        "lock": "locked",
        "locked": "locked",
        "strict": "locked",
        "maximum": "locked",
        "max": "locked",
        "builder": "builder",
        "build": "builder",
        "development": "builder",
        "dev": "builder",
        "expert": "builder",
        "none": "builder",
        "minimal": "builder",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in _GUARDRAIL_POSTURE_ORDER else "standard"


def guardrails_posture_requires_auth(current_posture: Any, target_posture: Any) -> bool:
    current = normalize_guardrails_posture(current_posture)
    target = normalize_guardrails_posture(target_posture)
    return _GUARDRAIL_POSTURE_ORDER.get(target, 1) < _GUARDRAIL_POSTURE_ORDER.get(current, 1)


def compute_enforcement_mode(posture: Any, allow_third_party_agent_access: Any) -> str:
    normalized = normalize_guardrails_posture(posture)
    if normalized == "builder" and bool(allow_third_party_agent_access):
        return "development"
    return "protected"


def sync_guardrails_security_state(advanced: Mapping[str, Any] | None) -> dict[str, Any]:
    current = deepcopy(dict(advanced or {}))
    security = dict(current.get("security") or {})
    posture = normalize_guardrails_posture(security.get("guardrails_posture"))
    security["guardrails_posture"] = posture
    security["enforcement_mode"] = compute_enforcement_mode(
        posture,
        security.get("allow_third_party_agent_access", True),
    )
    current["security"] = security
    return current


def apply_guardrails_posture_overlay(advanced: Mapping[str, Any] | None) -> dict[str, Any]:
    current = sync_guardrails_security_state(advanced)
    security = dict(current.get("security") or {})
    posture = normalize_guardrails_posture(security.get("guardrails_posture"))
    tools = dict(current.get("tools") or {})
    runtime = dict(current.get("runtime") or {})

    for field in _GUARDRAIL_TOOL_ALLOW_FIELDS:
        if not bool(_GUARDRAIL_TOOL_MAXIMA.get(posture, {}).get(field, True)):
            tools[field] = False

    for field in _GUARDRAIL_TOOL_MIN_FIELDS:
        if bool(_GUARDRAIL_TOOL_MINIMA.get(posture, {}).get(field, False)):
            tools[field] = True

    for field in _GUARDRAIL_RUNTIME_MIN_FIELDS:
        if bool(_GUARDRAIL_RUNTIME_MINIMA.get(posture, {}).get(field, False)):
            runtime[field] = True

    current["security"] = security
    current["tools"] = tools
    current["runtime"] = runtime
    return current


def guardrails_patch_weakening_fields(
    current_advanced: Mapping[str, Any] | None,
    incoming_advanced_patch: Mapping[str, Any] | None,
    *,
    ignore_runtime_fields: bool = False,
) -> list[str]:
    current = dict(current_advanced or {})
    incoming = dict(incoming_advanced_patch or {})
    weakened: list[str] = []

    current_tools = dict(current.get("tools") or {})
    incoming_tools = dict(incoming.get("tools") or {})
    for field in _GUARDRAIL_TOOL_ALLOW_FIELDS:
        if field in incoming_tools and bool(incoming_tools.get(field)) and not bool(current_tools.get(field, True)):
            weakened.append(f"advanced.tools.{field}")
    for field in _GUARDRAIL_TOOL_MIN_FIELDS:
        if field in incoming_tools and not bool(incoming_tools.get(field)) and bool(current_tools.get(field, False)):
            weakened.append(f"advanced.tools.{field}")

    current_runtime = dict(current.get("runtime") or {})
    incoming_runtime = dict(incoming.get("runtime") or {})
    if not ignore_runtime_fields:
        for field in _GUARDRAIL_RUNTIME_MIN_FIELDS:
            if (
                field in incoming_runtime
                and not bool(incoming_runtime.get(field))
                and bool(current_runtime.get(field, False))
            ):
                weakened.append(f"advanced.runtime.{field}")

    return weakened
