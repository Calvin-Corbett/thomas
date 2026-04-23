"""CLI command: gateway logs filter.

This command calls the server route:
POST /gateway/logs/filter

Design notes:
- No third-party HTTP client dependency (uses urllib).
- --json prints the raw JSON response.
- Default output prints matched lines for human use.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

import typer


@dataclass(frozen=True)
class GatewayLogsFilterCliArgs:
    contains: str | None = None
    regex: str | None = None
    ignore_case: bool = False
    levels: list[str] | None = None
    after: str | None = None
    before: str | None = None
    limit: int = 200
    newest_first: bool = False


def _default_server_url() -> str:
    return os.getenv("THOMAS_SERVER_URL") or os.getenv("THOMAS_GATEWAY_URL") or "http://127.0.0.1:8080"


def _post_json(url: str, payload: dict[str, Any], *, timeout_s: float = 10.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
            return {
                "ok": False,
                "error": {"code": "BAD_RESPONSE", "message": "Server returned non-JSON response.", "fields": {}},
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"ok": False, "error": {"code": "HTTP_ERROR", "message": f"HTTP {e.code}", "fields": {}}}
    except Exception as e:
        return {"ok": False, "error": {"code": "CLIENT_ERROR", "message": str(e), "fields": {}}}


def call_gateway_logs_filter(
    *, server_url: str, args: GatewayLogsFilterCliArgs, timeout_s: float = 10.0
) -> dict[str, Any]:
    endpoint = server_url.rstrip("/") + "/gateway/logs/filter"
    payload: dict[str, Any] = {k: v for k, v in asdict(args).items() if v is not None}
    return _post_json(endpoint, payload, timeout_s=timeout_s)


app = typer.Typer(add_completion=False, help="Gateway log utilities.")


@app.command("logs-filter")
def logs_filter_command(
    contains: str | None = typer.Option(None, "--contains", help="Substring to match."),
    regex: str | None = typer.Option(None, "--regex", help="Regex to match."),
    ignore_case: bool = typer.Option(False, "--ignore-case", help="Case-insensitive matching."),
    level: list[str] | None = typer.Option(None, "--level", help="Filter by log level. May be repeated."),
    after: str | None = typer.Option(None, "--after", help="Only include entries on/after this ISO timestamp."),
    before: str | None = typer.Option(None, "--before", help="Only include entries on/before this ISO timestamp."),
    limit: int = typer.Option(200, "--limit", help="Maximum number of matches to return."),
    newest_first: bool = typer.Option(False, "--newest-first", help="Return newest matches first."),
    server_url: str = typer.Option(_default_server_url(), "--server-url", help="Thomas server base URL."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    args = GatewayLogsFilterCliArgs(
        contains=contains,
        regex=regex,
        ignore_case=ignore_case,
        levels=level,
        after=after,
        before=before,
        limit=limit,
        newest_first=newest_first,
    )
    data = call_gateway_logs_filter(server_url=server_url, args=args)

    if json_out:
        typer.echo(json.dumps(data, ensure_ascii=False))
        return

    if not bool(data.get("ok", False)):
        err = data.get("error") or {}
        code = err.get("code", "ERROR")
        msg = err.get("message", "Unknown error")
        typer.echo(f"{code}: {msg}")
        raise typer.Exit(code=1)

    matches = data.get("matches", [])
    for m in matches:
        if isinstance(m, dict) and "text" in m:
            typer.echo(m["text"])
        else:
            typer.echo(str(m))


# Compatibility exports for registries that prefer constants/hooks.
COMMAND_PATH = "/gateway/logs/filter"
COMMAND_METHOD = "POST"
COMMAND_NAME = "logs-filter"


def get_cli_app() -> typer.Typer:
    return app
