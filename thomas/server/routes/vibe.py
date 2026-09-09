"""Compatibility shim for vibe event helpers."""

from __future__ import annotations

from .vibe_trace import build_vibe_graph_event, build_vibe_trace_event, tool_node_id, tool_node_label

__all__ = [
    "build_vibe_graph_event",
    "build_vibe_trace_event",
    "tool_node_id",
    "tool_node_label",
]
