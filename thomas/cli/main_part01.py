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
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore[assignment]

from thomas.agent.loop import AgentLoop
from thomas.cli.main_chatops import register_chatops_commands
from thomas.cli.main_library_commands import register_library_commands
from thomas.cli.main_runtime_ops import (
    doctor_cmd as _doctor_cmd,
)
from thomas.cli.main_runtime_ops import (
    live_browser_smoke_cmd as _live_browser_smoke_cmd,
)
from thomas.cli.main_runtime_ops import (
    repo_clean_cmd as _repo_clean_cmd,
)
from thomas.cli.main_runtime_ops import (
    resolved_config_path as _resolved_config_path,
)
from thomas.cli.main_runtime_ops import (
    run_provider_checks as _run_provider_checks_impl,
)
from thomas.cli.main_runtime_ops import (
    status_cmd as _status_cmd,
)
from thomas.cli.main_runtime_ops import (
    telegram_run_cmd as _telegram_run_cmd,
)
from thomas.core.autonomy import clamp_autonomy_level
from thomas.core.config import (
    AppConfig,
    apply_runtime_data_env_defaults,
    load_config,
    normalize_profile_name,
    resolve_thomas_data_dir,
)
from thomas.core.events import EventType
from thomas.core.llm import LLMClient
from thomas.core.redaction import Redactor
from thomas.server.tool_extensions import register_all_optional_tools
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.git import register_git_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.shell import register_shell_tools
from thomas.tools.ssh import register_ssh_tools

log = logging.getLogger(__name__)
_CLI_REDACTOR = Redactor()


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _CLI_REDACTOR.redact_text(super().format(record))


def _emit_json(payload: Any, **kwargs: Any) -> None:
    click.echo(json.dumps(_CLI_REDACTOR.redact_obj(payload), **kwargs))


def _prepare_runtime_data_environment(
    *,
    data_dir_override: str | None,
    data_profile: str | None,
    reset_profile: bool,
) -> tuple[Path, str]:
    try:
        profile = normalize_profile_name(data_profile)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    if reset_profile and not profile:
        raise click.UsageError("--reset requires --profile <name>.")

    base_override = Path(data_dir_override).expanduser() if data_dir_override else None
    base_dir = resolve_thomas_data_dir(base_override, None)
    effective_dir = resolve_thomas_data_dir(base_override if base_override is not None else base_dir, profile)

    if reset_profile:
        if len(effective_dir.resolve().parts) < 3:
            raise click.UsageError(f"Refusing to reset unsafe profile path: {effective_dir}")
        shutil.rmtree(effective_dir, ignore_errors=True)

    effective_dir.mkdir(parents=True, exist_ok=True)
    apply_runtime_data_env_defaults(base_dir=base_dir, effective_dir=effective_dir, profile=profile, overwrite=True)
    return effective_dir, profile


# Compatibility marker for prompt-pack integration tests that expect the
# browser wiring hook to be present on argparse.
argparse.ArgumentParser.add_subparsers._p026_browser_wrapped = True


def _parse_model_switch_prompt(prompt: str, config: AppConfig) -> tuple[str | None, str | None, str | None]:
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

    m = re.match(r"^(switch|use|set|change)\s+(to\s+)?(model\s+)?(?P<name>[\w\-\.:]+)(?P<rest>.*)$", lower)
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
    formatter = _RedactingFormatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[handler], force=True)


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
    register_ssh_tools(registry)

    # Investigation tools — registered only if investigation DB has cases
    try:
        from thomas.tools.investigation import register_investigation_tools

        register_investigation_tools(registry)
    except ImportError:
        pass

    # Register all optional domain module tools
    register_all_optional_tools(registry)

    # Notebook tools
    try:
        from thomas.tools.notebook import register_notebook_tools

        register_notebook_tools(registry, sandbox)
    except ImportError:
        pass

    # Plugin-provided tools
    try:
        from thomas.tools.plugin_bridge import register_plugin_tools

        register_plugin_tools(registry, config)
    except ImportError:
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
    model_name: str | None,
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
                autonomy_lv = int(
                    event.data.get("autonomy_level", clamp_autonomy_level(autonomy_level, default=3)) or 3
                )
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
                    sys.stdout.write(f"\033[90m[runtime model: {active_profile_name}/{active_model}]\033[0m\n")
            except (OSError, FileNotFoundError):
                pass
    finally:
        await llm.close()
        if memory:
            memory.close()


@click.group(invoke_without_command=True)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("-c", "--config", "config_path", type=click.Path(exists=False), help="Config file path")
@click.option(
    "--data-dir",
    "data_dir_override",
    type=click.Path(file_okay=False),
    default=None,
    help="Base runtime data dir (default: OS app data, e.g. %LOCALAPPDATA%\\Thomas on Windows).",
)
@click.option(
    "--profile",
    "data_profile",
    default=None,
    help="Data profile name. Runtime state is stored under <data-dir>/<profile>/...",
)
@click.option(
    "--reset",
    "reset_profile",
    is_flag=True,
    help="Start fresh by deleting the selected profile dir before startup (requires --profile).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    verbose: bool,
    config_path: str | None,
    data_dir_override: str | None,
    data_profile: str | None,
    reset_profile: bool,
) -> None:
    """Thomas - autonomous AI execution platform for local and remote deployments."""
    effective_data_dir, normalized_profile = _prepare_runtime_data_environment(
        data_dir_override=data_dir_override,
        data_profile=data_profile,
        reset_profile=reset_profile,
    )
    _setup_logging(verbose)
    path = Path(config_path) if config_path else None
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(
        path,
        data_dir=Path(data_dir_override).expanduser() if data_dir_override else None,
        profile=normalized_profile or None,
    )
    ctx.obj["verbose"] = verbose
    ctx.obj["data_dir"] = str(effective_data_dir)
    ctx.obj["data_profile"] = normalized_profile

    # First-run nudge: suggest setup if no config exists
    if ctx.invoked_subcommand not in ("setup", "quickstart"):
        if not getattr(cli, "_first_run_checked", False):
            cli._first_run_checked = True  # type: ignore[attr-defined]
            try:
                from thomas.cli.commands.setup_wizard import _detect_existing_config

                if _detect_existing_config() is None:
                    click.echo(
                        click.style(
                            "  Thomas isn't configured yet. " "Run `thomas setup` to get started.\n",
                            fg="yellow",
                        )
                    )
            except ImportError:
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
            except ImportError:
                pass

    if ctx.invoked_subcommand is None:
        # Default to interactive mode for plain `thomas` invocations when attached to a terminal.
        if sys.stdin.isatty() and sys.stdout.isatty():
            ctx.invoke(repl, model_name=None)
        else:
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
    model_name: str | None,
    autonomy_level: int,
) -> None:
    """Send a single prompt and get a response."""
    config: AppConfig = ctx.obj["config"]
    selected_profile = _resolve_model_profile_name(config, model_name) if model_name else ""
    if model_name and not selected_profile:
        click.echo(f"Unknown model profile '{model_name}'. Available: {', '.join(config.models.keys())}", err=True)
        sys.exit(2)

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
            selected_profile = _resolve_model_profile_name(config, nl_model)
            if not selected_profile:
                click.echo(f"Unknown model profile '{nl_model}'. Available: {', '.join(config.models.keys())}", err=True)
                sys.exit(2)
            model_name = selected_profile
            if nl_prompt is None:
                click.echo(f"Switched to model '{model_name}' for this run. Ask a question.")
                return
            prompt = nl_prompt

    from thomas.core.model_resolution import resolve_effective_model
    from thomas.preferences.store import get_db_path

    resolved_profile, resolved_model_id = resolve_effective_model(
        config,
        cli_profile=selected_profile,
        env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
        user_id="default",
        db_path=get_db_path(),
    )
    if not resolved_profile:
        selected_profile = _resolve_model_profile_name(config, config.default_model)
        if not selected_profile:
            click.echo("No valid model profile configured.", err=True)
            sys.exit(2)
        resolved_profile = selected_profile

    config.default_model = resolved_profile
    if resolved_model_id and resolved_profile in config.models:
        config.models[resolved_profile].model = resolved_model_id

    asyncio.run(
        _run_chat(
            config,
            prompt,
            resolved_profile,
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

    click.echo(f"\nData dir: {config.memory.data_dir or '(auto)'}")
    click.echo(f"Data profile: {config.memory.profile or '(default)'}")
    click.echo(f"Memory root: {config.memory.root}")
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
    except json.JSONDecodeError:
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
        _emit_json(payload, ensure_ascii=False, indent=2)
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
    except json.JSONDecodeError:
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
        _emit_json(payload, ensure_ascii=False, indent=2)
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
        _emit_json(payload, ensure_ascii=False, indent=2)
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
        _emit_json(report, ensure_ascii=False)
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
        _emit_json(payload, ensure_ascii=False)
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
def models_discover(ctx: click.Context, model_name: str | None, timeout_s: float) -> None:
    """Discover model ids available at an endpoint (best effort)."""
    _run_models_discover(ctx, model_name=model_name, timeout_s=timeout_s)


def _run_models_discover(ctx: click.Context, model_name: str | None, timeout_s: float) -> None:
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


