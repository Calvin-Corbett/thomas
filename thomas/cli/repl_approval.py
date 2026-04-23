"""REPL approval handler - interactive tool-use guardrails with diff preview.

Provides the ``ReplApprovalHandler`` that bridges the agent's
``GuardedToolRunner`` with the REPL's prompt_toolkit UI so that risky tool
calls (file writes, shell execution) can be approved/denied by the user.
"""

from __future__ import annotations

import difflib
import importlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Tool categories

_FILE_WRITE_TOOLS: set[str] = {
    "fs.write_file",
    "fs.edit_file",
    "fs.delete_file",
    "fs.move",
    "fs.copy",
    "fs.create_dir",
}

_SHELL_TOOLS: set[str] = {
    "shell.exec",
    "shell.run",
}

_SENSITIVE_TOOLS: set[str] = _FILE_WRITE_TOOLS | _SHELL_TOOLS


class ReplApprovalHandler:
    """Interactive approval handler for the REPL guardrail system.

    Integrates with ``GuardedToolRunner`` via a callback-based approval
    broker that pauses the agent loop to ask the user for permission.
    """

    def __init__(self, console: Any, config: Any) -> None:
        self._console = console
        self._config = config
        self._pause_ui: Callable[[], None] | None = None
        self._resume_ui: Callable[[], None] | None = None
        self._running = False
        self._auto_approve: set[str] = set()  # tool names to auto-approve

    def set_ui_callbacks(
        self,
        *,
        pause_ui: Callable[[], None] | None = None,
        resume_ui: Callable[[], None] | None = None,
    ) -> None:
        """Register callbacks that pause/resume the spinner during approval prompts."""
        self._pause_ui = pause_ui
        self._resume_ui = resume_ui

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def create_guarded_runner(self, config: Any) -> Any:
        """Create a ``GuardedToolRunner`` wired to this approval handler.

        Returns ``None`` if the policy/approval infrastructure is unavailable,
        which causes the agent loop to run tools without guardrails (suitable
        for low-risk or high-autonomy modes).
        """
        try:
            from thomas.agent.approval import ApprovalBroker
            from thomas.agent.guarded_tools import GuardedToolRunner

            policy_module = importlib.import_module("thomas.policy")
            redact_module = importlib.import_module("thomas.policy.redact")
            policy_cls = policy_module.PolicyEngine
            redactor_cls = redact_module.Redactor

            policy = policy_cls.from_config(config)
            approvals = ApprovalBroker(
                handler=self._handle_approval_request,
            )
            redactor = redactor_cls.from_config(config)

            return GuardedToolRunner(
                policy=policy,
                approvals=approvals,
                redactor=redactor,
            )
        except Exception as exc:
            log.debug("Guardrail setup skipped: %s", exc)
            return None

    async def _handle_approval_request(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Called by the approval broker when a tool needs user permission."""
        if not self._running:
            return True  # If handler not running, auto-approve

        # Auto-approve if previously allowed
        if tool_name in self._auto_approve:
            return True

        # Pause spinner if callback registered
        if self._pause_ui:
            self._pause_ui()

        try:
            return await self._prompt_approval(tool_name, args)
        finally:
            if self._resume_ui:
                self._resume_ui()

    async def _prompt_approval(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Show an interactive approval prompt for a tool call."""
        # Display tool call details
        self._console.print()
        self._console.print(f"[bold yellow]Approval needed:[/bold yellow] [cyan]{tool_name}[/cyan]")

        # Show relevant args
        if tool_name in _FILE_WRITE_TOOLS:
            path = args.get("path") or args.get("file_path") or args.get("filepath", "")
            self._console.print(f"  Path: [dim]{path}[/dim]")
            content = args.get("content", "")
            if content and len(content) < 500:
                self._console.print("  Content preview:")
                for line in content.splitlines()[:10]:
                    self._console.print(f"  [dim]  {line}[/dim]")
                if content.count("\n") > 10:
                    self._console.print(f"  [dim]  ... ({content.count(chr(10))} total lines)[/dim]")
        elif tool_name in _SHELL_TOOLS:
            cmd = args.get("command", "")
            self._console.print(f"  Command: [dim]{cmd[:200]}[/dim]")
        else:
            args_str = json.dumps(args, indent=2, ensure_ascii=False)
            if len(args_str) > 300:
                args_str = args_str[:300] + "..."
            self._console.print(f"  Args: [dim]{args_str}[/dim]")

        self._console.print()
        self._console.print(
            "  [green]y[/green] approve  |  [red]n[/red] deny  |  [yellow]a[/yellow] always approve this tool"
        )

        try:
            from prompt_toolkit import prompt as pt_prompt

            answer = pt_prompt("  > ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return False

        if answer in ("y", "yes"):
            return True
        elif answer in ("a", "always"):
            self._auto_approve.add(tool_name)
            return True
        return False


def create_repl_approval_handler(console: Any, config: Any) -> ReplApprovalHandler:
    """Factory function for creating a configured approval handler."""
    return ReplApprovalHandler(console, config)


def render_post_edit_summary(
    console: Any,
    tool_name: str,
    args: dict[str, Any],
    ok: bool,
    sandbox_path: Path,
) -> None:
    """Display a compact diff summary after a file-write tool completes.

    Shows added/removed line counts and a brief preview of changes.
    """
    if not ok:
        return

    path_str = args.get("path") or args.get("file_path") or args.get("filepath", "")
    if not path_str:
        return

    file_path = sandbox_path / path_str if not Path(path_str).is_absolute() else Path(path_str)

    if tool_name == "fs.edit_file":
        old_str = args.get("old_string", "")
        new_str = args.get("new_string", "")
        if old_str or new_str:
            diff_lines = list(
                difflib.unified_diff(
                    old_str.splitlines(keepends=True),
                    new_str.splitlines(keepends=True),
                    fromfile="before",
                    tofile="after",
                    lineterm="",
                )
            )
            added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
            if added or removed:
                console.print(f"    [dim]+{added} -{removed} lines[/dim]")

    elif tool_name == "fs.write_file":
        content = args.get("content", "")
        if content:
            line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
            console.print(f"    [dim]{line_count} lines written[/dim]")

    elif tool_name == "fs.delete_file":
        console.print(f"    [dim]deleted: {path_str}[/dim]")
