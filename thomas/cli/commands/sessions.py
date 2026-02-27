from __future__ import annotations

import json
import time
from typing import Any

import click

from thomas.core.config import AppConfig


@click.command("sessions")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option(
    "--active",
    "active_minutes",
    type=int,
    default=None,
    help="Only include sessions updated in the past N minutes.",
)
@click.pass_context
def sessions_cmd(ctx: click.Context, as_json: bool, active_minutes: int | None) -> None:
    """List persisted local chat sessions."""
    config: AppConfig = ctx.obj["config"]
    chats_dir = config.memory.root_path / ".thomas" / "chats"
    now_ms = int(time.time() * 1000)

    sessions: list[dict[str, Any]] = []
    if chats_dir.exists():
        for path in chats_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue

            sid = str(payload.get("id") or "").strip()
            if not sid:
                continue
            title = str(payload.get("title") or "Untitled").strip() or "Untitled"
            msgs = payload.get("messages")
            message_count = len(msgs) if isinstance(msgs, list) else 0

            try:
                updated_at = int(payload.get("updatedAt") or 0)
            except json.JSONDecodeError:
                updated_at = 0
            if updated_at <= 0:
                try:
                    updated_at = int(path.stat().st_mtime * 1000)
                except json.JSONDecodeError:
                    updated_at = now_ms

            age_minutes = max(0.0, float(now_ms - updated_at) / 60000.0)
            if active_minutes is not None and age_minutes > float(active_minutes):
                continue

            sessions.append(
                {
                    "id": sid,
                    "title": title,
                    "message_count": message_count,
                    "updated_at": updated_at,
                    "age_minutes": round(age_minutes, 2),
                    "file": str(path),
                }
            )

    sessions.sort(key=lambda x: int(x.get("updated_at", 0)), reverse=True)
    if as_json:
        click.echo(json.dumps({"count": len(sessions), "sessions": sessions}, ensure_ascii=False, indent=2))
        return

    click.echo(f"Sessions: {len(sessions)}")
    if not sessions:
        click.echo("(no persisted sessions found)")
        return
    for row in sessions:
        click.echo(f"- {row['id']} | {row['title']} | messages={row['message_count']} | age={row['age_minutes']}m")


def register_sessions_commands(cli: click.Group) -> None:
    if "sessions" not in cli.commands:
        cli.add_command(sessions_cmd)
