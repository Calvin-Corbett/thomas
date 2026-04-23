"""Compatibility shim for benchmark lane helpers."""

from __future__ import annotations

from thomas.core.benchmark_lane import (
    BENCHMARK_AUDIT_BASENAME,
    BENCHMARK_ENV_KEYS,
    BENCHMARK_MODE_ENV,
    BENCHMARK_REASON_ENV,
    BENCHMARK_REPO_ROOT_ENV,
    BENCHMARK_ROOT_ENV,
    BENCHMARK_RUN_ID_ENV,
    BENCHMARK_SINGLE_AGENT_ENV,
    BENCHMARK_WORKBOARD_PATH_ENV,
    audit_benchmark_event,
    benchmark_mode_enabled,
    benchmark_root_parent,
    benchmark_single_agent_enabled,
    get_benchmark_context,
    resolve_benchmark_repo_root,
    resolve_benchmark_root,
    resolve_benchmark_workboard_path,
)

__all__ = [
    "BENCHMARK_AUDIT_BASENAME",
    "BENCHMARK_ENV_KEYS",
    "BENCHMARK_MODE_ENV",
    "BENCHMARK_REPO_ROOT_ENV",
    "BENCHMARK_REASON_ENV",
    "BENCHMARK_ROOT_ENV",
    "BENCHMARK_RUN_ID_ENV",
    "BENCHMARK_SINGLE_AGENT_ENV",
    "BENCHMARK_WORKBOARD_PATH_ENV",
    "audit_benchmark_event",
    "benchmark_mode_enabled",
    "benchmark_root_parent",
    "benchmark_single_agent_enabled",
    "get_benchmark_context",
    "resolve_benchmark_repo_root",
    "resolve_benchmark_root",
    "resolve_benchmark_workboard_path",
]
