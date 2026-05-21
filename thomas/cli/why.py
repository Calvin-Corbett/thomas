"""thomas why <path> — on-demand architecture context for any file or directory."""

from __future__ import annotations

import click

from thomas._architecture import MODULES, RULES, resolve_module


@click.command("why")
@click.argument("path")
def why_command(path: str) -> None:
    """Show architecture context for a file or directory."""
    mod_name = resolve_module(path)
    if mod_name is None:
        click.echo(f"Could not resolve '{path}' to a known module.")
        click.echo(f"Known modules: {', '.join(sorted(MODULES.keys()))}")
        raise SystemExit(1)

    mod = MODULES[mod_name]
    tier = mod["tier"]
    tier_labels = {
        "core": "core (stable foundation)",
        "ext": "ext (extension)",
        "infra": "infra (cross-cutting)",
        "support": "support (utility)",
    }

    click.echo(f"Module:     {mod_name}")
    click.echo(f"Tier:       {tier_labels.get(tier, tier)}")
    click.echo(f"Depends on: {', '.join(mod['depends_on'])}")
    click.echo(f"Health:     {mod.get('health', 'unknown')}")
    click.echo(f"Desc:       {mod.get('description', '')}")

    debt = mod.get("debt", "")
    if debt:
        click.echo(f"Debt:       {debt}")

    click.echo(f"Max lines:  {RULES['max_file_lines_hard']} (new files)")

    if tier == "ext":
        click.echo("Rule:       extensions cannot import other extensions")
