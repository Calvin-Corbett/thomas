from __future__ import annotations

"""CLI operation: evaluate a channel throttling policy.

This command is intentionally self-contained so it can be discovered/registered
by the existing Thomas CLI command loader.

Machine-readable output is supported via --json.
"""

import json
from pathlib import Path
from typing import Any, Optional

import typer

from thomas.channels.p089_channel_throttling_policy import (
    ChannelThrottleError,
    ChannelThrottlePolicy,
    InMemoryThrottleStateStore,
    JsonFileThrottleStateStore,
    ThrottleCheckRequest,
    load_throttle_policy_config_file,
    parse_throttle_policy_config,
)

COMMAND_NAME = "throttling-policy"


def _emit(payload: dict[str, Any], json_out: bool) -> None:
    if json_out:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return

    if payload.get("ok") is True:
        decision = payload.get("decision", {})
        allowed = decision.get("allowed")
        retry = decision.get("retry_after_seconds")
        bucket = decision.get("bucket_key")
        if allowed:
            typer.echo(f"ALLOWED bucket={bucket}")
        else:
            typer.echo(f"THROTTLED bucket={bucket} retry_after_seconds={retry}")
        return

    err = payload.get("error", {})
    typer.echo(f"ERROR {err.get('code')}: {err.get('message')}", err=True)


def throttling_policy(
    channel: str | None = typer.Option(
        None,
        "--channel",
        "-c",
        help="Channel/integration name (example: telegram).",
    ),
    bucket_key: str | None = typer.Option(
        None,
        "--bucket-key",
        help="Throttle bucket key. Defaults to the channel name.",
    ),
    cost: float = typer.Option(1.0, "--cost", help="Token cost for this event (default: 1)."),
    burst: int | None = typer.Option(None, "--burst", help="Maximum burst capacity (tokens)."),
    rate_per_second: float | None = typer.Option(
        None,
        "--rate-per-second",
        help="Refill rate in tokens per second.",
    ),
    rate_per_minute: float | None = typer.Option(
        None,
        "--rate-per-minute",
        help="Refill rate in tokens per minute.",
    ),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        dir_okay=False,
        help="Path to a JSON throttle policy config file.",
    ),
    state_file: Path | None = typer.Option(
        None,
        "--state-file",
        dir_okay=False,
        help="Path to a JSON file used to persist throttle state.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not persist state."),
    now: float | None = typer.Option(None, "--now", help="Epoch timestamp override (tests/automation)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Evaluate whether an event is allowed under a token-bucket policy."""

    try:
        if channel is None or not channel.strip():
            raise ChannelThrottleError("invalid_input", "channel must be a non-empty string")
        channel_name = channel.strip()

        if config_file is not None and any(v is not None for v in (burst, rate_per_second, rate_per_minute)):
            raise ChannelThrottleError(
                "invalid_input",
                "--config cannot be combined with --burst/--rate-per-second/--rate-per-minute",
            )

        if config_file is not None:
            config = load_throttle_policy_config_file(config_file, channel_name)
        else:
            raw: dict[str, Any] = {}
            if burst is not None:
                raw["burst"] = burst

            if rate_per_second is not None and rate_per_minute is not None:
                raise ChannelThrottleError("invalid_input", "provide only one of --rate-per-second/--rate-per-minute")
            if rate_per_second is not None:
                raw["rate_per_second"] = rate_per_second
            if rate_per_minute is not None:
                raw["rate_per_minute"] = rate_per_minute

            if "burst" not in raw or not any(k in raw for k in ("rate_per_second", "rate_per_minute")):
                raise ChannelThrottleError(
                    "missing_config",
                    "missing throttle policy configuration (provide --config or --burst and a rate)",
                )

            config = parse_throttle_policy_config(raw)

        store = JsonFileThrottleStateStore(state_file) if state_file is not None else InMemoryThrottleStateStore()
        policy = ChannelThrottlePolicy(config=config, store=store)
        request = ThrottleCheckRequest(
            bucket_key=bucket_key or channel_name,
            cost=cost,
            now=now,
            dry_run=dry_run,
        )
        decision = policy.evaluate(request)

        payload: dict[str, Any] = {"ok": True, "decision": decision.to_dict()}
        _emit(payload, json_out=json_out)

    except ChannelThrottleError as exc:
        payload = {"ok": False, "error": exc.to_dict()}
        _emit(payload, json_out=json_out)
        raise typer.Exit(code=1) from None


def register(app: typer.Typer) -> None:
    """Register this operation on the provided Typer app."""
    app.command(name=COMMAND_NAME, help="Evaluate a channel throttling policy.")(throttling_policy)


register_command = register
add_commands = register
