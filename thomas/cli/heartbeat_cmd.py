"""thomas heartbeat — CLI entry point for the heartbeat system."""

from __future__ import annotations

import json

import click


@click.command("heartbeat")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--fix", is_flag=True, help="Auto-fix fixable failures.")
@click.option("--list", "list_flag", is_flag=True, help="List all available checks.")
@click.option("--tags", default="", help="Filter checks by tag (comma-separated).")
@click.argument("checks", nargs=-1)
def heartbeat_command(
    as_json: bool,
    fix: bool,
    list_flag: bool,
    tags: str,
    checks: tuple,
) -> None:
    """Run automated project health checks (all token-free)."""
    from thomas.system.heartbeat import (
        format_text_report,
        list_checks,
        run_heartbeat,
    )

    if list_flag:
        all_checks = list_checks()
        if as_json:
            click.echo(json.dumps(all_checks, ensure_ascii=False, indent=2))
        else:
            for c in all_checks:
                fix_mark = " [fixable]" if c["has_fix"] else ""
                tag_str = f" ({', '.join(c['tags'])})" if c["tags"] else ""
                click.echo(f"  {c['name']}{fix_mark}{tag_str}")
                click.echo(f"    {c['description']}")
        return

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    check_names = list(checks) if checks else None

    report = run_heartbeat(checks=check_names, fix=fix, tags=tag_list)

    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        click.echo(format_text_report(report))

    if not report.get("ok"):
        raise SystemExit(1)
