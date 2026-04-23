from __future__ import annotations

import json
from typing import Any

import click


@click.group()
@click.pass_context
def cron(ctx: click.Context) -> None:
    """Manage scheduled tasks (local scheduler)."""
    _ = ctx


def _emit_schedule_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    message = str(result.get("message") or "").strip()
    if message:
        click.echo(message)
    health = result.get("health")
    if health is not None:
        click.echo(f"health: {health}")
    table = str(result.get("table") or "").strip()
    if table:
        click.echo(table)
    nxt = result.get("next")
    if isinstance(nxt, list):
        click.echo("next:")
        for item in nxt:
            click.echo(f"- {item}")


@cron.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def cron_list(as_json: bool) -> None:
    """List scheduled tasks."""
    from thomas.tools.schedule import schedule_list

    _emit_schedule_result(schedule_list({}), as_json=as_json)


@cron.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def cron_status(as_json: bool) -> None:
    """Show scheduler status."""
    from thomas.tools.schedule import schedule_list

    _emit_schedule_result(schedule_list({}), as_json=as_json)


@cron.command("add")
@click.option("--id", "task_id", required=True, help="Task id.")
@click.option("--cron", "cron_expr", required=True, help="Cron expression.")
@click.option("--task", "task_text", required=True, help="Task text to execute.")
@click.option("--channel", default="default", show_default=True, help="Task channel label.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def cron_add(task_id: str, cron_expr: str, task_text: str, channel: str, as_json: bool) -> None:
    """Add or update a scheduled task."""
    from thomas.tools.schedule import schedule_add

    result = schedule_add({"id": task_id, "cron": cron_expr, "task": task_text, "channel": channel})
    _emit_schedule_result(result, as_json=as_json)


@cron.command("remove")
@click.argument("task_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def cron_remove(task_id: str, as_json: bool) -> None:
    """Remove a scheduled task."""
    from thomas.tools.schedule import schedule_remove

    _emit_schedule_result(schedule_remove({"id": task_id}), as_json=as_json)


@cron.command("run")
@click.argument("task_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def cron_run(task_id: str, as_json: bool) -> None:
    """Run a scheduled task now."""
    from thomas.tools.schedule import schedule_run_now

    _emit_schedule_result(schedule_run_now({"id": task_id}), as_json=as_json)


@cron.command("pause")
@click.argument("task_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def cron_pause(task_id: str, as_json: bool) -> None:
    """Pause a scheduled task."""
    from thomas.tools.schedule import schedule_pause

    _emit_schedule_result(schedule_pause({"id": task_id}), as_json=as_json)


@cron.command("resume")
@click.argument("task_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def cron_resume(task_id: str, as_json: bool) -> None:
    """Resume a paused scheduled task."""
    from thomas.tools.schedule import schedule_resume

    _emit_schedule_result(schedule_resume({"id": task_id}), as_json=as_json)


@cron.command("preview")
@click.argument("task_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def cron_preview(task_id: str, as_json: bool) -> None:
    """Preview upcoming execution times for a task."""
    from thomas.tools.schedule import schedule_preview

    _emit_schedule_result(schedule_preview({"id": task_id}), as_json=as_json)


@cron.command("update")
@click.argument("task_id")
@click.option("--cron", "cron_expr", required=False, help="New cron expression.")
@click.option("--task", "task_text", required=False, help="New task payload.")
@click.option("--channel", required=False, help="New channel label.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def cron_update(
    task_id: str,
    cron_expr: str | None,
    task_text: str | None,
    channel: str | None,
    as_json: bool,
) -> None:
    """Update task metadata."""
    from thomas.tools.schedule import schedule_update

    params: dict[str, Any] = {"id": task_id}
    if cron_expr is not None:
        params["cron"] = str(cron_expr)
    if task_text is not None:
        params["task"] = str(task_text)
    if channel is not None:
        params["channel"] = str(channel)
    _emit_schedule_result(schedule_update(params), as_json=as_json)


@cron.command("doctor")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def cron_doctor(as_json: bool) -> None:
    """Run a lightweight schedule consistency check."""
    from thomas.tools.schedule import schedule_list

    data = schedule_list({})
    if as_json:
        payload = dict(data)
        payload["doctor_ok"] = True
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _emit_schedule_result(data, as_json=False)
    click.echo("doctor_ok: True")


def register_cron_commands(cli: click.Group) -> None:
    if "cron" not in cli.commands:
        cli.add_command(cron)
