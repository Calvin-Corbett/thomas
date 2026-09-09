"""Vibe trace stream event helpers for chat runtime telemetry."""

from __future__ import annotations

import re
import time
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    if status in {"pending", "active", "success", "error", "skipped"}:
        return status
    return "pending"


def _safe_kind(value: str | None) -> str:
    kind = str(value or "").strip().lower()
    return kind or "step"


def tool_node_id(tool_name: str | None) -> str:
    raw = str(tool_name or "").strip().lower()
    if not raw:
        return "tool.unknown"
    normalized = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-")
    return f"tool.{normalized or 'unknown'}"


def tool_node_label(tool_name: str | None) -> str:
    name = str(tool_name or "").strip()
    return f"Tool {name}" if name else "Tool"


def build_vibe_graph_event(
    *,
    trace_id: str,
    session_id: str = "",
    profile: str = "",
    mode: str = "",
    autonomy_level: int = 3,
) -> dict[str, Any]:
    nodes = [
        {"id": "user.input", "label": "User Input", "kind": "user", "summary": "Inbound user message"},
        {"id": "api.chat.request", "label": "API Request", "kind": "server", "summary": "Chat endpoint accepted"},
        {"id": "session.resolve", "label": "Session Resolve", "kind": "server", "summary": "Runtime/session setup"},
        {"id": "response.stream", "label": "Response Stream", "kind": "stream", "summary": "Model output stream"},
        {"id": "tool.exec", "label": "Tool Execution", "kind": "tool", "summary": "Tool call lifecycle"},
    ]
    edges = [
        {"from": "user.input", "to": "api.chat.request"},
        {"from": "api.chat.request", "to": "session.resolve"},
        {"from": "session.resolve", "to": "response.stream"},
        {"from": "session.resolve", "to": "tool.exec"},
    ]
    return {
        "type": "vibe_graph",
        "trace_id": str(trace_id or ""),
        "run_id": str(trace_id or ""),
        "graph": {
            "nodes": nodes,
            "edges": edges,
        },
        "meta": {
            "session_id": str(session_id or ""),
            "profile": str(profile or ""),
            "mode": str(mode or ""),
            "autonomy_level": int(autonomy_level or 3),
            "ts_ms": _now_ms(),
        },
    }


def build_vibe_trace_event(
    *,
    trace_id: str,
    node_id: str,
    status: str,
    label: str | None = None,
    detail: str | None = None,
    kind: str | None = None,
    parent_node_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "vibe_trace",
        "trace_id": str(trace_id or ""),
        "run_id": str(trace_id or ""),
        "node_id": str(node_id or ""),
        "status": _safe_status(status),
        "label": str(label or node_id or ""),
        "detail": str(detail or ""),
        "kind": _safe_kind(kind),
        "ts_ms": _now_ms(),
    }
    parent = str(parent_node_id or "").strip()
    if parent:
        payload["parent_node_id"] = parent
    if isinstance(metadata, dict) and metadata:
        payload["metadata"] = metadata
    return payload
