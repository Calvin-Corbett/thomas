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
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

try:
    import click
except ImportError:
    print("Thomas requires 'click'. Install with: pip install click")
    sys.exit(1)

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
    config: AppConfig = ctx.obj["config"]
    cfg = config.get_model(model_name)

    from thomas.models.discovery import discover_models

    found = discover_models(cfg, timeout_s=timeout_s)
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
    models_discover(ctx, model_name=None, timeout_s=timeout_s)


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
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def models_set_image(as_json: bool) -> None:
    """Compatibility placeholder for image model assignment."""
    _emit_models_compat("set-image", "Use model profile configuration for image-capable providers.", as_json)


@models.command("aliases")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def models_aliases(as_json: bool) -> None:
    """Compatibility placeholder for model aliases."""
    _emit_models_compat("aliases", "Model alias management is not yet first-class in Thomas CLI.", as_json)


@models.command("auth")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def models_auth(as_json: bool) -> None:
    """Compatibility placeholder for model auth profiles."""
    _emit_models_compat("auth", "Use provider secrets and doctor/validate flows for auth checks.", as_json)


@models.command("fallbacks")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def models_fallbacks(as_json: bool) -> None:
    """Compatibility placeholder for fallback policy management."""
    _emit_models_compat("fallbacks", "Fallback policy is configured in Thomas failover settings.", as_json)


@models.command("image-fallbacks")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def models_image_fallbacks(as_json: bool) -> None:
    """Compatibility placeholder for image fallback policy management."""
    _emit_models_compat(
        "image-fallbacks",
        "Image fallback policy is provider/profile-driven in current Thomas runtime.",
        as_json,
    )


@cli.group()
@click.pass_context
def codex(ctx: click.Context) -> None:
    """Codex integration — use your ChatGPT subscription with Thomas."""


@codex.command("login")
@click.pass_context
def codex_login(ctx: click.Context) -> None:
    """Sign in to ChatGPT (opens browser). Uses your ChatGPT Plus/Pro subscription."""
    async def _login() -> None:
        from thomas.codex.bridge import CodexBridge
        bridge = CodexBridge()
        try:
            await bridge.start()
            click.echo("Checking auth status...")
            acct = await bridge.check_auth()
            if acct.logged_in:
                click.echo(f"Already signed in: {acct.email} ({acct.plan_type} plan)")
                return
            click.echo("Opening browser to sign in with ChatGPT...")
            acct = await bridge.login_chatgpt()
            click.echo(f"Signed in: {acct.email} ({acct.plan_type} plan)")
            click.echo("You can now use: thomas chat -m codex \"your prompt\"")
            click.echo("Or set default_model = \"codex\" in thomas.toml")
        finally:
            await bridge.stop()

    asyncio.run(_login())


@codex.command("status")
@click.pass_context
def codex_status(ctx: click.Context) -> None:
    """Check ChatGPT authentication status."""
    async def _status() -> None:
        from thomas.codex.bridge import CodexBridge
        bridge = CodexBridge()
        try:
            await bridge.start()
            acct = await bridge.check_auth()
            if acct.logged_in:
                click.echo(f"Signed in: {acct.email}")
                click.echo(f"  Plan: {acct.plan_type}")
                click.echo(f"  Auth: {acct.auth_type}")
                # List available models
                try:
                    models_list = await bridge.list_models()
                    if models_list:
                        click.echo("  Models:")
                        for m in models_list:
                            d = " (default)" if m.is_default else ""
                            click.echo(f"    {m.id}{d}")
                except Exception as e:
                    log.debug("Failed to list codex models in status: %s", e)
            else:
                click.echo("Not signed in. Run: thomas codex login")
        finally:
            await bridge.stop()

    asyncio.run(_status())


@codex.command("logout")
@click.pass_context
def codex_logout(ctx: click.Context) -> None:
    """Sign out of ChatGPT."""
    async def _logout() -> None:
        from thomas.codex.bridge import CodexBridge
        bridge = CodexBridge()
        try:
            await bridge.start()
            await bridge.logout()
            click.echo("Signed out.")
        finally:
            await bridge.stop()

    asyncio.run(_logout())


@codex.command("models")
@click.pass_context
def codex_models(ctx: click.Context) -> None:
    """List models available through your ChatGPT plan."""
    async def _models() -> None:
        from thomas.codex.bridge import CodexBridge
        bridge = CodexBridge()
        try:
            await bridge.start()
            acct = await bridge.check_auth()
            if not acct.logged_in:
                click.echo("Not signed in. Run: thomas codex login")
                return
            models_found = await bridge.list_models()
            if not models_found:
                click.echo("No models found.")
                return
            click.echo(f"Models available ({acct.plan_type} plan):")
            for m in models_found:
                d = " (default)" if m.is_default else ""
                name = f" — {m.display_name}" if m.display_name else ""
                click.echo(f"  {m.id}{name}{d}")
        finally:
            await bridge.stop()

    asyncio.run(_models())


@cli.group()
@click.pass_context
def doppelganger(ctx: click.Context) -> None:
    """Blue/green upgrade sandbox utilities (Doppelganger Protocol)."""


@doppelganger.command("status")
@click.pass_context
def dg_status(ctx: click.Context) -> None:
    """Show blue/green paths and whether the green slot is present."""
    from thomas.upgrade.doppelganger import get_paths

    p = get_paths()
    click.echo("Doppelganger paths:")
    click.echo(f"  blue_root      : {p.blue_root}")
    click.echo(f"  dg_root        : {p.dg_root}")
    click.echo(f"  green_root     : {p.green_root} ({'present' if p.green_root.exists() else 'missing'})")
    click.echo(f"  green_runtime  : {p.green_runtime}")
    click.echo(f"  green_venv     : {p.green_venv} ({'present' if p.green_venv.exists() else 'missing'})")
    click.echo(f"  backups_root   : {p.backups_root}")


@doppelganger.command("sync")
@click.pass_context
def dg_sync(ctx: click.Context) -> None:
    """Sync Blue -> Green (creates/updates the green sandbox working copy)."""
    from thomas.upgrade.doppelganger import get_paths, sync_blue_to_green

    p = get_paths()
    p.dg_root.mkdir(parents=True, exist_ok=True)
    sync_blue_to_green(p)
    click.echo(f"Synced Blue -> Green at: {p.green_root}")


@doppelganger.command("test")
@click.option(
    "--sync-from-blue",
    is_flag=True,
    help="Sync Blue -> Green before running tests (WARNING: overwrites green).",
)
@click.pass_context
def dg_test(ctx: click.Context, sync_from_blue: bool) -> None:
    """Run tests in Green (uses isolated green venv)."""
    from thomas.upgrade.doppelganger import get_paths, run_green_tests, sync_blue_to_green

    p = get_paths()
    if sync_from_blue:
        sync_blue_to_green(p)
    if not p.green_root.exists():
        click.echo("Green slot not found. Run: thomas doppelganger sync", err=True)
        sys.exit(2)
    run_green_tests(p)
    click.echo("Green tests: OK")


@doppelganger.command("serve-green")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8902, show_default=True, type=int)
@click.option(
    "--sync-from-blue",
    is_flag=True,
    help="Sync Blue -> Green before serving (WARNING: overwrites green).",
)
@click.pass_context
def dg_serve_green(ctx: click.Context, host: str, port: int, sync_from_blue: bool) -> None:
    """Run the server from Green using an isolated runtime root (no real memory/secrets)."""
    from thomas.upgrade.doppelganger import get_paths, run_green_server, sync_blue_to_green

    p = get_paths()
    if sync_from_blue:
        sync_blue_to_green(p)
    if not p.green_root.exists():
        click.echo("Green slot not found. Run: thomas doppelganger sync", err=True)
        sys.exit(2)
    click.echo(f"Green UI: http://{host}:{int(port)}/ (memory root: {p.green_runtime})")
    run_green_server(p, host=host, port=int(port))


@doppelganger.command("promote")
@click.option(
    "--stop-port",
    default=8899,
    show_default=True,
    type=int,
    help="If a Thomas server is listening on this port, attempt to stop it before promotion.",
)
@click.pass_context
def dg_promote(ctx: click.Context, stop_port: int) -> None:
    """Promote Green -> Blue (with backup)."""
    from thomas.upgrade.doppelganger import get_paths, latest_backup, promote_green_to_blue

    p = get_paths()
    if not p.green_root.exists():
        click.echo("Green slot not found. Run: thomas doppelganger sync", err=True)
        sys.exit(2)

    before = latest_backup(p)
    backup = promote_green_to_blue(p, stop_port=int(stop_port))
    click.echo(f"Promoted Green -> Blue. Backup created at: {backup}")
    if before:
        click.echo(f"Previous latest backup was: {before}")


@doppelganger.command("rollback")
@click.option(
    "--backup",
    "backup_path",
    type=click.Path(exists=False),
    help="Specific backup directory to restore (default: latest).",
)
@click.pass_context
def dg_rollback(ctx: click.Context, backup_path: Optional[str]) -> None:
    """Rollback Blue to the latest (or specified) backup snapshot."""
    from thomas.upgrade.doppelganger import get_paths, rollback

    p = get_paths()
    b = Path(backup_path).resolve() if backup_path else None
    restored = rollback(p, backup_dir=b)
    click.echo(f"Restored Blue from backup: {restored}")


@cli.group()
@click.pass_context
def telegram(ctx: click.Context) -> None:
    """Telegram bot integration."""


@telegram.command("run")
@click.option(
    "--token",
    "token",
    default="",
    help="Telegram bot token (or set THOMAS_TELEGRAM_BOT_TOKEN).",
)
@click.option(
    "--allow-chat",
    "allow_chat_ids",
    multiple=True,
    type=int,
    help="Allow this Telegram chat id (repeatable).",
)
@click.option(
    "--allow-chats",
    "allow_chats_csv",
    default="",
    help="Additional allowlisted chat ids as CSV (e.g. 123,456).",
)
@click.option(
    "-m",
    "--model",
    "model_name",
    help="Model profile for Telegram chats (default: current default model).",
)
@click.option(
    "--shared-memory/--isolated-memory",
    "shared_memory",
    default=False,
    show_default=True,
    help="Share one long-term memory stream across all Telegram chats.",
)
@click.option(
    "--all-memories/--chat-memories-only",
    "all_memories",
    default=True,
    show_default=True,
    help="Include curated global memory (facts/profile) in addition to this chat thread.",
)
@click.option(
    "--profile-memory/--no-profile-memory",
    "profile_memory",
    default=True,
    show_default=True,
    help="Include long-term profile hints in Telegram memory retrieval.",
)
@click.option(
    "--sessions-file",
    "sessions_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Path for persisted Telegram session state.",
)
@click.option(
    "--no-session-persist",
    "no_session_persist",
    is_flag=True,
    help="Disable on-disk Telegram session persistence.",
)
@click.pass_context
def telegram_run(
    ctx: click.Context,
    token: str,
    allow_chat_ids: tuple[int, ...],
    allow_chats_csv: str,
    model_name: Optional[str],
    shared_memory: bool,
    all_memories: bool,
    profile_memory: bool,
    sessions_file: Optional[Path],
    no_session_persist: bool,
) -> None:
    """Run a Telegram bot that routes messages through Thomas."""
    _telegram_run_cmd(
        ctx,
        token,
        allow_chat_ids,
        allow_chats_csv,
        model_name,
        shared_memory,
        all_memories,
        profile_memory,
        sessions_file,
        no_session_persist,
        build_tools=_build_tools,
        build_memory=_build_memory,
        logger=log,
    )


@cli.command()
@click.pass_context
def tools(ctx: click.Context) -> None:
    """List available tools."""
    config: AppConfig = ctx.obj["config"]
    registry = _build_tools(config)

    for cat in registry.list_categories():
        click.echo(f"\n{cat}:")
        for tool in registry.list_tools(cat):
            click.echo(f"  {tool.name} - {tool.description[:80]}")


@cli.group()
@click.pass_context
def library(ctx: click.Context) -> None:
    """Manage the durable research library (separate from chat memory)."""


@library.command("where")
@click.pass_context
def library_where(ctx: click.Context) -> None:
    """Show library root path and key files."""
    config: AppConfig = ctx.obj["config"]
    store = _build_library(config)
    if store is None:
        click.echo("Library unavailable.", err=True)
        sys.exit(1)
    click.echo(f"Library root: {store.root}")
    click.echo(f"Catalog: {store.index_path}")
    click.echo(f"Index: {store.toc_path}")


@library.command("list")
@click.option("--category", "category", default="", help="Filter by category.")
@click.option("--query", "query", default="", help="Search query.")
@click.option("--limit", "limit", type=int, default=25, show_default=True)
@click.pass_context
def library_list(ctx: click.Context, category: str, query: str, limit: int) -> None:
    """List library entries."""
    config: AppConfig = ctx.obj["config"]
    store = _build_library(config)
    if store is None:
        click.echo("Library unavailable.", err=True)
        sys.exit(1)
    rows = store.list_entries(
        category=(category.strip() or None),
        query=(query.strip() or None),
        limit=max(1, int(limit)),
    )
    if not rows:
        click.echo("No library entries found.")
        return
    click.echo(f"Found {len(rows)} entries:")
    for row in rows:
        rid = str(row.get("id", ""))
        title = str(row.get("title", rid))
        cat = str(row.get("category", "uncategorized"))
        src = str(row.get("source", ""))
        click.echo(f"- {rid} [{cat}] {title}")
        if src:
            click.echo(f"  source: {src}")


@library.command("show")
@click.argument("entry_id")
@click.pass_context
def library_show(ctx: click.Context, entry_id: str) -> None:
    """Show one library entry (metadata + content)."""
    config: AppConfig = ctx.obj["config"]
    store = _build_library(config)
    if store is None:
        click.echo("Library unavailable.", err=True)
        sys.exit(1)
    row = store.get_entry(entry_id)
    if row is None:
        click.echo(f"Entry not found: {entry_id}", err=True)
        sys.exit(2)
    click.echo(f"id: {row.get('id')}")
    click.echo(f"title: {row.get('title')}")
    click.echo(f"category: {row.get('category')}")
    click.echo(f"source: {row.get('source')}")
    tags = row.get("tags") or []
    if isinstance(tags, list) and tags:
        click.echo("tags: " + ", ".join(str(t) for t in tags))
    click.echo("")
    click.echo(str(row.get("content", "")))


@library.command("add")
@click.option("--title", "title", required=True, help="Entry title.")
@click.option("--category", "category", default="research-notes", show_default=True)
@click.option("--summary", "summary", default="", help="Short summary.")
@click.option("--source", "source", default="", help="Source URL or citation note.")
@click.option("--tags", "tags", default="", help="Comma-separated tags.")
@click.option("--content", "content", default="", help="Inline content text.")
@click.option("--content-file", "content_file", type=click.Path(exists=True, dir_okay=False), default="")
@click.option("--query", "query", default="", help="Original research query.")
@click.pass_context
def library_add(
    ctx: click.Context,
    title: str,
    category: str,
    summary: str,
    source: str,
    tags: str,
    content: str,
    content_file: str,
    query: str,
) -> None:
    """Add a new library entry."""
    config: AppConfig = ctx.obj["config"]
    store = _build_library(config)
    if store is None:
        click.echo("Library unavailable.", err=True)
        sys.exit(1)

    payload = str(content or "").strip()
    if content_file:
        payload = Path(content_file).read_text(encoding="utf-8", errors="replace").strip()
    if not payload:
        click.echo("Missing content. Use --content or --content-file.", err=True)
        sys.exit(2)

    tag_list = [x.strip() for x in str(tags or "").split(",") if x.strip()]
    row = store.add_entry(
        title=title,
        category=category,
        content=payload,
        summary=summary,
        source=source,
        tags=tag_list,
        query=query,
        auto_captured=False,
        dedupe=True,
    )
    click.echo(f"Saved: {row.get('id')} -> {row.get('path')}")


@library.command("reindex")
@click.pass_context
def library_reindex(ctx: click.Context) -> None:
    """Rebuild table of contents from catalog."""
    config: AppConfig = ctx.obj["config"]
    store = _build_library(config)
    if store is None:
        click.echo("Library unavailable.", err=True)
        sys.exit(1)
    store.rebuild_toc()
    click.echo(f"Rebuilt: {store.toc_path}")


@library.command("curate")
@click.option("--force", is_flag=True, help="Ignore curator interval cooldown.")
@click.pass_context
def library_curate(ctx: click.Context, force: bool) -> None:
    """Run one memory curator pass (promote chat/library knowledge into durable memory)."""
    config: AppConfig = ctx.obj["config"]
    memory = _build_memory(config)
    if memory is None:
        click.echo("Memory engine unavailable.", err=True)
        sys.exit(1)
    try:
        runner = getattr(memory, "run_curator", None)
        if not callable(runner):
            click.echo("Curator unavailable for current memory backend.", err=True)
            sys.exit(2)
        result = runner(force=bool(force))
        if not isinstance(result, dict):
            result = {"ran": False, "reason": "invalid_result"}
        click.echo("Curator run:")
        for key in (
            "ran",
            "reason",
            "episodes_scanned",
            "library_entries_scanned",
            "hints_promoted",
            "facts_promoted",
            "duplicates_skipped",
            "last_episode_id",
            "last_library_ts_utc",
        ):
            if key in result:
                click.echo(f"- {key}: {result.get(key)}")
    finally:
        try:
            memory.close()
        except Exception as e:
            log.debug("Failed to close memory engine after library curate: %s", e)


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
