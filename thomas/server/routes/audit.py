"""Audit log API routes.

GET /api/audit/files
    Query recent file changes across all runs.
    Query params: run_id, path, model, action, since, limit, offset

GET /api/audit/runs/<run_id>/files
    All file changes for a specific run, plus aggregate summary.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from thomas.observability.file_audit import list_file_changes, get_run_summary

log = logging.getLogger(__name__)


def _json(data: Any, status: int = 200) -> tuple[bytes, int, dict]:
    body = json.dumps(data, ensure_ascii=False, default=str).encode()
    return body, status, {"Content-Type": "application/json"}


def _parse_int(val: Any, default: int, min_val: int = 0, max_val: int = 500) -> int:
    try:
        return max(min_val, min(max_val, int(val)))
    except (TypeError, ValueError):
        return default


async def handle_audit_files(request: Any) -> tuple[bytes, int, dict]:
    """GET /api/audit/files"""
    try:
        qs = getattr(request, "query_string", b"")
        if isinstance(qs, bytes):
            qs = qs.decode("utf-8", errors="replace")

        params: Dict[str, str] = {}
        if qs:
            for part in qs.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v

        run_id = params.get("run_id") or None
        path_contains = params.get("path") or None
        model = params.get("model") or None
        action = params.get("action") or None
        since_iso = params.get("since") or None
        limit = _parse_int(params.get("limit"), 50, max_val=200)
        offset = _parse_int(params.get("offset"), 0)

        changes = list_file_changes(
            run_id=run_id,
            path_contains=path_contains,
            model=model,
            action=action,
            since_iso=since_iso,
            limit=limit,
            offset=offset,
        )
        return _json({"changes": changes, "count": len(changes)})
    except Exception as e:
        log.exception("audit files error")
        return _json({"error": str(e)}, 500)


async def handle_audit_run_files(request: Any, run_id: str) -> tuple[bytes, int, dict]:
    """GET /api/audit/runs/<run_id>/files"""
    try:
        changes = list_file_changes(run_id=run_id, limit=200)
        summary = get_run_summary(run_id)
        return _json({"run_id": run_id, "summary": summary, "changes": changes})
    except Exception as e:
        log.exception("audit run files error")
        return _json({"error": str(e)}, 500)
