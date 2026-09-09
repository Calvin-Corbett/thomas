
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_MAX_LINES = 2000
_TRIM_TO = 1200
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _issues_path(repo_root: str | Path | None = None) -> Path:
    root = Path(repo_root) if repo_root else _REPO_ROOT
    return root / "runtime" / "logs" / "issues.jsonl"


def _is_test_run_writing_to_the_real_ledger(path: Path) -> bool:
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    try:
        return path.resolve() == (_REPO_ROOT / "runtime" / "logs" / "issues.jsonl").resolve()
    except OSError:
        return False


def record_issue(
    *,
    surface: str,
    kind: str,
    message: str,
    context: dict[str, Any] | None = None,
    repo_root: str | Path | None = None,
) -> None:
    """Append one issue line. Fail-silent: reporting must never break the app."""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "surface": str(surface or "unknown")[:40],
            "kind": str(kind or "error")[:40],
            "message": str(message or "")[:400],
            "context": {str(k)[:40]: str(v)[:200] for k, v in (context or {}).items()},
        }
        path = _issues_path(repo_root)
        if _is_test_run_writing_to_the_real_ledger(path):
            return
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _trim_if_needed(path)
    except (OSError, TypeError, ValueError) as exc:
        log.debug("issue ledger append failed: %s", exc)


def _trim_if_needed(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > _MAX_LINES:
            path.write_text("\n".join(lines[-_TRIM_TO:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def recent_issues(limit: int = 50, repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    try:
        path = _issues_path(repo_root)
        if not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-max(1, int(limit)) :]:
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    out.append(row)
            except (json.JSONDecodeError, TypeError):
                continue
        return out
    except OSError:
        return []


def summarize(hours: int = 24, repo_root: str | Path | None = None) -> dict[str, Any]:
    """The report: totals by kind/surface over the window + latest entries."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
    rows = recent_issues(limit=_MAX_LINES, repo_root=repo_root)
    windowed: list[dict[str, Any]] = []
    for row in rows:
        try:
            if datetime.fromisoformat(str(row.get("ts") or "")) >= cutoff:
                windowed.append(row)
        except ValueError:
            continue
    by_kind: dict[str, int] = {}
    by_surface: dict[str, int] = {}
    for row in windowed:
        by_kind[str(row.get("kind"))] = by_kind.get(str(row.get("kind")), 0) + 1
        by_surface[str(row.get("surface"))] = by_surface.get(str(row.get("surface")), 0) + 1
    return {
        "window_hours": hours,
        "total": len(windowed),
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "by_surface": dict(sorted(by_surface.items(), key=lambda kv: -kv[1])),
        "recent": windowed[-25:],
    }


__all__ = ["record_issue", "recent_issues", "summarize"]
