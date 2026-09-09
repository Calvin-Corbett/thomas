"""User-facing CLI framing helpers for the Thomas product shell."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore[assignment]

START_HERE_COMMANDS = ("quickstart", "setup", "status", "doctor")
EVERYDAY_COMMANDS = ("repl", "chat", "serve", "dashboard", "models", "memory", "sessions", "library")
BUILD_COMMANDS = ("browser", "tools", "plugins", "skills", "gateway", "companion", "channels", "message", "webhooks")


def section_rule(width: int = 34) -> str:
    return "-" * max(12, int(width))


def print_section_heading(title: str, *, color: str = "cyan") -> None:
    click.echo("")
    click.echo(click.style(f"  {title}", fg=color, bold=True))
    click.echo(click.style(f"  {section_rule(len(title) + 4)}", fg=color))


def print_step_heading(step_number: int, title: str) -> None:
    print_section_heading(f"Step {int(step_number)}: {title}", color="green")


def _command_rows(group: click.Group, names: Sequence[str]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for name in names:
        command = group.commands.get(name)
        if command is None:
            continue
        desc = str(command.get_short_help_str(limit=88) or "").strip()
        rows.append((name, desc))
    return rows


def _other_command_rows(group: click.Group, excluded: set[str]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for name in group.list_commands(click.Context(group)):
        if name in excluded:
            continue
        command = group.commands.get(name)
        if command is None:
            continue
        rows.append((name, str(command.get_short_help_str(limit=88) or "").strip()))
    return rows


class ProductShellGroup(click.Group):
    """Click group that presents Thomas as a tiered product shell."""

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        if not self.commands:
            return

        formatter.write_paragraph()
        formatter.write_text("Plain `thomas` starts the interactive REPL when run in a terminal.")

        start_here_rows = _command_rows(self, START_HERE_COMMANDS)
        everyday_rows = _command_rows(self, EVERYDAY_COMMANDS)
        build_rows = _command_rows(self, BUILD_COMMANDS)
        excluded = set(START_HERE_COMMANDS) | set(EVERYDAY_COMMANDS) | set(BUILD_COMMANDS)
        other_rows = _other_command_rows(self, excluded)

        with formatter.section("Start Here"):
            formatter.write_text(
                "Use the simplest path first. Builder and operator systems stay available when you need them."
            )
            formatter.write_dl(start_here_rows)

        with formatter.section("Everyday Use"):
            formatter.write_dl(everyday_rows)

        with formatter.section("Build And Extend"):
            formatter.write_dl(build_rows)

        if other_rows:
            with formatter.section("More Commands"):
                formatter.write_dl(other_rows)


def build_status_experience(payload: Mapping[str, Any]) -> dict[str, Any]:
    config_exists = bool(payload.get("config_exists"))
    config_ok = bool(payload.get("ok"))
    profile_count = int(payload.get("profile_count") or 0)
    default_model = str(payload.get("default_model") or "").strip()
    worktree_clean = payload.get("worktree_clean")

    if not config_exists or profile_count <= 0 or not default_model:
        state = "needs_setup"
        summary = "Thomas is not configured for everyday use yet."
        next_steps = [
            "thomas quickstart  - fastest path to first chat",
            "thomas setup       - guided setup if you want to choose provider/model details",
            "thomas doctor      - diagnose local runtime issues",
        ]
    elif not config_ok:
        state = "needs_attention"
        summary = "Thomas is configured, but the current runtime config needs attention."
        next_steps = [
            "thomas config validate --strict  - inspect config errors",
            "thomas doctor                    - diagnose common setup and connectivity issues",
            "thomas setup                     - re-run guided setup if needed",
        ]
    else:
        state = "ready"
        summary = "Thomas is configured and ready for everyday use."
        next_steps = [
            "thomas repl          - interactive everyday mode",
            'thomas chat "hello"  - one-shot question',
            "thomas serve         - local web UI at http://127.0.0.1:8899",
        ]

    note = ""
    if worktree_clean is False:
        note = "Git worktree is dirty. That matters for repo development, not normal chat use."

    return {
        "state": state,
        "summary": summary,
        "next_steps": next_steps,
        "note": note,
    }
