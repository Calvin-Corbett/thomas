"""Activity-feed tracking methods extracted from ``ThomasREPL``."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class ThomasREPLActivityMixin:
    """Mixin: activity-feed recording and keyboard navigation."""

    def _activity_allows(self, level: str) -> bool:
        order = {"minimal": 0, "normal": 1, "debug": 2}
        target = order.get(str(level or "normal"), 1)
        current = order.get(str(self._activity_verbosity or "normal"), 1)
        return target <= current

    def _activity_event_verbosity(self, event_type: str) -> str:
        if event_type in {"phase_start", "phase_end"}:
            return "minimal"
        if event_type in {"tool_call", "tool_result"}:
            return "normal"
        if event_type == "memory_event":
            return "debug"
        if event_type == "warning":
            return "debug"
        if event_type == "error":
            return "normal"
        return "normal"

    def _append_log(self, message: str) -> None:
        if not str(message or "").strip():
            return
        ts = datetime.now().strftime("%H:%M:%S")
        for idx, line in enumerate(str(message).splitlines() or [""]):
            prefix = f"{ts} " if idx == 0 else "      "
            self._logs.append(f"{prefix}{line}")

        if self._logs_panel_open:
            self._render_panels()

    def _record_activity(self, payload: dict[str, Any] | str, *, level: str = "normal") -> None:
        if isinstance(payload, str):
            payload = {"type": "status", "message": payload, "level": level}

        event_type = str(payload.get("type") or "status")
        if not self._activity_allows(level):
            return
        if not self._activity_allows(self._activity_event_verbosity(event_type)):
            return

        if event_type in {"tool_call", "tool_result"}:
            self._handle_tool_activity_event(payload)
            return

        if event_type in {"phase_start", "phase_end"}:
            self._activity_feed.append(
                {
                    "type": event_type,
                    "phase": str(payload.get("phase") or ""),
                    "duration_ms": payload.get("duration_ms"),
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "id": str(payload.get("id") or ""),
                }
            )
        elif event_type == "memory_event":
            self._activity_feed.append(
                {
                    "type": "memory_event",
                    "query": str(payload.get("query") or ""),
                    "hits": payload.get("hits"),
                    "score": payload.get("score"),
                    "duration_ms": payload.get("duration_ms"),
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            )
        elif event_type in {"warning", "error", "status"}:
            message = str(payload.get("message") or "").strip()
            if message:
                self._activity_feed.append(
                    {
                        "type": event_type,
                        "message": message,
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
                )
        else:
            message = str(payload.get("message") or "").strip()
            if message:
                self._activity_feed.append(
                    {
                        "type": "status",
                        "message": message,
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
                )

        self._rebuild_activity_tool_index()
        if self._activity_panel_open:
            self._render_panels()

    def _rebuild_activity_tool_index(self) -> None:
        self._activity_tool_index = {}
        for idx, row in enumerate(self._activity_feed):
            if str(row.get("type")) == "tool":
                tool_id = str(row.get("tool_id") or "")
                if tool_id:
                    self._activity_tool_index[tool_id] = idx
        if self._activity_tool_selected_id and self._activity_tool_selected_id not in self._activity_tool_index:
            self._activity_tool_selected_id = None

    def _tool_rows(self) -> list[tuple[int, dict[str, Any]]]:
        rows: list[tuple[int, dict[str, Any]]] = []
        for idx, row in enumerate(self._activity_feed):
            if str(row.get("type")) == "tool":
                rows.append((idx, row))
        return rows

    def _tool_row_order(self) -> list[str]:
        rows = self._tool_rows()
        rows.sort(key=lambda item: item[0])
        return [str(item[1].get("tool_id") or "") for item in rows]

    def _cycle_activity_tool_selection(self, direction: int) -> None:
        tool_ids = self._tool_row_order()
        if not tool_ids:
            self._activity_tool_selected_id = None
            return
        if self._activity_tool_selected_id not in tool_ids:
            self._activity_tool_selected_id = tool_ids[0]
            return
        idx = tool_ids.index(self._activity_tool_selected_id)
        self._activity_tool_selected_id = tool_ids[(idx + direction) % len(tool_ids)]

    def _toggle_activity_tool_expansion(self) -> None:
        if not self._activity_tool_selected_id:
            return
        if self._activity_tool_selected_id in self._expanded_tool_events:
            self._expanded_tool_events.remove(self._activity_tool_selected_id)
        else:
            self._expanded_tool_events.add(self._activity_tool_selected_id)

    def _handle_tool_activity_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "")
        tool_id = str(payload.get("tool_id") or "").strip()
        if not tool_id:
            return

        name = str(payload.get("tool_name") or "")
        short_label = str(payload.get("short_label") or "")
        command = str(payload.get("command") or "")

        if event_type == "tool_call":
            for row in self._activity_feed:
                if str(row.get("type")) == "tool" and str(row.get("tool_id") or "") == tool_id:
                    row.update(
                        {
                            "tool_name": name or str(row.get("tool_name") or ""),
                            "short_label": short_label or str(row.get("short_label") or ""),
                            "command": command or str(row.get("command") or ""),
                            "status": "running",
                            "ok": None,
                            "duration_ms": None,
                            "bytes_out": None,
                            "result_preview": "",
                            "stderr": "",
                            "time": datetime.now().strftime("%H:%M:%S"),
                        }
                    )
                    self._rebuild_activity_tool_index()
                    if self._activity_panel_open:
                        self._render_panels()
                    return
            self._activity_feed.append(
                {
                    "type": "tool",
                    "tool_id": tool_id,
                    "tool_name": name,
                    "short_label": short_label,
                    "command": command,
                    "status": "running",
                    "ok": None,
                    "duration_ms": None,
                    "bytes_out": None,
                    "result_preview": "",
                    "stderr": "",
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            )
            if not self._activity_tool_selected_id:
                self._activity_tool_selected_id = tool_id
            self._rebuild_activity_tool_index()
            if self._activity_panel_open:
                self._render_panels()
            return

        if event_type == "tool_result":
            updated = False
            for row in self._activity_feed:
                if str(row.get("type")) != "tool":
                    continue
                if str(row.get("tool_id") or "") != tool_id:
                    continue
                row.update(
                    {
                        "status": "ok" if bool(payload.get("ok", False)) else "error",
                        "ok": bool(payload.get("ok", False)),
                        "duration_ms": payload.get("duration_ms"),
                        "bytes_out": payload.get("bytes_out"),
                        "result_preview": str(payload.get("result_preview") or row.get("result_preview") or ""),
                        "stderr": str(payload.get("stderr") or row.get("stderr") or ""),
                        "tool_name": name or str(row.get("tool_name") or ""),
                        "short_label": short_label or str(row.get("short_label") or ""),
                        "command": command or str(row.get("command") or ""),
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
                )
                updated = True
            if not updated:
                self._activity_feed.append(
                    {
                        "type": "tool",
                        "tool_id": tool_id,
                        "tool_name": name,
                        "short_label": short_label,
                        "command": command,
                        "status": "ok" if bool(payload.get("ok", False)) else "error",
                        "ok": bool(payload.get("ok", False)),
                        "duration_ms": payload.get("duration_ms"),
                        "bytes_out": payload.get("bytes_out"),
                        "result_preview": str(payload.get("result_preview") or ""),
                        "stderr": str(payload.get("stderr") or ""),
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
                )
            self._rebuild_activity_tool_index()
            if self._activity_panel_open:
                self._render_panels()
            return
