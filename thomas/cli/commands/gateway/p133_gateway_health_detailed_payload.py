"""CLI command: Gateway health (detailed payload).

This command queries a running Gateway over WebSocket and prints a *detailed*
health snapshot.

Properties:
- Deterministic errors (invalid input / missing config / external failures)
- Machine-readable mode via `--json`

Implementation reuses the server helper in:
`thomas.server.routes.gateway.p133_gateway_health_detailed_payload`
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click

from thomas.server.routes.gateway.p133_gateway_health_detailed_payload import (
    DEFAULT_TIMEOUT_MS,
    GatewayHealthDetailedRequest,
    GatewayHealthError,
    fetch_gateway_health_detailed,
)


@click.command()
@click.option(
    "--url",
    "url",
    default=None,
    help="Gateway WebSocket URL (ws://... or wss://...). If omitted, uses server config/env.",
)
@click.option("--token", "token", default=None, help="Gateway auth token")
@click.option("--password", "password", default=None, help="Gateway auth password")
@click.option(
    "--timeout",
    "timeout_ms",
    default=DEFAULT_TIMEOUT_MS,
    show_default=True,
    type=int,
    help="Timeout budget in ms",
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
def gateway_health_detailed_payload(
    url: str | None,
    token: str | None,
    password: str | None,
    timeout_ms: int,
    as_json: bool,
) -> None:
    """Query a running Gateway for a detailed health snapshot."""
    ctx = click.get_current_context()
    req = GatewayHealthDetailedRequest(url=url, token=token, password=password, timeout_ms=timeout_ms)

    try:
        result = asyncio.run(fetch_gateway_health_detailed(req))
        payload = result.to_dict()
        if as_json:
            click.echo(json.dumps(payload, sort_keys=True))
        else:
            _print_human(payload)
        ctx.exit(0)
    except GatewayHealthError as e:
        if as_json:
            click.echo(json.dumps(e.to_error_dict(), sort_keys=True))
        else:
            click.echo(f"{e.error_type}: {e.code}: {e.message}")
            if e.details:
                click.echo(json.dumps(e.details, sort_keys=True))
        ctx.exit(1)


def _print_human(payload: dict[str, Any]) -> None:
    gateway = payload.get("gateway", {}) if isinstance(payload.get("gateway"), dict) else {}
    url = gateway.get("url", "<unknown>")
    duration = payload.get("duration_ms", "?")
    click.echo(f"Gateway health OK: {url} ({duration} ms)")

    snapshot = payload.get("snapshot")
    if snapshot is None:
        click.echo("Snapshot: <empty>")
        return

    if isinstance(snapshot, dict):
        keys = ", ".join(sorted(snapshot.keys()))
        click.echo(f"Snapshot keys: {keys}")
    else:
        click.echo(f"Snapshot type: {type(snapshot).__name__}")


COMMAND = gateway_health_detailed_payload


def register(group: Any) -> None:
    """Hook for click/typer group-based CLIs."""
    try:
        group.add_command(gateway_health_detailed_payload)
    except Exception:
        return


def main(argv: list[str] | None = None) -> int:
    """Programmatic entrypoint; returns an exit code."""
    try:
        gateway_health_detailed_payload.main(args=argv, standalone_mode=False)
        return 0
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
