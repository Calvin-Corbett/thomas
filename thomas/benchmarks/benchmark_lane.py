"""Benchmark lane helpers for audited dirty-worktree benchmark runs."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BENCHMARK_MODE_ENV = "THOMAS_BENCHMARK_MODE"
BENCHMARK_RUN_ID_ENV = "THOMAS_BENCHMARK_RUN_ID"
BENCHMARK_REASON_ENV = "THOMAS_BENCHMARK_REASON"
BENCHMARK_ROOT_ENV = "THOMAS_BENCHMARK_ROOT"
BENCHMARK_ENV_KEYS = (
    BENCHMARK_MODE_ENV,
    BENCHMARK_RUN_ID_ENV,
    BENCHMARK_REASON_ENV,
    BENCHMARK_ROOT_ENV,
)
BENCHMARK_RELATIVE_ROOT = Path("output") / "benchmarks"
BENCHMARK_AUDIT_BASENAME = "benchmark_audit.jsonl"


def _is_truthy(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "y", "on"}


def _commonpath_startswith(parent: Path, child: Path) -> bool:
    try:
        return Path(os.path.commonpath([str(parent), str(child)])).resolve() == parent.resolve()
    except ValueError:
        return False


def benchmark_root_parent(repo_root: Path) -> Path:
    return (repo_root.resolve() / BENCHMARK_RELATIVE_ROOT).resolve()


def resolve_benchmark_root(repo_root: Path, raw_root: str) -> tuple[Path | None, str | None]:
    text = str(raw_root or "").strip()
    if not text:
        return None, f"{BENCHMARK_ROOT_ENV} is required"
    try:
        candidate = Path(text).expanduser().resolve()
    except OSError as exc:
        return None, f"{BENCHMARK_ROOT_ENV} could not be resolved: {exc}"
    allowed_parent = benchmark_root_parent(repo_root)
    if not _commonpath_startswith(allowed_parent, candidate):
        return None, (
            f"{BENCHMARK_ROOT_ENV} must resolve under {allowed_parent}"
        )
    return candidate, None


def get_benchmark_context(
    repo_root: Path,
    *,
    env: dict[str, str] | None = None,
) -> tuple[dict[str, str] | None, str | None]:
    values = dict(env or os.environ)
    if not _is_truthy(values.get(BENCHMARK_MODE_ENV, "")):
        return None, None

    missing = [key for key in BENCHMARK_ENV_KEYS[1:] if not str(values.get(key, "")).strip()]
    if missing:
        return None, f"benchmark mode requested but missing env keys: {', '.join(missing)}"

    resolved_root, root_error = resolve_benchmark_root(repo_root, str(values.get(BENCHMARK_ROOT_ENV, "")))
    if root_error is not None or resolved_root is None:
        return None, root_error or "invalid benchmark root"

    return {
        "mode": "benchmark",
        "lane": "benchmark",
        "run_id": str(values.get(BENCHMARK_RUN_ID_ENV, "")).strip(),
        "reason": str(values.get(BENCHMARK_REASON_ENV, "")).strip(),
        "root": str(resolved_root),
        "audit_path": str((resolved_root / BENCHMARK_AUDIT_BASENAME).resolve()),
    }, None


def audit_benchmark_event(
    context: dict[str, str] | None,
    *,
    event: str,
    decision: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if not context:
        return
    audit_path = Path(str(context.get("audit_path") or "")).resolve()
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": str(context.get("run_id") or ""),
        "lane": str(context.get("lane") or "benchmark"),
        "reason": str(context.get("reason") or ""),
        "allowed_root": str(context.get("root") or ""),
        "event": str(event or ""),
        "decision": str(decision or ""),
        "payload": payload or {},
    }
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


__all__ = [
    "BENCHMARK_AUDIT_BASENAME",
    "BENCHMARK_ENV_KEYS",
    "BENCHMARK_MODE_ENV",
    "BENCHMARK_REASON_ENV",
    "BENCHMARK_ROOT_ENV",
    "BENCHMARK_RUN_ID_ENV",
    "audit_benchmark_event",
    "benchmark_root_parent",
    "get_benchmark_context",
    "resolve_benchmark_root",
]
