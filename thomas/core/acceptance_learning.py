"""Every caught miss becomes a permanent check for the project (Self-Harness style).

A miss is a contract item that was unmet when the work first claimed done. Whether
the retry then fixed it (caught) or it reached the user (escaped), the item is
recorded under the project's Praxis root and joins every later contract for that
project. Persisted as one JSON file; read at contract build time.

Root rule (see ``project_root``): a repo keeps its own record under
``runtime/coordination/verification``; a bare folder (a benchmark container, a
scratch dir) records under the user's own Praxis root so the workspace is never
polluted with Thomas bookkeeping.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from thomas.core.acceptance_contract import KIND_DATA_FIELD, KIND_LEARNED, KIND_OUTPUT_PATH, ContractItem
from thomas.core.project_root import resolve_project_root, user_praxis_root

_FILE = "learned_checks.json"
_MAX_ROWS = 200
_MAX_LOADED = 40


def learning_root(workspace: str | Path, *, env: dict[str, str] | None = None) -> Path:
    ws = Path(workspace).resolve()
    root = resolve_project_root(ws, env=env)
    if (root / ".git").exists() or (root / "runtime").is_dir():
        return root
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", ws.name).strip("-").lower() or "workspace"
    digest = hashlib.sha1(str(ws).encode("utf-8", errors="replace")).hexdigest()[:8]
    return user_praxis_root(env) / "projects" / f"{slug}-{digest}"


def learned_path(root: Path) -> Path:
    return root / "runtime" / "coordination" / "verification" / _FILE


def _read(path: Path) -> list[dict[str, Any]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def load_learned(workspace: str | Path, *, env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Rows for ``build_contract(learned=...)``: a data field or output path keeps
    its target so it is re-checked; everything else returns as a judgement reminder."""

    rows = _read(learned_path(learning_root(workspace, env=env)))
    rows.sort(key=lambda r: (-int(r.get("count") or 0), str(r.get("last_seen") or "")))
    out: list[dict[str, Any]] = []
    ws = Path(workspace)
    for row in rows[:_MAX_LOADED]:
        kind = str(row.get("kind") or "")
        if kind == KIND_DATA_FIELD and not any(ws.rglob(str(row.get("source") or "\0"))):
            continue
        if kind == KIND_OUTPUT_PATH and not Path(str(row.get("target") or "")).parent.is_dir():
            continue
        if kind not in {KIND_DATA_FIELD, KIND_OUTPUT_PATH}:
            kind = KIND_LEARNED
        out.append(
            {
                "item_id": f"learned:{row.get('item_id') or ''}"
                if kind == KIND_LEARNED
                else str(row.get("item_id") or ""),
                "kind": kind,
                "description": str(row.get("description") or ""),
                "source": str(row.get("source") or "learned"),
                "target": str(row.get("target") or ""),
            }
        )
    return out


def record_misses(
    workspace: str | Path,
    items: Sequence[ContractItem],
    *,
    caught: bool,
    run_id: str = "",
    env: dict[str, str] | None = None,
) -> Path | None:
    """Upsert every item in ``items`` (the misses) into the project's record.
    Returns the file written, or None when there was nothing to record."""

    misses = [it for it in items if it.description]
    if not misses:
        return None
    path = learned_path(learning_root(workspace, env=env))
    rows = _read(path)
    by_id = {str(r.get("item_id") or ""): r for r in rows}
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for it in misses:
        row = by_id.get(it.item_id)
        if row is None:
            row = {
                "item_id": it.item_id,
                "kind": it.kind,
                "description": it.description,
                "source": it.source,
                "target": it.target,
                "count": 0,
                "caught": 0,
                "escaped": 0,
                "first_seen": stamp,
            }
            rows.append(row)
            by_id[it.item_id] = row
        bucket = "caught" if caught else "escaped"
        row["count"] = int(row.get("count") or 0) + 1
        row[bucket] = int(row.get(bucket) or 0) + 1
        row["last_seen"] = stamp
        row["last_detail"] = it.detail[:300]
        if run_id:
            row["last_run_id"] = run_id
    rows = sorted(rows, key=lambda r: -int(r.get("count") or 0))[:_MAX_ROWS]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


__all__ = ["learning_root", "learned_path", "load_learned", "record_misses"]
