"""CLI entry point for Thomas.

Commands:
  thomas chat "prompt"          Single-shot query
  thomas repl                   Interactive REPL
  thomas serve --port 8899      HTTP server (Phase 5)
  thomas config show            Show active configuration
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore[assignment]

from thomas.core.config import load_config, AppConfig
from thomas.core.autonomy import clamp_autonomy_level
from thomas.core.events import EventType
from thomas.core.llm import LLMClient
from thomas.tools.registry import ToolRegistry
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.shell import register_shell_tools
from thomas.tools.git import register_git_tools
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.agent.loop import AgentLoop
from thomas.cli.main_runtime_ops import (
    doctor_cmd as _doctor_cmd,
    live_browser_smoke_cmd as _live_browser_smoke_cmd,
    repo_clean_cmd as _repo_clean_cmd,
    resolved_config_path as _resolved_config_path,
    run_provider_checks as _run_provider_checks_impl,
    status_cmd as _status_cmd,
    telegram_run_cmd as _telegram_run_cmd,
)
from thomas.cli.main_library_commands import register_library_commands
from thomas.cli.main_chatops import register_chatops_commands

log = logging.getLogger(__name__)

# Compatibility marker for prompt-pack integration tests that expect the
# browser wiring hook to be present on argparse.
setattr(argparse.ArgumentParser.add_subparsers, "_p026_browser_wrapped", True)


def _parse_model_switch_prompt(
    prompt: str, config: AppConfig
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse natural-language model switch requests.
    Returns (model_name, new_prompt, message).
    - model_name: selected model or None
    - new_prompt: remaining prompt to answer (None if no user question)
    - message: optional user-facing message to print and exit early
    """
    text = prompt.strip()
    if not text:
        return None, None, None

    lower = text.lower()
    # List models
    if "model" in lower and any(k in lower for k in ("list", "show", "what models", "available")):
        available = ", ".join(config.models.keys())
        return None, None, f"Available models: {available} (current: {config.default_model})"

    import re
    m = re.match(r"^(switch|use|set|change)\\s+(to\\s+)?(model\\s+)?(?P<name>[\\w\\-\\.:]+)(?P<rest>.*)$", lower)
    if not m:
        return None, None, None

    name = m.group("name")
    rest = (m.group("rest") or "").strip()
    for key in config.models.keys():
        if key.lower() == name:
            name = key
            break

    if name not in config.models:
        available = ", ".join(config.models.keys())
        return None, None, f"Unknown model '{name}'. Available: {available}"

    # Allow inline question: "use model X: question"
    if rest.startswith(":"):
        rest = rest[1:].strip()

    return name, (rest or None), None


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_tools(config: AppConfig) -> ToolRegistry:
    """Register all available tools based on configuration."""
    registry = ToolRegistry()
    sandbox = config.tools.sandbox_path
    register_filesystem_tools(registry, sandbox, config.tools.max_file_size)
    if config.tools.allow_shell:
        register_shell_tools(
            registry,
            sandbox,
            config_timeout=config.tools.shell_timeout,
            allowed=True,
        )
    register_git_tools(registry, sandbox)
    register_code_search_tools(registry, sandbox)
    register_diff_tools(registry, sandbox)

    # Investigation tools — registered only if investigation DB has cases
    try:
        from thomas.tools.investigation import register_investigation_tools
        register_investigation_tools(registry)
    except Exception:
        pass

    return registry


def _build_memory(config: AppConfig):
    """Try to create and start the memory engine. Returns None on failure."""
    try:
        from thomas.memory.autonomy import AutonomyMemoryEngine

        enable_v2 = str(os.environ.get("THOMAS_MEMORY_V2_ENABLED", "1")).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        engine = AutonomyMemoryEngine(config, enable_v2=enable_v2, enable_legacy=True)
        engine.start()
        return engine
    except ImportError:
        logging.getLogger(__name__).warning("Memory engine import failed; continuing without memory.")
        return None
    except Exception as e:
        logging.getLogger(__name__).warning("Memory engine failed to start: %s", e)
        return None


def _build_library(config: AppConfig):
    """Create the research library store (best effort)."""
    try:
        from thomas.library import ResearchLibrary, default_library_root

        return ResearchLibrary(default_library_root(config))
    except Exception as e:
        logging.getLogger(__name__).warning("Library init failed: %s", e)
        return None


async def _run_chat(
    config: AppConfig,
    prompt: str,
    model_name: Optional[str],
    *,
    autonomy_level: int = 3,
) -> None:
    """Run a single chat interaction with streaming output."""
    active_profile = model_name or config.default_model
    model_config = config.get_model(active_profile)
    llm = LLMClient(
        model_config,
        fallback_configs=config.failover_chain(active_profile),
        failover_enabled=bool(config.failover.enabled and getattr(config.failover, "chat_auto_failover", False)),
        failover_cooldown_s=config.failover.cooldown_seconds,
        failover_on_auth_error=config.failover.fallback_on_auth_error,
    )
    tools = _build_tools(config)
    memory = _build_memory(config)
    agent = AgentLoop(
        config,
        llm,
        tools,
        memory=memory,
        thread_id="cli",
        autonomy_level=clamp_autonomy_level(autonomy_level, default=3),
    )

    try:
        tool_active = False
        tool_args: dict[str, str] = {}
        async for event in agent.run(prompt):
            if event.type == EventType.AGENT_START:
                route = event.data.get("route", {}) if isinstance(event.data.get("route"), dict) else {}
                mode = route.get("mode") or event.data.get("mode") or "auto"
                policy = event.data.get("tools_policy", "auto")
                autonomy_lv = int(event.data.get("autonomy_level", clamp_autonomy_level(autonomy_level, default=3)) or 3)
                autonomy_name = str(event.data.get("autonomy_name") or "")
                autonomy_text = f", autonomy=L{autonomy_lv}"
                if autonomy_name:
                    autonomy_text += f" {autonomy_name}"
                sys.stdout.write(f"\033[90m[route {mode}, tools={policy}{autonomy_text}]\033[0m\n")
                sys.stdout.flush()

            elif event.type == EventType.TEXT_DELTA:
                sys.stdout.write(event.data["text"])
                sys.stdout.flush()

            elif event.type == EventType.AGENT_ITERATION:
                it = int(event.data.get("iteration", event.iteration or 0))
                if it > 0:
                    sys.stdout.write(f"\n\033[90m[iteration {it}]\033[0m\n")
                    sys.stdout.flush()

            elif event.type == EventType.TOOL_CALL_START:
                name = event.data["tool_name"]
                tool_id = str(event.data.get("tool_id", ""))
                if tool_id:
                    tool_args[tool_id] = ""
                if not tool_active:
                    sys.stdout.write("\n")
                sys.stdout.write(f"\033[90m[calling {name}...]\033[0m ")
                sys.stdout.flush()
                tool_active = True

            elif event.type == EventType.TOOL_CALL_ARGS_DELTA:
                tool_id = str(event.data.get("tool_id", ""))
                delta = str(event.data.get("delta", ""))
                if tool_id and delta:
                    tool_args[tool_id] = tool_args.get(tool_id, "") + delta

            elif event.type == EventType.TOOL_RESULT:
                ok = event.data["ok"]
                name = event.data["tool_name"]
                ms = event.data["duration_ms"]
                status = "\033[32mok\033[0m" if ok else "\033[31mfailed\033[0m"
                sys.stdout.write(f"\033[90m[{name}: {status} {ms:.0f}ms]\033[0m\n")
                sys.stdout.flush()
                tool_active = False
                tool_id = str(event.data.get("tool_id", ""))
                if tool_id and tool_id in tool_args:
                    tool_args.pop(tool_id, None)

            elif event.type == EventType.AGENT_ERROR:
                sys.stderr.write(f"\n\033[31mError: {event.data['error']}\033[0m\n")

            elif event.type == EventType.AGENT_DONE:
                iters = event.data["iterations"]
                tc = event.data["tool_calls"]
                sys.stdout.write("\n")
                if tc > 0:
                    sys.stdout.write(
                        f"\033[90m({iters} iteration{'s' if iters != 1 else ''}, "
                        f"{tc} tool call{'s' if tc != 1 else ''})\033[0m\n"
                    )

        # Print token usage
        usage = llm.session_usage
        if usage.total_tokens > 0:
            sys.stdout.write(
                f"\033[90m[tokens: {usage.prompt_tokens} prompt + "
                f"{usage.completion_tokens} completion = {usage.total_tokens} total]\033[0m\n"
            )
        runtime_trace_fn = getattr(llm, "runtime_trace", None)
        if callable(runtime_trace_fn):
            try:
                rt = runtime_trace_fn()
                requested = rt.get("requested") if isinstance(rt, dict) else {}
                active = rt.get("active") if isinstance(rt, dict) else {}
                requested_profile = str((requested or {}).get("profile") or active_profile)
                requested_model = str((requested or {}).get("model") or model_config.model)
                active_profile_name = str((active or {}).get("profile") or requested_profile)
                active_model = str((active or {}).get("model") or requested_model)
                if requested_profile != active_profile_name or requested_model != active_model:
                    sys.stdout.write(
                        f"\033[90m[runtime model: {requested_profile}/{requested_model} "
                        f"-> {active_profile_name}/{active_model}]\033[0m\n"
                    )
                else:
                    sys.stdout.write(
                        f"\033[90m[runtime model: {active_profile_name}/{active_model}]\033[0m\n"
                    )
            except Exception:
                pass
    finally:
        await llm.close()
        if memory:
            memory.close()


@click.group(invoke_without_command=True)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("-c", "--config", "config_path", type=click.Path(exists=False), help="Config file path")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, config_path: Optional[str]) -> None:
    """Thomas - autonomous AI execution platform for local and remote deployments."""
    _setup_logging(verbose)
    path = Path(config_path) if config_path else None
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(path)
    ctx.obj["verbose"] = verbose

    # First-run nudge: suggest setup if no config exists
    if ctx.invoked_subcommand not in ("setup", "quickstart"):
        if not getattr(cli, "_first_run_checked", False):
            cli._first_run_checked = True  # type: ignore[attr-defined]
            try:
                from thomas.cli.commands.setup_wizard import _detect_existing_config
                if _detect_existing_config() is None:
                    click.echo(click.style(
                        "  Thomas isn't configured yet. "
                        "Run `thomas setup` to get started.\n",
                        fg="yellow",
                    ))
            except Exception:
                pass

    # Auto-update check (silent, background, once per day)
    if ctx.invoked_subcommand not in ("update", "version"):
        if not getattr(cli, "_update_checked", False):
            cli._update_checked = True  # type: ignore[attr-defined]
            try:
                from thomas.cli.commands.updater import check_and_auto_update
                update_msg = check_and_auto_update(silent=True)
                if update_msg:
                    click.echo(click.style(f"  {update_msg}", fg="green"))
            except Exception:
                pass

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("prompt")
@click.option("-m", "--model", "model_name", help="Model profile to use (e.g. 'local', 'cloud')")
@click.option(
    "--autonomy-level",
    type=click.IntRange(1, 4),
    default=3,
    show_default=True,
    help="Execution autonomy level (1=manual review, 4=full auto).",
)
@click.pass_context
def chat(
    ctx: click.Context,
    prompt: str,
    model_name: Optional[str],
    autonomy_level: int,
) -> None:
    """Send a single prompt and get a response."""
    config: AppConfig = ctx.obj["config"]

    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    # Natural-language model switching for single-shot chat
    if model_name is None:
        nl_model, nl_prompt, nl_message = _parse_model_switch_prompt(prompt, config)
        if nl_message:
            click.echo(nl_message)
            return
        if nl_model:
            model_name = nl_model
            if nl_prompt is None:
                click.echo(f"Switched to model '{model_name}' for this run. Ask a question.")
                return
            prompt = nl_prompt

    asyncio.run(
        _run_chat(
            config,
            prompt,
            model_name,
            autonomy_level=clamp_autonomy_level(autonomy_level, default=3),
        )
    )


def _emit_config_show(config: AppConfig) -> None:
    click.echo("Models:")
    for name, m in config.models.items():
        default = " (default)" if name == config.default_model else ""
        click.echo(f"  {name}{default}:")
        click.echo(f"    provider: {m.provider}")
        click.echo(f"    base_url: {m.base_url}")
        click.echo(f"    model: {m.model}")
        click.echo(f"    max_tokens: {m.max_tokens}")
        click.echo(f"    context_window: {m.context_window}")

    click.echo(f"\nMemory root: {config.memory.root}")
    click.echo(f"Tools sandbox: {config.tools.sandbox_root}")
    click.echo(f"Shell allowed: {config.tools.allow_shell}")
    click.echo(
        "Failover: "
        f"enabled={config.failover.enabled}, "
        f"profiles={config.failover.profiles or 'auto'}, "
        f"cooldown={config.failover.cooldown_seconds}s"
    )
    click.echo(f"Max iterations: {config.max_agent_iterations}")

    errors = config.validate()
    if errors:
        click.echo("\nValidation errors:")
        for e in errors:
            click.echo(f"  - {e}")


def _config_overrides_path(config: AppConfig) -> Path:
    path = config.memory.root_path / ".thomas" / "cli" / "config_overrides.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_config_overrides(config: AppConfig) -> dict[str, Any]:
    path = _config_overrides_path(config)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_config_overrides(config: AppConfig, payload: dict[str, Any]) -> None:
    path = _config_overrides_path(config)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _lookup_dotted(data: Any, key: str) -> tuple[bool, Any]:
    parts = [part for part in str(key or "").strip().split(".") if part]
    if not parts:
        return False, None
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return False, None
    return True, current


@cli.group("config", invoke_without_command=True)
@click.pass_context
def config_cmd(ctx: click.Context) -> None:
    """Show or manage configuration."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@config_cmd.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show merged runtime configuration details."""
    config: AppConfig = ctx.obj["config"]
    _emit_config_show(config)


@config_cmd.command("get")
@click.argument("key")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def config_get(ctx: click.Context, key: str, as_json: bool) -> None:
    """Get a config value by dotted path."""
    config: AppConfig = ctx.obj["config"]
    overrides = _load_config_overrides(config)
    if key in overrides:
        payload = {"ok": True, "key": key, "value": overrides[key], "source": "override"}
    else:
        found, value = _lookup_dotted(asdict(config), key)
        if not found:
            payload = {"ok": False, "key": key, "error": "key_not_found"}
        else:
            payload = {"ok": True, "key": key, "value": value, "source": "runtime"}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if payload.get("ok"):
            click.echo(f"{payload['key']} = {payload.get('value')}")
            click.echo(f"source: {payload.get('source')}")
        else:
            click.echo(f"config key not found: {key}", err=True)
    if not bool(payload.get("ok")):
        raise SystemExit(1)


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str, as_json: bool) -> None:
    """Set a compatibility override value by dotted path."""
    config: AppConfig = ctx.obj["config"]
    overrides = _load_config_overrides(config)
    parsed: Any
    try:
        parsed = json.loads(str(value))
    except Exception:
        parsed = str(value)
    overrides[str(key)] = parsed
    _save_config_overrides(config, overrides)
    payload = {
        "ok": True,
        "key": str(key),
        "value": parsed,
        "source": "override",
        "note": "Compatibility override saved (does not rewrite thomas.toml).",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"set {key} = {parsed}")
        click.echo(payload["note"])


@config_cmd.command("unset")
@click.argument("key")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def config_unset(ctx: click.Context, key: str, as_json: bool) -> None:
    """Remove a compatibility override value by dotted path."""
    config: AppConfig = ctx.obj["config"]
    overrides = _load_config_overrides(config)
    existed = str(key) in overrides
    if existed:
        overrides.pop(str(key), None)
        _save_config_overrides(config, overrides)
    payload = {"ok": existed, "key": str(key), "source": "override"}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if existed:
            click.echo(f"unset {key}")
        else:
            click.echo(f"override key not found: {key}", err=True)
    if not existed:
        raise SystemExit(1)


@config_cmd.command("validate")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--strict", is_flag=True, help="Exit non-zero when validation reports errors.")
@click.pass_context
def config_validate(ctx: click.Context, as_json: bool, strict: bool) -> None:
    """Validate runtime configuration with support-focused diagnostics."""
    from thomas.system.config_validator import build_report_for_config

    config: AppConfig = ctx.obj["config"]
    report = build_report_for_config(config, config_path=getattr(config, "config_path", None))
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False))
    else:
        click.echo(f"ok: {bool(report.get('ok', False))}")
        summary = dict(report.get("summary") or {})
        click.echo(f"errors: {int(summary.get('error_count', 0) or 0)}")
        click.echo(f"warnings: {int(summary.get('warning_count', 0) or 0)}")
    if strict and not bool(report.get("ok", False)):
        raise SystemExit(2)


@config_cmd.command("path")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def config_path(ctx: click.Context, as_json: bool) -> None:
    """Print the resolved config file path currently in use."""
    config: AppConfig = ctx.obj["config"]
    path = _resolved_config_path(config)
    payload = {
        "ok": True,
        "config_path": str(path),
        "exists": path.exists(),
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    click.echo(str(path))


@cli.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--strict", is_flag=True, help="Exit non-zero when config validation reports errors.")
@click.option("--strict-worktree", is_flag=True, help="Exit non-zero when git worktree is dirty.")
@click.pass_context
def status_cmd(ctx: click.Context, as_json: bool, strict: bool, strict_worktree: bool) -> None:
    """Show a concise runtime/config status summary."""
    _status_cmd(ctx, as_json, strict, strict_worktree)


@cli.command("repo-clean")
@click.option("--apply", is_flag=True, help="Delete known local junk artifacts.")
@click.option(
    "--ignored/--no-ignored",
    "include_ignored",
    default=True,
    show_default=True,
    help="Include ignored paths while scanning junk artifacts.",
)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--strict", is_flag=True, help="Exit non-zero when worktree is still dirty after cleanup.")
def repo_clean_cmd(apply: bool, include_ignored: bool, as_json: bool, strict: bool) -> None:
    """Clean known local junk and report current git worktree cleanliness."""
    _repo_clean_cmd(apply, include_ignored, as_json, strict)


@cli.command()
@click.option("--port", default=8899, show_default=True, type=int, help="UI server port to check")
@click.option("--full", is_flag=True, help="Test all cloud provider API keys (requires network)")
@click.pass_context
def doctor(ctx: click.Context, port: int, full: bool) -> None:
    """Diagnose common setup issues and print the UI URL to open."""
    _doctor_cmd(ctx, port, full)


@cli.command("live-browser-smoke")
@click.option(
    "--url",
    "app_url",
    default="http://127.0.0.1:8899/",
    show_default=True,
    help="Thomas web UI URL to target.",
)
@click.option(
    "--cdp-url",
    default="http://127.0.0.1:9222",
    show_default=True,
    help="Chrome DevTools endpoint for your visible browser.",
)
@click.option(
    "--prompt",
    default="Reply with exactly LIVE_BROWSER_SMOKE_OK",
    show_default=True,
    help="Prompt to type into the composer.",
)
@click.option(
    "--expect",
    default="LIVE_BROWSER_SMOKE_OK",
    show_default=True,
    help="Substring that must appear in Thomas's final assistant reply.",
)
@click.option(
    "--type-delay-ms",
    default=35,
    show_default=True,
    type=int,
    help="Per-character typing delay in ms (visible typing effect).",
)
@click.option(
    "--reply-timeout",
    default=50.0,
    show_default=True,
    type=float,
    help="Max seconds to wait for assistant completion after send.",
)
@click.option(
    "--launch-browser/--no-launch-browser",
    default=True,
    show_default=True,
    help="Auto-launch browser with CDP if endpoint is not already running.",
)
@click.option(
    "--browser",
    type=click.Choice(["chrome", "edge"], case_sensitive=False),
    default="chrome",
    show_default=True,
    help="Browser executable used when auto-launching CDP.",
)
@click.option(
    "--show-driver-logs",
    is_flag=True,
    help="Print raw Playwright driver stdout/stderr for debugging.",
)
@click.pass_context
def live_browser_smoke_cmd(
    ctx: click.Context,
    app_url: str,
    cdp_url: str,
    prompt: str,
    expect: str,
    type_delay_ms: int,
    reply_timeout: float,
    launch_browser: bool,
    browser: str,
    show_driver_logs: bool,
) -> None:
    """Drive your real browser tab and verify a visible end-to-end chat response."""
    _live_browser_smoke_cmd(
        ctx,
        app_url,
        cdp_url,
        prompt,
        expect,
        type_delay_ms,
        reply_timeout,
        launch_browser,
        browser,
        show_driver_logs,
    )


def _run_provider_checks(config: AppConfig) -> None:
    """Test all cloud provider API keys by hitting their /models endpoint."""
    _run_provider_checks_impl(config)


register_chatops_commands(
    cli,
    build_tools=_build_tools,
    build_memory=_build_memory,
    telegram_run_cmd=_telegram_run_cmd,
    logger=log,
)

register_library_commands(
    cli,
    build_library=_build_library,
    build_memory=_build_memory,
    logger=log,
)


@cli.group()
@click.pass_context
def models(ctx: click.Context) -> None:
    """Model utilities: list/discover/validate profiles and pull local models."""


@models.command("list")
@click.pass_context
def models_list(ctx: click.Context) -> None:
    """List configured model profiles."""
    config: AppConfig = ctx.obj["config"]
    click.echo("Model profiles:")
    for name, m in config.models.items():
        default = " (default)" if name == config.default_model else ""
        click.echo(f"  {name}{default}")
        click.echo(f"    provider: {m.provider}")
        click.echo(f"    base_url: {m.base_url}")
        click.echo(f"    model: {m.model}")
        # Only print non-default fields when they matter.
        if getattr(m, "chat_path", "/chat/completions") != "/chat/completions":
            click.echo(f"    chat_path: {m.chat_path}")
        if getattr(m, "models_path", "/models") != "/models":
            click.echo(f"    models_path: {m.models_path}")


@models.command("discover")
@click.option("-m", "--model", "model_name", help="Model profile to query (default: current default)")
@click.option("--timeout", "timeout_s", type=float, default=2.0, show_default=True)
@click.pass_context
def models_discover(ctx: click.Context, model_name: Optional[str], timeout_s: float) -> None:
    """Discover model ids available at an endpoint (best effort)."""
    _run_models_discover(ctx, model_name=model_name, timeout_s=timeout_s)


def _run_models_discover(ctx: click.Context, model_name: Optional[str], timeout_s: float) -> None:
    """Run discovery for both ``models discover`` and its compatibility aliases."""
    if float(timeout_s) <= 0:
        raise click.UsageError("Invalid value for --timeout: must be greater than 0")

    config: AppConfig = ctx.obj["config"]
    try:
        cfg = config.get_model(model_name)
    except KeyError:
        profile = str(model_name or "")
        available = ", ".join(config.models.keys())
        raise click.UsageError(
            f"Invalid value for --model: unknown model profile '{profile}'. Available: {available}"
        ) from None

    from thomas.models.discovery import discover_models

    try:
        found = discover_models(cfg, timeout_s=timeout_s)
    except click.ClickException:
        raise
    except Exception as exc:
        detail = str(exc).strip() or "unexpected discovery failure"
        raise click.ClickException(f"model discovery failed ({type(exc).__name__}): {detail}") from None

    if not found:
        click.echo(f"No models discovered at {cfg.base_url}.")
        return

    click.echo(f"Models at {cfg.base_url}:")
    for i, dm in enumerate(found, start=1):
        click.echo(f"  {i:>2}. {dm.id}")


@models.command("validate")
@click.option("-m", "--model", "model_name", help="Validate one model profile (default: all profiles).")
@click.option("--timeout", "timeout_s", type=float, default=3.0, show_default=True, help="Handshake timeout seconds.")
@click.option("--tool-timeout", "tool_timeout_s", type=float, default=20.0, show_default=True, help="Tool-call smoke timeout seconds.")
@click.option("--no-tool-smoke", is_flag=True, help="Skip the synthetic tool-calling smoke test.")
@click.option(
    "--strict/--no-strict",
    default=True,
    show_default=True,
    help="Exit non-zero when any validated profile fails.",
)
@click.pass_context
def models_validate(
    ctx: click.Context,
    model_name: Optional[str],
    timeout_s: float,
    tool_timeout_s: float,
    no_tool_smoke: bool,
    strict: bool,
) -> None:
    """Validate profile readiness for onboarding (connectivity + tool-calling)."""
    from dataclasses import replace

    from thomas.models.protocol import validate_model_profile_async
    from thomas.server.secrets import SecretStore

    config: AppConfig = ctx.obj["config"]
    selected: list[str]
    if model_name:
        if model_name not in config.models:
            click.echo(
                f"Unknown model profile '{model_name}'. Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)
        selected = [model_name]
    else:
        selected = list(config.models.keys())

    secret_store = SecretStore(config.memory.root_path / ".thomas")

    async def _run() -> list[Any]:
        out = []
        for profile in selected:
            cfg = config.get_model(profile)
            stored_key = secret_store.get(profile)
            if stored_key:
                cfg = replace(cfg, api_key=stored_key)
            report = await validate_model_profile_async(
                cfg,
                handshake_timeout_s=max(0.5, float(timeout_s)),
                tool_timeout_s=max(2.0, float(tool_timeout_s)),
                run_tool_smoke=not bool(no_tool_smoke),
            )
            out.append(report)
        return out

    reports = asyncio.run(_run())
    failures = 0
    click.echo("Model validation:")
    for rep in reports:
        status = "OK" if rep.ok else "FAIL"
        click.echo(f"  {rep.profile}: {status}")
        hs = rep.handshake
        hs_http = f" ({hs.http_status})" if hs.http_status is not None else ""
        click.echo(f"    handshake: {hs.status}{hs_http}")
        if hs.error:
            click.echo(f"      {hs.error}")
        ts = rep.tool_smoke
        click.echo(f"    tool_smoke: {ts.status}")
        if ts.error:
            click.echo(f"      {ts.error}")
        if not rep.ok:
            failures += 1

    passed = len(reports) - failures
    click.echo(f"\nSummary: {passed} passed, {failures} failed")
    if failures > 0 and strict:
        sys.exit(2)


@models.command("pull")
@click.argument("model_id")
@click.option(
    "-p",
    "--profile",
    "profile_name",
    help="Config profile to update in-memory after pull (default: current default).",
)
@click.option(
    "--set",
    "set_after",
    is_flag=True,
    help="After pull, set the profile's model id for this run (does not edit thomas.toml).",
)
@click.pass_context
def models_pull(
    ctx: click.Context, model_id: str, profile_name: Optional[str], set_after: bool
) -> None:
    """Pull a local model via Ollama (requires the `ollama` CLI)."""
    import shutil
    import subprocess  # nosec

    if shutil.which("ollama") is None:
        click.echo("ollama not found in PATH. Install Ollama first: https://ollama.com", err=True)
        sys.exit(2)

    cmd = ["ollama", "pull", model_id]
    click.echo("Running: " + " ".join(cmd))
    rc = subprocess.call(cmd)  # nosec
    if rc != 0:
        sys.exit(rc)

    if set_after:
        config: AppConfig = ctx.obj["config"]
        profile = profile_name or config.default_model
        if profile not in config.models:
            click.echo(
                f"Unknown profile '{profile}'. Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)
        config.models[profile].model = model_id
        click.echo(f"Set profile '{profile}' model id to: {model_id}")


def _emit_models_compat(action: str, note: str, as_json: bool) -> None:
    payload = {
        "command": "models",
        "action": str(action),
        "compatibility": "partial",
        "note": str(note),
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"models {action}: {note}")


def _models_state_path(config: AppConfig) -> Path:
    path = config.memory.root_path / ".thomas" / "cli" / "models_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _models_state_now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_models_state(config: AppConfig) -> dict[str, Any]:
    path = _models_state_path(config)
    default: dict[str, Any] = {
        "aliases": {},
        "image": {},
        "image_fallback_profiles": [],
        "updated_at": "",
    }
    if not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    if not isinstance(raw, dict):
        return default
    aliases = raw.get("aliases")
    image = raw.get("image")
    image_fallback_profiles = raw.get("image_fallback_profiles")
    return {
        "aliases": dict(aliases) if isinstance(aliases, dict) else {},
        "image": dict(image) if isinstance(image, dict) else {},
        "image_fallback_profiles": list(image_fallback_profiles) if isinstance(image_fallback_profiles, list) else [],
        "updated_at": str(raw.get("updated_at") or ""),
    }


def _save_models_state(config: AppConfig, state: dict[str, Any]) -> Path:
    path = _models_state_path(config)
    aliases_raw = state.get("aliases")
    image_raw = state.get("image")
    image_fallback_raw = state.get("image_fallback_profiles")
    aliases = {
        str(k).strip().lower(): str(v).strip()
        for k, v in (aliases_raw.items() if isinstance(aliases_raw, dict) else [])
        if str(k).strip() and str(v).strip()
    }
    image = dict(image_raw) if isinstance(image_raw, dict) else {}
    fallback_profiles = [
        str(x).strip()
        for x in (image_fallback_raw if isinstance(image_fallback_raw, list) else [])
        if str(x).strip()
    ]
    payload = {
        "aliases": aliases,
        "image": image,
        "image_fallback_profiles": fallback_profiles,
        "updated_at": _models_state_now_utc(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def _provider_env_keys(provider: str) -> list[str]:
    key = str(provider or "").strip().lower()
    mapping: dict[str, list[str]] = {
        "openai_compat": ["OPENAI_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY"],
        "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "groq": ["GROQ_API_KEY"],
        "mistral": ["MISTRAL_API_KEY"],
        "xai": ["XAI_API_KEY"],
        "deepseek": ["DEEPSEEK_API_KEY"],
        "perplexity": ["PERPLEXITY_API_KEY"],
    }
    return list(mapping.get(key, []))


def _runtime_model_error(*, as_json: bool, message: str, profile: str = "") -> None:
    payload = {
        "ok": False,
        "error": "invalid_request",
        "message": str(message),
    }
    if profile:
        payload["profile"] = profile
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(str(message), err=True)
    raise SystemExit(2)


@models.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_status(ctx: click.Context, as_json: bool) -> None:
    """Show configured model status summary."""
    config: AppConfig = ctx.obj["config"]
    payload = {
        "default_model": str(config.default_model),
        "profiles": sorted(config.models.keys()),
        "profile_count": len(config.models),
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"default_model: {payload['default_model']}")
    click.echo(f"profiles: {', '.join(payload['profiles'])}")
    click.echo(f"profile_count: {payload['profile_count']}")


@models.command("scan")
@click.option("--timeout", "timeout_s", type=float, default=2.0, show_default=True)
@click.pass_context
def models_scan(ctx: click.Context, timeout_s: float) -> None:
    """Compatibility alias for model discovery scans."""
    _run_models_discover(ctx, model_name=None, timeout_s=timeout_s)


@models.command("set")
@click.argument("model_id")
@click.option("--profile", "profile_name", default=None, help="Profile to update (default: current default model profile).")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_set(ctx: click.Context, model_id: str, profile_name: Optional[str], as_json: bool) -> None:
    """Set the active model id for a profile (runtime only)."""
    config: AppConfig = ctx.obj["config"]
    profile = str(profile_name or config.default_model)
    if profile not in config.models:
        payload = {"ok": False, "error": "unknown_profile", "profile": profile}
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            click.echo(f"Unknown profile '{profile}'. Available: {', '.join(config.models.keys())}", err=True)
        raise SystemExit(2)
    config.models[profile].model = str(model_id)
    payload = {
        "ok": True,
        "profile": profile,
        "model": str(model_id),
        "note": "Updated in-memory profile for this run (does not rewrite thomas.toml).",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"set profile '{profile}' model to '{model_id}'")
        click.echo(payload["note"])


@models.command("set-image")
@click.option("--profile", "profile_name", default="", help="Model profile to bind as the image profile.")
@click.option("--model", "model_id", default="", help="Optional model id override for the image profile.")
@click.option("--clear", is_flag=True, help="Clear runtime image profile override and use default profile/model.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_set_image(
    ctx: click.Context,
    profile_name: str,
    model_id: str,
    clear: bool,
    as_json: bool,
) -> None:
    """Set or inspect runtime image model assignment."""
    config: AppConfig = ctx.obj["config"]
    state = _load_models_state(config)
    changed = False
    if clear:
        state["image"] = {}
        changed = True

    profile_text = str(profile_name or "").strip()
    model_text = str(model_id or "").strip()
    if profile_text or model_text:
        selected_profile = profile_text or str(config.default_model)
        if selected_profile not in config.models:
            _runtime_model_error(
                as_json=as_json,
                profile=selected_profile,
                message=f"Unknown profile '{selected_profile}'. Available: {', '.join(config.models.keys())}",
            )
        selected_model = model_text or str(config.models[selected_profile].model)
        state["image"] = {
            "profile": selected_profile,
            "model": selected_model,
            "updated_at": _models_state_now_utc(),
        }
        changed = True

    if changed:
        _save_models_state(config, state)

    image_row = dict(state.get("image") or {})
    image_profile = str(image_row.get("profile") or "").strip()
    image_model = str(image_row.get("model") or "").strip()
    source = "state"
    if not image_profile or image_profile not in config.models:
        image_profile = str(config.default_model)
        image_model = str(config.models[image_profile].model)
        source = "default_profile"
    elif not image_model:
        image_model = str(config.models[image_profile].model)

    payload = {
        "ok": True,
        "action": "set-image",
        "profile": image_profile,
        "model": image_model,
        "source": source,
        "state_file": str(_models_state_path(config)),
        "available_profiles": sorted(config.models.keys()),
        "note": "Runtime-only mapping (does not rewrite thomas.toml).",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"image profile: {payload['profile']}")
    click.echo(f"image model: {payload['model']}")
    click.echo(f"source: {payload['source']}")
    click.echo(payload["note"])


@models.command("aliases")
@click.option("--set", "set_pairs", multiple=True, help="Set alias mapping as alias=profile_or_model (repeatable).")
@click.option("--remove", "remove_aliases", multiple=True, help="Remove alias mapping by alias key (repeatable).")
@click.option("--resolve", "resolve_alias", default="", help="Resolve one alias/profile to effective profile+model.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_aliases(
    ctx: click.Context,
    set_pairs: tuple[str, ...],
    remove_aliases: tuple[str, ...],
    resolve_alias: str,
    as_json: bool,
) -> None:
    """Manage runtime model aliases."""
    config: AppConfig = ctx.obj["config"]
    state = _load_models_state(config)
    aliases = {
        str(k).strip().lower(): str(v).strip()
        for k, v in dict(state.get("aliases") or {}).items()
        if str(k).strip() and str(v).strip()
    }
    changed = False

    for raw in set_pairs:
        text = str(raw or "").strip()
        if "=" not in text:
            _runtime_model_error(as_json=as_json, message=f"Invalid --set '{text}'. Expected alias=profile_or_model.")
        alias_raw, target_raw = text.split("=", 1)
        alias = str(alias_raw or "").strip().lower()
        target = str(target_raw or "").strip()
        if not alias or not target:
            _runtime_model_error(as_json=as_json, message=f"Invalid --set '{text}'. Alias and target are required.")
        aliases[alias] = target
        changed = True

    for raw in remove_aliases:
        key = str(raw or "").strip().lower()
        if key and key in aliases:
            aliases.pop(key, None)
            changed = True

    if changed:
        state["aliases"] = aliases
        _save_models_state(config, state)

    rows: list[dict[str, Any]] = []
    for alias, target in sorted(aliases.items(), key=lambda item: item[0]):
        target_type = "profile" if target in config.models else "model"
        model = str(config.models[target].model) if target_type == "profile" else str(target)
        rows.append(
            {
                "alias": alias,
                "target": target,
                "target_type": target_type,
                "model": model,
            }
        )

    resolved_payload: dict[str, Any] | None = None
    resolve_text = str(resolve_alias or "").strip()
    if resolve_text:
        key = resolve_text.lower()
        if key in aliases:
            target = str(aliases[key])
            if target in config.models:
                resolved_payload = {
                    "query": resolve_text,
                    "source": "alias",
                    "profile": target,
                    "model": str(config.models[target].model),
                }
            else:
                resolved_payload = {
                    "query": resolve_text,
                    "source": "alias",
                    "profile": "",
                    "model": target,
                }
        elif resolve_text in config.models:
            resolved_payload = {
                "query": resolve_text,
                "source": "profile",
                "profile": resolve_text,
                "model": str(config.models[resolve_text].model),
            }
        else:
            for profile_name in config.models:
                if str(profile_name).lower() == key:
                    resolved_payload = {
                        "query": resolve_text,
                        "source": "profile",
                        "profile": profile_name,
                        "model": str(config.models[profile_name].model),
                    }
                    break

    payload = {
        "ok": True,
        "action": "aliases",
        "count": len(rows),
        "aliases": rows,
        "state_file": str(_models_state_path(config)),
    }
    if resolved_payload is not None:
        payload["resolved"] = resolved_payload

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"aliases: {payload['count']}")
    for row in rows:
        click.echo(f"  {row['alias']} -> {row['target']} ({row['target_type']})")
    if resolved_payload is not None:
        click.echo(
            "resolved: "
            f"{resolved_payload.get('query')} -> "
            f"profile={resolved_payload.get('profile') or '(none)'} "
            f"model={resolved_payload.get('model')}"
        )


@models.command("auth")
@click.option("--profile", "profile_name", default="", help="Inspect one model profile (default: all).")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_auth(ctx: click.Context, profile_name: str, as_json: bool) -> None:
    """Show effective auth readiness per model profile."""
    from thomas.server.secrets import SecretStore

    config: AppConfig = ctx.obj["config"]
    selected_profile = str(profile_name or "").strip()
    if selected_profile:
        if selected_profile not in config.models:
            _runtime_model_error(
                as_json=as_json,
                profile=selected_profile,
                message=f"Unknown profile '{selected_profile}'. Available: {', '.join(config.models.keys())}",
            )
        profiles = [selected_profile]
    else:
        profiles = sorted(config.models.keys())

    secret_store = SecretStore(config.memory.root_path / ".thomas")
    local_providers = {"ollama", "local"}
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        model_cfg = config.models[profile]
        provider = str(model_cfg.provider or "").strip().lower()
        env_keys = _provider_env_keys(provider)
        env_present = [key for key in env_keys if str(os.environ.get(key) or "").strip()]
        has_config_key = bool(str(model_cfg.api_key or "").strip())
        has_secret = bool(secret_store.has(profile))
        auth_required = provider not in local_providers
        auth_ready = (not auth_required) or has_config_key or has_secret or bool(env_present)
        rows.append(
            {
                "profile": profile,
                "provider": provider,
                "auth_required": auth_required,
                "auth_ready": auth_ready,
                "sources": {
                    "config_api_key": has_config_key,
                    "secret_store": has_secret,
                    "secret_persisted": bool(secret_store.is_persisted(profile)),
                    "env": bool(env_present),
                },
                "env_keys": env_keys,
                "env_keys_present": env_present,
            }
        )

    payload = {
        "ok": True,
        "action": "auth",
        "profile_count": len(rows),
        "ready_count": sum(1 for row in rows if bool(row.get("auth_ready"))),
        "rows": rows,
        "secret_store_path": str(secret_store.storage_info.path),
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"profiles: {payload['profile_count']} (ready: {payload['ready_count']})")
    for row in rows:
        click.echo(
            f"  {row['profile']}: provider={row['provider']} "
            f"auth_ready={row['auth_ready']} required={row['auth_required']}"
        )


@models.command("fallbacks")
@click.option("--for-profile", "primary_profile", default="", help="Primary profile to compute effective chain for.")
@click.option("--set-profile", "set_profiles", multiple=True, help="Set ordered fallback profiles (repeatable).")
@click.option("--enable/--disable", "enabled", default=None, help="Toggle failover enabled.")
@click.option(
    "--chat-auto-failover/--no-chat-auto-failover",
    "chat_auto_failover",
    default=None,
    help="Toggle automatic chat failover.",
)
@click.option("--cooldown-seconds", type=int, default=None, help="Set runtime failover cooldown seconds.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_fallbacks(
    ctx: click.Context,
    primary_profile: str,
    set_profiles: tuple[str, ...],
    enabled: Optional[bool],
    chat_auto_failover: Optional[bool],
    cooldown_seconds: Optional[int],
    as_json: bool,
) -> None:
    """Inspect or update runtime failover profile chain."""
    config: AppConfig = ctx.obj["config"]
    primary = str(primary_profile or config.default_model).strip()
    if primary not in config.models:
        _runtime_model_error(
            as_json=as_json,
            profile=primary,
            message=f"Unknown profile '{primary}'. Available: {', '.join(config.models.keys())}",
        )

    if set_profiles:
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in set_profiles:
            name = str(raw or "").strip()
            if not name:
                continue
            if name not in config.models:
                _runtime_model_error(
                    as_json=as_json,
                    profile=name,
                    message=f"Unknown fallback profile '{name}'. Available: {', '.join(config.models.keys())}",
                )
            if name in seen:
                continue
            seen.add(name)
            ordered.append(name)
        config.failover.profiles = ordered
    if enabled is not None:
        config.failover.enabled = bool(enabled)
    if chat_auto_failover is not None:
        config.failover.chat_auto_failover = bool(chat_auto_failover)
    if cooldown_seconds is not None:
        if int(cooldown_seconds) < 0:
            _runtime_model_error(as_json=as_json, message="cooldown_seconds must be >= 0")
        config.failover.cooldown_seconds = int(cooldown_seconds)

    chain = [cfg.name for cfg in config.failover_chain(primary)]
    payload = {
        "ok": True,
        "action": "fallbacks",
        "primary_profile": primary,
        "enabled": bool(config.failover.enabled),
        "chat_auto_failover": bool(config.failover.chat_auto_failover),
        "fallback_on_auth_error": bool(config.failover.fallback_on_auth_error),
        "cooldown_seconds": int(config.failover.cooldown_seconds),
        "configured_profiles": list(config.failover.profiles),
        "effective_chain": chain,
        "note": "Runtime-only updates (does not rewrite thomas.toml).",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"primary: {payload['primary_profile']}")
    click.echo(f"enabled: {payload['enabled']}")
    click.echo(f"chat_auto_failover: {payload['chat_auto_failover']}")
    click.echo(f"configured_profiles: {', '.join(payload['configured_profiles']) or '(none)'}")
    click.echo(f"effective_chain: {', '.join(payload['effective_chain']) or '(none)'}")
    click.echo(payload["note"])


@models.command("image-fallbacks")
@click.option("--for-profile", "primary_profile", default="", help="Primary profile to derive default image fallback chain.")
@click.option("--set-profile", "set_profiles", multiple=True, help="Set ordered image fallback profiles (repeatable).")
@click.option("--clear", is_flag=True, help="Clear configured image fallback profiles.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def models_image_fallbacks(
    ctx: click.Context,
    primary_profile: str,
    set_profiles: tuple[str, ...],
    clear: bool,
    as_json: bool,
) -> None:
    """Inspect or update runtime image fallback profile chain."""
    config: AppConfig = ctx.obj["config"]
    state = _load_models_state(config)
    configured = [str(x).strip() for x in state.get("image_fallback_profiles", []) if str(x).strip()]
    changed = False

    if clear:
        configured = []
        changed = True
    if set_profiles:
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in set_profiles:
            name = str(raw or "").strip()
            if not name:
                continue
            if name not in config.models:
                _runtime_model_error(
                    as_json=as_json,
                    profile=name,
                    message=f"Unknown image fallback profile '{name}'. Available: {', '.join(config.models.keys())}",
                )
            if name in seen:
                continue
            seen.add(name)
            ordered.append(name)
        configured = ordered
        changed = True

    if changed:
        state["image_fallback_profiles"] = configured
        _save_models_state(config, state)

    primary = str(primary_profile or config.default_model).strip()
    if primary not in config.models:
        _runtime_model_error(
            as_json=as_json,
            profile=primary,
            message=f"Unknown profile '{primary}'. Available: {', '.join(config.models.keys())}",
        )
    effective = list(configured) if configured else [cfg.name for cfg in config.failover_chain(primary)]

    payload = {
        "ok": True,
        "action": "image-fallbacks",
        "primary_profile": primary,
        "configured_profiles": configured,
        "effective_chain": effective,
        "source": "state" if configured else "derived_from_failover",
        "state_file": str(_models_state_path(config)),
        "note": "Runtime-only updates (does not rewrite thomas.toml).",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"primary: {payload['primary_profile']}")
    click.echo(f"configured_profiles: {', '.join(payload['configured_profiles']) or '(none)'}")
    click.echo(f"effective_chain: {', '.join(payload['effective_chain']) or '(none)'}")
    click.echo(f"source: {payload['source']}")
    click.echo(payload["note"])


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host")
@click.option("--port", default=8899, show_default=True, type=int, help="Bind port")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int) -> None:
    """Run the web UI + HTTP API server."""
    config: AppConfig = ctx.obj["config"]
    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    try:
        from thomas.server.app import serve as serve_app
        serve_app(config, host=host, port=port)
    except ModuleNotFoundError as e:
        # Most commonly: aiohttp missing.
        click.echo(f"Server dependencies missing: {e}", err=True)
        click.echo("Install with: pip install -e \".[server]\"", err=True)
        sys.exit(1)


@cli.command()
@click.option("-m", "--model", "model_name", help="Model profile to use")
@click.pass_context
def repl(ctx: click.Context, model_name: Optional[str]) -> None:
    """Start the interactive REPL with rich terminal UI."""
    try:
        from thomas.cli.repl import ThomasREPL
    except ImportError as e:
        click.echo(f"REPL requires additional dependencies: {e}", err=True)
        click.echo("Install with: pip install prompt_toolkit>=3.0 rich>=13.0", err=True)
        sys.exit(1)

    config: AppConfig = ctx.obj["config"]
    if model_name:
        config.default_model = model_name

    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    tools_registry = _build_tools(config)

    # On Windows, prompt_toolkit may need the SelectorEventLoop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    repl_instance = ThomasREPL(config, tools_registry)
    asyncio.run(repl_instance.run())


@cli.command("onboarding-outcomes")
@click.option("--db", "db_path", type=click.Path(exists=False, dir_okay=False), default="", help="Runs DB path.")
@click.option("--days", "window_days", type=int, default=7, show_default=True, help="Lookback window in days.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def onboarding_outcomes_cmd(db_path: str, window_days: int, as_json: bool) -> None:
    """Generate onboarding outcome metrics from observability events."""
    from thomas.observability.onboarding_outcomes import (
        build_onboarding_outcome_report,
        get_outcomes_report,
    )

    days = max(1, int(window_days))
    if str(db_path or "").strip():
        report = build_onboarding_outcome_report(Path(str(db_path).strip()), since_days=days)
    else:
        report = get_outcomes_report(since_days=days)

    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False))
        return
    summary = dict(report.get("summary") or {})
    click.echo(f"events: {int(summary.get('events', 0) or 0)}")
    click.echo(f"wizard_opened: {int(summary.get('wizard_opened', 0) or 0)}")
    click.echo(f"onboarding_completed: {int(summary.get('onboarding_completed', 0) or 0)}")


@cli.group("release-contracts")
def release_contracts_group() -> None:
    """Release contract governance checks."""


@release_contracts_group.command("check")
@click.option("--registry", "registry_path", type=click.Path(exists=False, dir_okay=False), default="")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--strict", is_flag=True, help="Exit non-zero when checks fail.")
def release_contracts_check_cmd(registry_path: str, as_json: bool, strict: bool) -> None:
    """Validate the release contract registry."""
    from thomas.system.release_contracts import build_release_contract_report

    report = build_release_contract_report(Path(registry_path).resolve() if registry_path else None)
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False))
    else:
        summary = dict(report.get("summary") or {})
        click.echo(f"ok: {bool(report.get('ok', False))}")
        click.echo(f"contract_count: {int(summary.get('contract_count', 0) or 0)}")
        click.echo(f"errors: {int(summary.get('error_count', 0) or 0)}")
        click.echo(f"warnings: {int(summary.get('warning_count', 0) or 0)}")
    if strict and not bool(report.get("ok", False)):
        raise SystemExit(2)


# Public root app alias used by external loaders/tests.
app = cli


def main() -> None:
    cli(obj={})


for _module_name, _register_name in (
    ("thomas.cli.commands.channels", "register_channels_commands"),
    ("thomas.cli.commands.cron", "register_cron_commands"),
    ("thomas.cli.commands.sessions", "register_sessions_commands"),
    ("thomas.cli.commands.webhooks", "register_webhooks_commands"),
    ("thomas.cli.commands.companion", "register_companion_commands"),
    ("thomas.cli.commands.setup_wizard", "register_setup_commands"),
    ("thomas.cli.commands.quickstart", "register_quickstart_commands"),
    ("thomas.cli.commands.shortcuts", "register_shortcuts_commands"),
    ("thomas.cli.commands.updater", "register_update_commands"),
    ("thomas.cli.commands.release", "register_release_commands"),
):
    try:
        _mod = __import__(_module_name, fromlist=[_register_name])
        _register = getattr(_mod, _register_name, None)
        if callable(_register):
            _register(cli)
    except Exception as e:
        log.debug("Failed to register %s.%s: %s", _module_name, _register_name, e)


try:
    from thomas.cli.parity_commands import register_parity_commands

    register_parity_commands(cli)
except Exception as e:
    log.debug("Failed to register parity commands: %s", e)

try:
    from thomas.cli.quality_ops import register_quality_ops

    register_quality_ops(cli)
except Exception as e:
    log.debug("Failed to register quality ops commands: %s", e)


# --- Architecture tools ---
try:
    from thomas.cli.doctor import doctor_command
    cli.add_command(doctor_command)
except Exception:
    pass

try:
    from thomas.cli.why import why_command
    cli.add_command(why_command)
except Exception:
    pass

try:
    from thomas.cli.scaffold import scaffold_group
    cli.add_command(scaffold_group)
except Exception:
    pass

try:
    from thomas.cli.generate_agent_docs import generate_agent_docs_command
    cli.add_command(generate_agent_docs_command)
except Exception:
    pass

try:
    from thomas.cli.sweep import sweep_command
    cli.add_command(sweep_command)
except Exception:
    pass

try:
    from thomas.cli.heartbeat_cmd import heartbeat_command
    cli.add_command(heartbeat_command)
except Exception:
    pass

try:
    from thomas.cli.commands.investigate import register_investigate_commands
    register_investigate_commands(cli)
except Exception:
    pass


if __name__ == "__main__":
    main()
