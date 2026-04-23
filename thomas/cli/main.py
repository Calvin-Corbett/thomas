"""Thomas CLI entry point and command registration."""

from __future__ import annotations

import uuid

import thomas.cli._commands_misc  # noqa: F401

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

# These imports trigger registration of commands on the cli group
import thomas.cli._commands_models  # noqa: F401

# Import all command groups from submodules to register them
from thomas.agent.loop import AgentLoop
from thomas.cli import _commands_base as _commands_base_mod
from thomas.cli import _commands_models as _commands_models_mod
from thomas.cli._commands_base import _repl_needs_codex_event_loop, _resolve_model_profile_name, cli, log
from thomas.cli._commands_models import _resolve_repl_profile_from_prefs, models
from thomas.core.autonomy import clamp_autonomy_level
from thomas.core.llm import LLMClient

app = cli

_build_tools = _commands_base_mod._build_tools


def _build_memory(config):
    return _commands_base_mod._build_memory(config)


_models_discover_impl = _commands_models_mod._run_models_discover


def _run_models_discover(ctx, model_name: str | None, timeout_s: float) -> None:
    return _models_discover_impl(ctx, model_name=model_name, timeout_s=timeout_s)


_commands_models_mod._run_models_discover = lambda ctx, model_name=None, timeout_s=2.0: _run_models_discover(  # type: ignore[assignment]
    ctx,
    model_name,
    timeout_s,
)


@models.command("scan")
@click.option("--timeout", "timeout_s", type=float, default=2.0, show_default=True)
@click.pass_context
def models_scan(ctx: click.Context, timeout_s: float) -> None:
    """Compatibility alias for model discovery scans."""
    _run_models_discover(ctx, model_name=None, timeout_s=timeout_s)


async def _run_chat(config, prompt: str, model_name: str | None, *, autonomy_level: int = 3) -> None:
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
        thread_id=f"cli:{uuid.uuid4().hex}",
        autonomy_level=clamp_autonomy_level(autonomy_level, default=3),
    )
    try:
        async for _event in agent.run(prompt):
            pass
    finally:
        try:
            await llm.close()
        except (RuntimeError, OSError) as exc:
            log.debug("Failed to close CLI chat LLM client: %s", exc)
        if memory is not None:
            try:
                memory.close()
            except (AttributeError, RuntimeError, OSError) as exc:
                log.debug("Failed to close CLI chat memory backend: %s", exc)


def main() -> None:
    cli(obj={})


for _module_name, _register_name in (
    ("thomas.cli.commands.channels", "register_channels_commands"),
    ("thomas.cli.commands.cron", "register_cron_commands"),
    ("thomas.cli.commands.research", "register_research_commands"),
    ("thomas.cli.commands.evolve", "register_evolve_commands"),
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
except Exception as e:
    log.debug("Failed to register doctor command: %s", e)

try:
    from thomas.cli.why import why_command

    cli.add_command(why_command)
except Exception as e:
    log.debug("Failed to register why command: %s", e)

try:
    from thomas.cli.scaffold import scaffold_group

    cli.add_command(scaffold_group)
except Exception as e:
    log.debug("Failed to register scaffold command: %s", e)

try:
    from thomas.cli.generate_agent_docs import generate_agent_docs_command

    cli.add_command(generate_agent_docs_command)
except Exception as e:
    log.debug("Failed to register generate_agent_docs command: %s", e)

try:
    from thomas.cli.sweep import sweep_command

    cli.add_command(sweep_command)
except Exception as e:
    log.debug("Failed to register sweep command: %s", e)
try:
    from thomas.cli.heartbeat_cmd import heartbeat_command

    cli.add_command(heartbeat_command)
except Exception as e:
    log.debug("Failed to register heartbeat command: %s", e)

try:
    from thomas.cli.commands.investigate import register_investigate_commands

    register_investigate_commands(cli)
except Exception as e:
    log.debug("Failed to register investigate commands: %s", e)

try:
    from thomas.cli.commands.desktop_operator import register_desktop_operator_commands

    register_desktop_operator_commands(cli)
except Exception as e:
    log.debug("Failed to register desktop operator commands: %s", e)


if __name__ == "__main__":
    main()
