"""Thomas CLI entry point and command registration."""

from __future__ import annotations

import thomas.cli._commands_misc  # noqa: F401

# These imports trigger registration of commands on the cli group
import thomas.cli._commands_models  # noqa: F401
from thomas.agent.loop import AgentLoop  # noqa: F401  -- re-export for tests

# Import all command groups from submodules to register them
from thomas.cli._commands_base import (  # noqa: F401  -- re-exports for tests
    _build_memory,
    _build_tools,
    _repl_needs_codex_event_loop,
    _resolve_model_profile_name,
    _run_chat,
    cli,
    log,
)
from thomas.cli._commands_models import (  # noqa: F401  -- re-exports for tests
    _resolve_repl_profile_from_prefs,
    _run_models_discover,
)

# Re-export ``LLMClient`` so tests that
# ``monkeypatch.setattr(thomas.cli.main, "LLMClient", ...)`` reach the
# CLI's chat code path. The CLI consumes the symbol via
# :mod:`thomas.cli._commands_base`, which imports from
# :mod:`thomas.core.llm` — the patched value on this module is the legacy
# test contract.
from thomas.core.llm import LLMClient  # noqa: F401  -- re-export for tests

app = cli

# Commands that talk to a model. Only these pay for the server-side sign-in
# import; `thomas status` and friends stay as light as they were.
_MODEL_COMMANDS = frozenset({"chat", "repl", "agent"})


def _register_transport_signins(argv: list[str]) -> bool:
    """Give the CLI the ChatGPT sign-in the server has, before a model command runs.

    The core transport asks ``codex_auth`` for a registered resolver; until
    2026-09-05 only ``thomas.server.openai_codex_oauth`` registered one, so
    ``thomas chat`` with the default profile failed in every shell with
    "ChatGPT OAuth is not connected". Returns True when the import happened.
    """
    first = next((arg for arg in argv if not arg.startswith("-")), "")
    if first not in _MODEL_COMMANDS:
        return False
    try:
        from thomas.core import codex_auth
        from thomas.server import openai_codex_oauth
    except (ImportError, ModuleNotFoundError, RuntimeError, OSError) as exc:
        log.warning("ChatGPT sign-in unavailable to the CLI: %s", exc)
        return False
    # Importing registers the resolver once; a module already loaded (or a
    # slot cleared since) needs the explicit call.
    if codex_auth._access_token_resolver is None:
        codex_auth.register_access_token_resolver(openai_codex_oauth._resolve_registered_access_token)
    return True


def main() -> None:
    import sys

    _register_transport_signins(sys.argv[1:])
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
    ("thomas.cli.commands.training", "register_training_commands"),
    ("thomas.cli.commands.ship", "register_ship_commands"),
):
    try:
        _mod = __import__(_module_name, fromlist=[_register_name])
        _register = getattr(_mod, _register_name, None)
        if callable(_register):
            _register(cli)
    except Exception as e:
        log.warning("Failed to register %s.%s: %s", _module_name, _register_name, e)


try:
    from thomas.cli.parity_commands import register_parity_commands

    register_parity_commands(cli)
except Exception as e:
    log.warning("Failed to register parity commands: %s", e)

try:
    from thomas.cli.quality_ops import register_quality_ops

    register_quality_ops(cli)
except Exception as e:
    log.warning("Failed to register quality ops commands: %s", e)


# --- Architecture tools ---
try:
    from thomas.cli.doctor import doctor_command

    cli.add_command(doctor_command)
except Exception as e:
    log.warning("Failed to register doctor command: %s", e)

try:
    from thomas.cli.why import why_command

    cli.add_command(why_command)
except Exception as e:
    log.warning("Failed to register why command: %s", e)

try:
    from thomas.cli.scaffold import scaffold_group

    cli.add_command(scaffold_group)
except Exception as e:
    log.warning("Failed to register scaffold command: %s", e)

try:
    from thomas.cli.generate_agent_docs import generate_agent_docs_command

    cli.add_command(generate_agent_docs_command)
except Exception as e:
    log.warning("Failed to register generate_agent_docs command: %s", e)

try:
    from thomas.cli.sweep import sweep_command

    cli.add_command(sweep_command)
except Exception as e:
    log.warning("Failed to register sweep command: %s", e)
try:
    from thomas.cli.heartbeat_cmd import heartbeat_command

    cli.add_command(heartbeat_command)
except Exception as e:
    log.warning("Failed to register heartbeat command: %s", e)

try:
    from thomas.cli.consolidate_cmd import consolidate_command

    cli.add_command(consolidate_command)
except (ImportError, ModuleNotFoundError, AttributeError, RuntimeError, TypeError) as e:
    log.warning("Failed to register consolidate command: %s", e)

try:
    from thomas.cli.commands.investigate import register_investigate_commands

    register_investigate_commands(cli)
except Exception as e:
    log.warning("Failed to register investigate commands: %s", e)

try:
    from thomas.cli.commands.desktop_operator import register_desktop_operator_commands

    register_desktop_operator_commands(cli)
except Exception as e:
    log.warning("Failed to register desktop operator commands: %s", e)


if __name__ == "__main__":
    main()
