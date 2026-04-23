"""Activity tracking, logging, and panel rendering extracted from ThomasREPL.

This mixin owns all activity-feed state, tool-event processing, and the
three side-panels (Help / Activity / Logs).  It is mixed in to ThomasREPL
via standard Python MRO.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from rich.panel import Panel

log = logging.getLogger(__name__)


class ThomasREPLActivityMixin:
    """Activity tracking, logging, and panel rendering mixin for ThomasREPL."""

    # ------------------------------------------------------------------
    # Verbosity helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_activity_time(self, duration_ms: Any) -> str:
        if duration_ms is None:
            return ""
        try:
            duration = float(duration_ms)
        except (TypeError, ValueError):
            return ""
        if duration < 1000:
            return f"{int(round(duration))}ms"
        return f"{duration / 1000:.1f}s"

    def _shorten(self, value: str, limit: int) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[: max(3, limit - 3)] + "..."

    # ------------------------------------------------------------------
    # Log buffer
    # ------------------------------------------------------------------

    def _append_log(self, message: str) -> None:
        if not str(message or "").strip():
            return
        ts = datetime.now().strftime("%H:%M:%S")
        for idx, line in enumerate(str(message).splitlines() or [""]):
            prefix = f"{ts} " if idx == 0 else "      "
            self._logs.append(f"{prefix}{line}")

        if self._logs_panel_open:
            self._render_panels()

    # ------------------------------------------------------------------
    # Activity recording
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Tool-event index
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Tool-event handler (tool_call / tool_result lifecycle)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Panel rendering
    # ------------------------------------------------------------------

    def _render_help_panel(self) -> None:
        lines = [
            "F1  Toggle Help",
            "F2  Toggle Activity",
            "F3  Toggle Logs",
            "Ctrl+Space  Commands",
            "Tab  Cycle panel focus",
            "Esc  Back in pickers",
        ]
        self._console.print(Panel("\n".join(lines), title="Help", border_style=self._mascot_style, expand=False))

    def _render_activity_row(self, row: dict[str, Any], *, selected: bool) -> str:
        event_type = str(row.get("type") or "")
        ts = str(row.get("time") or "").strip()
        if ts:
            ts = f"{ts} "

        if event_type == "phase_start":
            phase = str(row.get("phase") or "phase").strip()
            duration = self._format_activity_time(row.get("duration_ms"))
            suffix = f" ({duration})" if duration else ""
            label = f"{phase} start{suffix}"
            if selected:
                return f"{ts}[bold blue]{label}[/bold blue]"
            return f"{ts}[dim blue]{label}[/dim blue]"

        if event_type == "phase_end":
            phase = str(row.get("phase") or "phase").strip()
            duration = self._format_activity_time(row.get("duration_ms"))
            suffix = f" ({duration})" if duration else ""
            label = f"{phase} end{suffix}"
            if selected:
                return f"{ts}[bold blue]{label}[/bold blue]"
            return f"{ts}[dim]{label}[/dim]"

        if event_type == "memory_event":
            if self._activity_verbosity == "minimal":
                return ""
            query = str(row.get("query") or "").strip()
            score = row.get("score")
            bits = []
            if query:
                bits.append(self._shorten(query, 40))
            hits = row.get("hits")
            if hits is not None:
                bits.append(f"hits={hits}")
            if score is not None:
                bits.append(f"score={score}")
            duration = self._format_activity_time(row.get("duration_ms"))
            if duration:
                bits.append(duration)
            detail = f" ({', '.join(bits)})" if bits else ""
            if selected:
                return f"{ts}[bold magenta]memory{detail}[/bold magenta]"
            return f"{ts}[magenta]memory{detail}[/magenta]"

        if event_type == "warning":
            if self._activity_verbosity != "debug":
                return ""
            message = str(row.get("message") or "").strip()
            return f"{ts}[yellow]! {message}[/yellow]"

        if event_type == "error":
            message = str(row.get("message") or "").strip()
            return f"{ts}[red]\u274c {message}[/red]"

        if event_type == "tool":
            tool_name = str(row.get("tool_name") or "tool")
            short_label = str(row.get("short_label") or "").strip()
            display = f"tool: {tool_name}"
            if short_label:
                display = f"{display} {self._shorten(short_label, 54)}"
            duration = self._format_activity_time(row.get("duration_ms"))
            if duration:
                display = f"{display} ({duration})"
            status = str(row.get("status") or "running")
            if status == "ok":
                icon = "\u2714"
                color = "green"
            elif status == "error":
                icon = "\u274c"
                color = "red"
            else:
                icon = "..."
                color = "cyan"

            line = f"{display} {icon}"
            if self._activity_tool_selected_id == str(row.get("tool_id") or ""):
                return f"{ts}[{color}]> {line}[/{color}]"
            return f"{ts}[{color}]{line}[/{color}]"

        message = str(row.get("message") or "").strip()
        if not message:
            return ""
        return f"{ts}[dim]{message}[/dim]"

    def _activity_tool_details(self, row: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        command = str(row.get("command") or "").strip()
        if command:
            lines.append(f"  cmd: {self._shorten(command, 180)}")
        preview = str(row.get("result_preview") or "").strip()
        if preview:
            lines.append(f"  output: {self._shorten(preview, 240)}")
        stderr = str(row.get("stderr") or "").strip()
        if stderr:
            lines.append(f"  stderr: {self._shorten(stderr, 240)}")
        bytes_out = row.get("bytes_out")
        if bytes_out is not None:
            lines.append(f"  bytes: {bytes_out}")
        return [f"[dim]{line}[/dim]" for line in lines]

    def _render_activity_panel(self) -> None:
        rows = list(self._activity_feed)[-12:]
        content: list[str] = []
        if not rows:
            content.append("(no activity yet)")
        else:
            for row in rows:
                selected = str(row.get("tool_id") or "") == str(self._activity_tool_selected_id or "")
                line = self._render_activity_row(row, selected=selected)
                if line:
                    content.append(line)
                if (
                    selected
                    and self._activity_verbosity == "debug"
                    and str(row.get("tool_id") or "") in self._expanded_tool_events
                    and row.get("type") == "tool"
                ):
                    content.extend(self._activity_tool_details(row))
        self._console.print(
            Panel(
                "\n".join(content),
                title=f"Activity ({self._activity_verbosity})",
                border_style=self._mascot_style,
                expand=False,
            )
        )

    def _render_logs_panel(self) -> None:
        rows = list(self._logs)
        content = list(rows) if rows else ["(no logs yet)"]
        self._console.print(Panel("\n".join(content), title="Logs", border_style=self._mascot_style, expand=False))

    def _render_panels(self) -> None:
        try:
            from prompt_toolkit.application import run_in_terminal

            def _print_panels() -> None:
                if self._help_panel_open:
                    self._render_help_panel()
                if self._activity_panel_open:
                    self._render_activity_panel()
                if self._logs_panel_open:
                    self._render_logs_panel()

            run_in_terminal(_print_panels, render_cli_done=False)
        except Exception:
            if self._help_panel_open:
                self._render_help_panel()
            if self._activity_panel_open:
                self._render_activity_panel()
            if self._logs_panel_open:
                self._render_logs_panel()

    def _cycle_panel_focus(self) -> None:
        sequence = ["input"]
        if self._help_panel_open:
            sequence.append("help")
        if self._activity_panel_open:
            sequence.append("activity")
        if self._logs_panel_open:
            sequence.append("logs")
        if len(sequence) <= 1:
            self._panel_focus = "input"
            return
        try:
            idx = sequence.index(self._panel_focus)
        except ValueError:
            idx = 0
        self._panel_focus = sequence[(idx + 1) % len(sequence)]
