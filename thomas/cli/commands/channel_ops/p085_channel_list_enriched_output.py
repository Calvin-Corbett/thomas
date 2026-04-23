from __future__ import annotations

import typer

try:  # pragma: no cover
    from rich.console import Console
    from rich.table import Table
except ImportError:  # pragma: no cover
    Console = None  # type: ignore[assignment,misc]
    Table = None  # type: ignore[assignment,misc]

from thomas.channels.p085_channel_list_enriched_output import (
    ChannelListEnrichedOutputError,
    ChannelListEnrichedRequest,
    ChannelListEnrichedResponse,
    channel_list_enriched_output,
    error_to_json,
    response_to_json,
)

# Typer sub-app intended to be mounted under a higher-level `channels` command group.
app = typer.Typer(add_completion=False, help="List channels with enriched metadata.")

# Common discovery hooks used across Thomas CLI modules.
cli = app
typer_app = app
COMMAND_NAME = "list"


def register(parent_app: typer.Typer) -> None:
    """Register this op module on a parent Typer app."""

    parent_app.add_typer(app, name=COMMAND_NAME, help=app.info.help)


@app.callback(invoke_without_command=True)
def list_channels(
    ctx: typer.Context,
    limit: int = typer.Option(100, "--limit", min=0, help="Max channels to return (0 means no limit)."),
    offset: int = typer.Option(0, "--offset", min=0, help="Number of channels to skip before returning results."),
    integration: str | None = typer.Option(
        None,
        "--integration",
        "-i",
        help="Integration/platform to list channels from (defaults to configured integration).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON instead of a human table."),
) -> None:
    """List channels and print enriched output.

    JSON success:
      {"count": N, "channels": [...]}

    JSON failure:
      {"error": {"code": "...", "message": "...", "details": {...}}}
    """

    try:
        response = _run(ctx=ctx, integration=integration, limit=limit, offset=offset)
    except ChannelListEnrichedOutputError as err:
        if json_output:
            typer.echo(error_to_json(err))
        else:
            _print_error(err)
        raise typer.Exit(code=2)

    if json_output:
        typer.echo(response_to_json(response))
        return

    _print_human(response)


def _run(*, ctx: typer.Context, integration: str | None, limit: int, offset: int) -> ChannelListEnrichedResponse:
    request = ChannelListEnrichedRequest(integration=integration, limit=limit, offset=offset)
    return channel_list_enriched_output(request, ctx=ctx)


def _print_error(err: ChannelListEnrichedOutputError) -> None:
    if Console is None:
        typer.echo(f"Error: {err.code}: {err.message}")
        return
    console = Console()
    console.print(f"[red]Error:[/red] {err.code}: {err.message}")


def _print_human(response: ChannelListEnrichedResponse) -> None:
    if Console is None or Table is None:
        for ch in response.channels:
            private = "" if ch.is_private is None else ("private" if ch.is_private else "public")
            typer.echo(f"{ch.platform}\t{ch.id}\t{ch.name}\t{ch.kind or ''}\t{private}")
        return

    console = Console()
    table = Table(title=f"Channels ({response.count})")
    table.add_column("Platform", overflow="fold")
    table.add_column("ID", overflow="fold")
    table.add_column("Name", overflow="fold")
    table.add_column("Kind", overflow="fold")
    table.add_column("Username", overflow="fold")
    table.add_column("Private", overflow="fold")
    table.add_column("Members", justify="right")

    for ch in response.channels:
        priv = "" if ch.is_private is None else ("yes" if ch.is_private else "no")
        table.add_row(
            ch.platform,
            ch.id,
            ch.name,
            ch.kind or "",
            ch.username or "",
            priv,
            "" if ch.member_count is None else str(ch.member_count),
        )

    console.print(table)
