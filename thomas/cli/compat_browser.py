"""Browser-related compatibility CLI commands."""

from __future__ import annotations

import json

import click

from thomas.cli.pack_bridge import register_pack_proxy_commands
from thomas.cli.parity_support import (
    emit_json_or_text as _emit_json_or_text,
)
from thomas.cli.parity_support import (
    forward_main_cli as _forward_main_cli,
)

try:
    import shutil
except (ImportError, ModuleNotFoundError):
    shutil = None  # type: ignore


@click.group()
@click.pass_context
def browser(ctx: click.Context) -> None:
    """Browser helpers and smoke checks."""
    _ = ctx


@browser.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_status(as_json: bool) -> None:
    """Show local browser tool availability."""
    chrome = shutil.which("chrome") or shutil.which("msedge") or shutil.which("chromium")
    playwright = shutil.which("playwright") or shutil.which("playwright-cli")
    payload = {
        "chrome_path": str(chrome or ""),
        "playwright_path": str(playwright or ""),
        "browser_ready": bool(chrome or playwright),
    }
    _emit_json_or_text(payload, as_json=as_json)


@browser.command("open")
@click.argument("url", required=False)
@click.option("--url", "url_opt", default="", help="URL to open (overrides positional URL).")
@click.option("--config", "config_path", default="", help="Optional browser config path.")
@click.option("--timeout", "timeout_s", default=None, type=float, help="Optional timeout in seconds.")
@click.option("--dry-run", is_flag=True, help="Validate request without opening a browser.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--json-schema", "as_schema", is_flag=True, help="Print JSON output schema and exit.")
def browser_open(
    url: str | None,
    url_opt: str,
    config_path: str,
    timeout_s: float | None,
    dry_run: bool,
    as_json: bool,
    as_schema: bool,
) -> None:
    """Open a URL via the Thomas browser integration surface (P026)."""
    from thomas.browser.p026_browser_integration_into_top_level_cli import (
        BrowserOpenRequest,
        open_url,
        result_json_schema,
    )

    if as_schema:
        click.echo(json.dumps(result_json_schema(), ensure_ascii=False, indent=2))
        return

    target = str(url_opt or "").strip() or (str(url or "").strip() if url else "")
    result = open_url(
        BrowserOpenRequest(
            url=(target or None),
            config_path=(str(config_path).strip() or None),
            timeout_s=timeout_s,
            dry_run=bool(dry_run),
        )
    )

    if as_json:
        click.echo(result.to_json())
    else:
        if result.ok:
            click.echo(f"{result.message}: {result.url}")
        elif result.error is not None:
            click.echo(f"{result.error.kind}: {result.error.message}", err=True)
        else:
            click.echo(f"error: {result.message}", err=True)

    if result.ok:
        return

    kind = str(getattr(result.error, "kind", "internal_error") or "internal_error")
    code_map = {
        "invalid_input": 2,
        "missing_config": 2,
        "external_failure": 1,
        "internal_error": 1,
    }
    raise SystemExit(int(code_map.get(kind, 1)))


@browser.command("smoke")
@click.option("--url", default="https://example.com", show_default=True)
@click.option("--expected-text", default="Example Domain", show_default=True)
@click.option("--timeout", "timeout_s", default=45.0, show_default=True, type=float)
@click.option("--max-actions", default=6, show_default=True, type=int)
@click.pass_context
def browser_smoke(
    ctx: click.Context,
    url: str,
    expected_text: str,
    timeout_s: float,
    max_actions: int,
) -> None:
    """Forward to live browser smoke workflow."""
    rc = _forward_main_cli(
        ctx,
        [
            "live-browser-smoke",
            "--url",
            str(url),
            "--expected-text",
            str(expected_text),
            "--timeout",
            str(float(timeout_s)),
            "--max-actions",
            str(int(max_actions)),
        ],
    )
    if rc != 0:
        raise SystemExit(rc)


register_pack_proxy_commands(
    browser,
    package="thomas.cli.commands.browser",
    family_hint="browser",
    strict_run_missing_entrypoint=True,
)
