"""Panel-rendering methods extracted from ``ThomasREPL``."""

from __future__ import annotations

from typing import Any

from rich.panel import Panel


class ThomasREPLPanelsMixin:
    """Mixin: rich panel rendering for help, activity, and logs."""

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
            return f"{ts}[red]❌ {message}[/red]"

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
                icon = "✔"
                color = "green"
            elif status == "error":
                icon = "❌"
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
        except (ImportError, RuntimeError, OSError, ValueError, TypeError):
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
