"""Click command wrapper for the interactive REPL."""

from __future__ import annotations

import asyncio
import os
import sys

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore[assignment]


@click.command()
@click.option("-m", "--model", "model_name", help="Model profile to use")
@click.option(
    "--trace-files/--no-trace-files",
    default=None,
    help="Show files read by REPL on startup and each turn.",
)
@click.pass_context
def repl(ctx: click.Context, model_name: str | None, trace_files: bool | None) -> None:
    """Start the interactive REPL with rich terminal UI."""
    try:
        from thomas.cli.repl import ThomasREPL
    except ImportError as exc:
        click.echo(f"REPL requires additional dependencies: {exc}", err=True)
        click.echo("Install with: pip install prompt_toolkit>=3.0 rich>=13.0", err=True)
        sys.exit(1)

    from thomas.cli._commands_base import _build_tools, _repl_needs_codex_event_loop, _resolve_model_profile_name

    config = ctx.obj["config"]
    try:
        from thomas.core.model_resolution import resolve_effective_model

        selected_model = _resolve_model_profile_name(config, model_name)
        if model_name and not selected_model:
            click.echo(
                f"Unknown model profile '{model_name}'. Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)

        resolved_profile, resolved_model_id = resolve_effective_model(
            config,
            cli_profile=selected_model,
            env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
            user_id="default",
        )
        if not resolved_profile:
            click.echo(
                f"Unknown model profile '{model_name}'. Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)
        config.default_model = resolved_profile
        if resolved_model_id and resolved_profile in config.models:
            config.models[resolved_profile].model = resolved_model_id
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        resolved_profile = _resolve_model_profile_name(config, config.default_model)
        if not resolved_profile:
            click.echo("No valid model profile configured.", err=True)
            sys.exit(2)
        config.default_model = resolved_profile
    selected_model = config.default_model

    errors = config.validate()
    if errors:
        for error in errors:
            click.echo(f"Config error: {error}", err=True)
        sys.exit(1)

    tools_registry = _build_tools(config)

    if sys.platform == "win32":
        if _repl_needs_codex_event_loop(config, selected_model):
            policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
        else:
            policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if policy_cls is not None:
            asyncio.set_event_loop_policy(policy_cls())

    if trace_files is None:
        trace_files = str(os.environ.get("THOMAS_REPL_TRACE_FILES", "1")).strip().lower() not in (
            "0",
            "false",
            "off",
            "no",
        )
    repl_instance = ThomasREPL(config, tools_registry, trace_file_reads=trace_files)
    asyncio.run(repl_instance.run())
