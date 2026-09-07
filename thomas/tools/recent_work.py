"""``recent_work.list``: what Thomas made lately, from the record.

A fresh chat asked "what did I ask you to build earlier today, and what did I
ask you to make into a CSV?" and Thomas could only answer from shared memory:
the morning's Build conversations and the CSV delegation were on disk, listed
by the Library page, and out of the model's reach. This tool reads the same two
sources the Library shows, newest first, so the answer comes from the record
and carries the record's own verdict (a delegation filed as failed says so).

Every source is injected so a test drives a real temporary Build store and
stubbed execution records; the server registration fills in the live ones.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult

DEFAULT_LIMIT = 12
MAX_LIMIT = 40
DEFAULT_DAYS = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _when(value: Any) -> str:
    parsed = _parse(value)
    return parsed.strftime("%Y-%m-%d %H:%M UTC") if parsed else "unknown time"


class RecentWorkTool(Tool):
    name = "recent_work.list"
    category = "history"
    description = (
        "List what Thomas made recently, newest first, from the record: Build conversations (title, project "
        "folder, when) and chat deliverables (the ask, the files, and the recorded verdict). Use it when the "
        "user asks what they asked for, what was built or made, or what happened earlier, instead of guessing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": f"How many items at most (default {DEFAULT_LIMIT}, max {MAX_LIMIT})",
            },
            "days": {
                "type": "integer",
                "description": f"Only work touched within this many days (default {DEFAULT_DAYS})",
            },
        },
    }

    def __init__(
        self,
        *,
        conversation_roots: Callable[[], list[Path]],
        list_executions: Callable[[], list[dict[str, Any]]],
        get_execution: Callable[[str, str | Path | None], dict[str, Any] | None],
        list_conversations: Callable[[Path], list[dict[str, Any]]],
        now: Callable[[], str] = _now_iso,
    ) -> None:
        self._conversation_roots = conversation_roots
        self._list_executions = list_executions
        self._get_execution = get_execution
        # The Build record reader is injected: tools may not depend on forge
        # (thomas/_architecture.py), so the server hands the store's reader in.
        self._list_conversations = list_conversations
        self._now = now

    def _builds(self) -> list[tuple[datetime, str]]:
        rows: list[tuple[datetime, str]] = []
        seen: set[str] = set()
        for root in self._conversation_roots():
            try:
                summaries = self._list_conversations(root)
            except OSError:
                continue
            for summary in summaries:
                cid = str(summary.get("id") or "")
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                stamp = _parse(summary.get("updated_at") or summary.get("created_at"))
                if stamp is None:
                    continue
                title = str(summary.get("title") or "").strip() or "(untitled build)"
                rows.append((stamp, f"[Build] {title} — folder {Path(root).name} — {_when(stamp)}"))
        return rows

    def _deliverables(self) -> list[tuple[datetime, str]]:
        rows: list[tuple[datetime, str]] = []
        for row in self._list_executions():
            execution_id = str(row.get("execution_id") or "")
            stamp = _parse(row.get("updated_at") or row.get("created_at"))
            if not execution_id or stamp is None:
                continue
            detail = self._get_execution(execution_id, row.get("_record_root")) or {}
            ask = " ".join(str(detail.get("summary") or row.get("summary") or "").split())
            ask = ask[:160] or "(no summary recorded)"
            files = [
                str(f) for f in (detail.get("salvaged_artifacts") or detail.get("artifacts") or []) if str(f).strip()
            ]
            state = str(detail.get("state") or row.get("state") or "unknown")
            blocker = str(detail.get("blocker") or "").strip()
            verdict = f"{state}" + (f" ({blocker})" if blocker and state != "completed" else "")
            file_part = f" — files: {', '.join(files[:6])}" if files else ""
            rows.append((stamp, f"[Chat] {ask}{file_part} — recorded as {verdict} — {_when(stamp)}"))
        return rows

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            limit = max(1, min(int(args.get("limit") or DEFAULT_LIMIT), MAX_LIMIT))
            days = max(1, int(args.get("days") or DEFAULT_DAYS))
        except (TypeError, ValueError):
            return ToolResult(ok=False, error="limit and days must be whole numbers")
        now = _parse(self._now()) or datetime.now(timezone.utc)
        floor = now - timedelta(days=days)
        rows = [r for r in self._builds() + self._deliverables() if r[0] >= floor]
        if not rows:
            return ToolResult(ok=True, data=f"nothing recorded in the last {days} day(s)")
        rows.sort(key=lambda r: r[0], reverse=True)
        lines = [line for _, line in rows[:limit]]
        header = f"{len(rows)} item(s) in the last {days} day(s); showing {len(lines)}, newest first:"
        return ToolResult(ok=True, data="\n".join([header, *lines]))


__all__ = ["RecentWorkTool", "DEFAULT_DAYS", "DEFAULT_LIMIT", "MAX_LIMIT"]
