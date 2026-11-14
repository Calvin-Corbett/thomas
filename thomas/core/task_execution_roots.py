"""Find task records without confusing the task's project with the server cwd.

Explicit roots remain strict. User-level lookups include the user's one-off
board, legacy installation records, linked projects, and roots registered when
a task was created. Each project has its own index entry, so concurrent starts
in different projects never overwrite a shared list.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from thomas.core.project_root import resolve_project_root, user_praxis_root
from thomas.core.shared_root_sandbox import coordination_root as ledger_root
from thomas.core.task_bot_lock import _write_json

log = logging.getLogger(__name__)
RECORDS_DIR = Path("runtime") / "coordination" / "task_bots"


def _root_key(root: Path) -> str:
    return os.path.normcase(str(root.resolve()))


def _index_dir() -> Path:
    return ledger_root(user_praxis_root()) / "runtime" / "coordination" / "task_roots"


def index_path(root: Path) -> Path:
    key = hashlib.sha256(_root_key(root).encode("utf-8")).hexdigest()
    return _index_dir() / f"{key}.json"


def register_root(repo_root: str | Path | None) -> Path:
    root = resolve_project_root(explicit=repo_root)
    path = index_path(root)
    if _read_object(path).get("root_path") != str(root):
        _write_json(path, {"root_path": str(root)})
    return root


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, ValueError, RecursionError):
        log.warning("Cannot read task root index entry %s", path, exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def roots_for_user(legacy_root: Path) -> list[Path]:
    """Return known roots only; never walk projects or create records while listing."""
    resolved_paths: dict[Path, Path] = {}

    def canonical(root: Path) -> Path:
        # Request-local reuse keeps registry changes visible on the next read.
        if root not in resolved_paths:
            resolved_paths[root] = root.resolve()
        return resolved_paths[root]

    data = user_praxis_root()
    roots = [resolve_project_root(), data, legacy_root]
    index_dir = _index_dir()
    for entry in sorted(index_dir.glob("*.json")):
        raw = _read_object(entry).get("root_path")
        if isinstance(raw, str) and raw.strip() and Path(raw).is_absolute():
            root = canonical(Path(raw))
            key = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()
            if entry.name == f"{key}.json":
                roots.append(root)

    # Projects that already had tasks before the index was introduced remain
    # discoverable through the existing local-project registry.
    registry_bases = [data, Path.cwd(), legacy_root]
    registry_bases.extend(
        Path(raw).expanduser()
        for key in ("THOMAS_HOME", "THOMAS_STATE_DIR")
        if (raw := os.environ.get(key, "").strip())
    )
    for base in registry_bases:
        projects = _read_object(base / ".thomas" / "linked_projects.json").get("projects", [])
        for project in projects if isinstance(projects, list) else []:
            raw = project.get("root_path") if isinstance(project, dict) else None
            if isinstance(raw, str) and raw.strip() and Path(raw).is_absolute():
                roots.append(Path(raw))

    unique: dict[str, Path] = {}
    for root in roots:
        resolved = canonical(root)
        unique.setdefault(os.path.normcase(str(resolved)), resolved)
    return list(unique.values())


def execution_root(execution_id: str, repo_root: str | Path | None, legacy_root: Path) -> Path:
    if repo_root is not None:
        return resolve_project_root(explicit=repo_root)
    matches = [
        root
        for root in roots_for_user(legacy_root)
        if (ledger_root(root) / RECORDS_DIR / f"{execution_id}.json").is_file()
    ]
    if len(matches) > 1:
        raise ValueError(f"execution `{execution_id}` exists in multiple projects; specify its project")
    return matches[0] if matches else resolve_project_root()


def combine_summaries(summaries: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for summary in summaries:
        for row in summary.get("executions", []):
            key = str(row.get("execution_id") or "")
            if key in rows:
                duplicates.add(key)
            rows[key] = row
    # Never let an ambiguous id direct Cancel/Steer to an arbitrary copy.
    for key in duplicates:
        rows.pop(key, None)
        log.warning("Ambiguous task id omitted from user task list: %s", key)
    ordered = sorted(rows.values(), key=lambda row: (str(row.get("updated_at", "")), row["execution_id"]), reverse=True)
    from thomas.core.task_bot_states import TERMINAL_STATES

    return {
        "generated_at": generated_at,
        "execution_count": len(ordered),
        "active_count": sum(row.get("state") not in TERMINAL_STATES and not row.get("stale") for row in ordered),
        "stale_count": sum(bool(row.get("stale")) for row in ordered),
        "blocked_count": sum(row.get("state") == "blocked" for row in ordered),
        "awaiting_proof_count": sum(row.get("state") == "awaiting_proof" for row in ordered),
        "executions": ordered,
    }


def user_rows(legacy_root, read_summary, records_dir, generated_at) -> list[dict[str, Any]]:
    summaries = []
    for root in roots_for_user(legacy_root):
        if not records_dir(root).is_dir():
            continue
        summary = read_summary(root)
        summaries.append(
            {
                "executions": [dict(row, _record_root=str(root)) for row in summary.get("executions", [])],
            }
        )
    return combine_summaries(summaries, generated_at)["executions"]
