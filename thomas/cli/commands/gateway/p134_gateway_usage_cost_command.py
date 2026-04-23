"""Gateway usage-cost command (CLI).

Print aggregated gateway usage + cost for a date range.

Supports machine-readable JSON output via --json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any, Optional, Sequence


def _run(coro: Any) -> Any:
    """Run an async coroutine from sync CLI context deterministically."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("gateway usage-cost CLI cannot run inside an active event loop")


def _format_human(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if not isinstance(data, dict):
        return json.dumps(payload, indent=2, sort_keys=True)

    currency = data.get("currency", "USD")
    return "\n".join(
        [
            f"Gateway usage & cost: {data.get('start_date')} -> {data.get('end_date')}",
            f"Requests: {data.get('requests')}",
            (
                "Tokens: "
                f"in={data.get('input_tokens')} "
                f"out={data.get('output_tokens')} "
                f"total={data.get('total_tokens')}"
            ),
            f"Cost: {data.get('total_cost_usd')} {currency}",
        ]
    )


def _execute_usage_cost(
    *,
    start_date: str,
    end_date: Optional[str],
    project: Optional[str],
    model: Optional[str],
    gateway_url: Optional[str],
    gateway_api_key: Optional[str],
) -> dict[str, Any]:
    from thomas.server.routes.gateway.p134_gateway_usage_cost_command import (
        parse_usage_cost_query,
        run_gateway_usage_cost,
    )

    payload: dict[str, Any] = {"start_date": start_date}
    if end_date:
        payload["end_date"] = end_date
    if project:
        payload["project"] = project
    if model:
        payload["model"] = model

    resolved_url = gateway_url or os.environ.get("THOMAS_GATEWAY_URL") or os.environ.get("GATEWAY_URL")
    resolved_key = (
        gateway_api_key or os.environ.get("THOMAS_GATEWAY_API_KEY") or os.environ.get("GATEWAY_API_KEY")
    )

    query = parse_usage_cost_query(payload)
    report = _run(
        run_gateway_usage_cost(
            query=query,
            gateway_url=resolved_url,
            gateway_api_key=resolved_key,
        )
    )
    return {"ok": True, "data": report.to_dict()}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="thomas gateway usage-cost", add_help=True)
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="End date (YYYY-MM-DD). Defaults to start-date")
    parser.add_argument("--project", default=None, help="Optional project filter")
    parser.add_argument("--model", default=None, help="Optional model filter")
    parser.add_argument("--gateway-url", default=None, help="Gateway base URL (overrides env/config)")
    parser.add_argument(
        "--gateway-api-key",
        default=None,
        help="Gateway API key (overrides env/config)",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    return parser


def run(argv: Optional[Sequence[str]] = None, *, _out: Any = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    out_stream = _out if _out is not None else None

    from thomas.server.routes.gateway.p134_gateway_usage_cost_command import GatewayUsageCostError

    try:
        out_payload = _execute_usage_cost(
            start_date=str(args.start_date),
            end_date=args.end_date,
            project=args.project,
            model=args.model,
            gateway_url=args.gateway_url,
            gateway_api_key=args.gateway_api_key,
        )
    except GatewayUsageCostError as err:
        out_payload = err.to_dict()
        rendered = (
            json.dumps(out_payload, indent=2, sort_keys=True)
            if bool(args.json)
            else str(out_payload.get("error", {}).get("message", "gateway usage-cost failed"))
        )
        if out_stream is None:
            print(rendered)
        else:
            out_stream.write(rendered + "\n")
        return 2

    rendered = json.dumps(out_payload, indent=2, sort_keys=True) if bool(args.json) else _format_human(out_payload)
    if out_stream is None:
        print(rendered)
    else:
        out_stream.write(rendered + "\n")
    return 0


def _get_typer() -> Any:
    try:
        import typer  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Typer is required for register(app). Install optional dependency `typer` to use this API."
        ) from exc
    return typer


def register(app: Any) -> None:
    """Register the command on a Typer app."""
    typer = _get_typer()

    if getattr(app, "registered_callback", None) is None:
        @app.callback(invoke_without_command=True)
        def _root() -> None:
            return

    @app.command("usage-cost")
    def usage_cost(
        start_date: str = typer.Option(
            ..., "--start-date", help="Start date (YYYY-MM-DD)", show_default=False
        ),
        end_date: Optional[str] = typer.Option(
            None, "--end-date", help="End date (YYYY-MM-DD). Defaults to start-date"
        ),
        project: Optional[str] = typer.Option(None, "--project", help="Optional project filter"),
        model: Optional[str] = typer.Option(None, "--model", help="Optional model filter"),
        gateway_url: Optional[str] = typer.Option(
            None, "--gateway-url", help="Gateway base URL (overrides env/config)"
        ),
        gateway_api_key: Optional[str] = typer.Option(
            None, "--gateway-api-key", help="Gateway API key (overrides env/config)"
        ),
        json_output: bool = typer.Option(
            False, "--json", help="Emit machine-readable JSON to stdout"
        ),
    ) -> None:
        """Print usage + cost from Gateway."""
        from thomas.server.routes.gateway.p134_gateway_usage_cost_command import GatewayUsageCostError

        try:
            out_payload = _execute_usage_cost(
                start_date=start_date,
                end_date=end_date,
                project=project,
                model=model,
                gateway_url=gateway_url,
                gateway_api_key=gateway_api_key,
            )
        except GatewayUsageCostError as err:
            out_payload = err.to_dict()
            if json_output:
                typer.echo(json.dumps(out_payload, indent=2, sort_keys=True))
            else:
                typer.secho(out_payload["error"]["message"], fg=typer.colors.RED)
            raise typer.Exit(code=2)

        if json_output:
            typer.echo(json.dumps(out_payload, indent=2, sort_keys=True))
        else:
            typer.echo(_format_human(out_payload))


# Optional metadata for any discovery framework (no import-time side effects).
COMMAND_GROUP = "gateway"
COMMAND_NAME = "usage-cost"
SERVER_ROUTE = "/gateway/usage-cost"


def get_command_spec() -> dict[str, Any]:
    return {
        "group": COMMAND_GROUP,
        "name": COMMAND_NAME,
        "route": SERVER_ROUTE,
        "register": register,
    }


COMMAND_SPEC = get_command_spec()


def add_commands(app: Any) -> None:
    register(app)


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
