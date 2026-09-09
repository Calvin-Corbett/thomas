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


@browser.group("workflows")
def browser_workflows() -> None:
    """Inspect production browser workflow profiles."""


@browser_workflows.command("list")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_workflows_list(limit: int, as_json: bool) -> None:
    from thomas.browser.workflow_runtime import list_profiles

    rows = list_profiles()
    rows = rows[: max(1, int(limit))]
    payload = {"count": len(rows), "profiles": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Workflow profiles: {len(rows)}")
    for row in rows:
        click.echo(
            f"- {row.get('profile_id')} | category={row.get('category')} | "
            f"risk={row.get('risk_tier')} | timeout_ms={row.get('timeout_ms')}"
        )


@browser_workflows.command("show")
@click.argument("profile_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_workflows_show(profile_id: str, as_json: bool) -> None:
    from thomas.browser.workflow_runtime import load_profile

    row = load_profile(str(profile_id))
    if row is None:
        raise click.ClickException(f"workflow profile not found: {profile_id}")
    if as_json:
        click.echo(json.dumps(row, ensure_ascii=False, indent=2))
        return
    click.echo(f"profile_id: {row.get('profile_id')}")
    click.echo(f"title: {row.get('title')}")
    click.echo(f"category: {row.get('category')}")
    click.echo(f"risk_tier: {row.get('risk_tier')}")
    click.echo(f"required_signals: {', '.join(str(x) for x in (row.get('required_signals') or []))}")


@browser.group("workflow-cases")
def browser_workflow_cases() -> None:
    """Inspect and validate production browser workflow corpus cases."""


@browser_workflow_cases.command("list")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_workflow_cases_list(limit: int, as_json: bool) -> None:
    from thomas.browser.workflow_runtime import list_case_files

    rows = [p.name for p in list_case_files(limit=max(1, int(limit)))]
    payload = {"count": len(rows), "cases": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Workflow cases: {len(rows)}")
    for row in rows:
        click.echo(f"- {row}")


@browser_workflow_cases.command("show")
@click.argument("case_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_workflow_cases_show(case_id: str, as_json: bool) -> None:
    from thomas.browser.workflow_runtime import load_case

    payload = load_case(str(case_id))
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"workflow_id: {payload.get('workflow_id')}")
    click.echo(f"title: {payload.get('title')}")
    click.echo(f"category: {payload.get('category')}")
    click.echo(f"steps: {len(payload.get('steps') or [])}")
    click.echo(f"assertions: {len(payload.get('assertions') or [])}")


@browser_workflow_cases.command("validate")
@click.argument("case_id", required=False, default="")
@click.option(
    "--limit",
    default=0,
    type=int,
    show_default=True,
    help="When no case_id is given, validate first N cases (0 = all).",
)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_workflow_cases_validate(case_id: str, limit: int, as_json: bool) -> None:
    from thomas.browser.workflow_runtime import load_case, validate_case_payload, validate_corpus

    target = str(case_id or "").strip()
    if target:
        payload = load_case(target)
        ok, errors = validate_case_payload(payload)
        out = {
            "target": target,
            "ok": bool(ok),
            "errors": errors,
            "workflow_id": payload.get("workflow_id"),
        }
        if as_json:
            click.echo(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            click.echo(f"target: {target}")
            click.echo(f"ok: {bool(ok)}")
            if errors:
                for row in errors[:20]:
                    click.echo(f"- {row}")
        if not ok:
            raise SystemExit(1)
        return

    summary = validate_corpus(limit=(None if int(limit) <= 0 else int(limit)))
    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        click.echo(f"corpus_root: {summary.get('root')}")
        click.echo(f"total: {summary.get('total')}")
        click.echo(f"valid: {summary.get('valid')}")
        click.echo(f"invalid: {summary.get('invalid')}")
    if int(summary.get("invalid") or 0) > 0:
        raise SystemExit(1)


register_pack_proxy_commands(
    browser,
    package="thomas.cli.commands.browser",
    family_hint="browser",
    strict_run_missing_entrypoint=True,
)
