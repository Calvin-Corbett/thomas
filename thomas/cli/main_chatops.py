"""Chat ops command registrations for the top-level CLI."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore[assignment]

from thomas.core.config import AppConfig


def register_chatops_commands(
    cli: click.Group,
    *,
    build_tools: Callable[[AppConfig], Any],
    build_memory: Callable[[AppConfig], Any],
    telegram_run_cmd: Callable[..., None],
    logger: logging.Logger,
) -> None:
    """Register codex, doppelganger, telegram, and tools commands."""

    @cli.group(
        invoke_without_command=True,
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    )
    @click.pass_context
    def codex(ctx: click.Context) -> None:
        """Codex integration - use your ChatGPT subscription with Thomas."""
        if ctx.invoked_subcommand is not None:
            return

        # Passthrough to native Codex CLI interactive mode so the session
        # stays open instead of exiting as a one-shot helper command.
        try:
            from thomas.codex.bridge import _find_codex

            codex_bin = _find_codex()
        except Exception as exc:
            click.echo(f"Failed to find Codex CLI: {exc}", err=True)
            ctx.exit(2)

        passthrough_args = list(ctx.args or [])
        try:
            code = subprocess.call([codex_bin] + passthrough_args)
        except Exception as exc:
            click.echo(f"Failed to launch Codex CLI: {exc}", err=True)
            ctx.exit(2)
        ctx.exit(int(code))

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
                click.echo('You can now use: thomas chat -m codex "your prompt"')
                click.echo('Or set default_model = "codex" in thomas.toml')
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
                    try:
                        models_list = await bridge.list_models()
                        if models_list:
                            click.echo("  Models:")
                            for model in models_list:
                                default_flag = " (default)" if model.is_default else ""
                                click.echo(f"    {model.id}{default_flag}")
                    except Exception as exc:
                        logger.debug("Failed to list codex models in status: %s", exc)
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
                for model in models_found:
                    default_flag = " (default)" if model.is_default else ""
                    name = f" - {model.display_name}" if model.display_name else ""
                    click.echo(f"  {model.id}{name}{default_flag}")
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
        from thomas.forge.anvil.doppelganger import get_paths

        paths = get_paths()
        click.echo("Doppelganger paths:")
        click.echo(f"  blue_root      : {paths.blue_root}")
        click.echo(f"  dg_root        : {paths.dg_root}")
        click.echo(
            f"  green_root     : {paths.green_root} " f"({'present' if paths.green_root.exists() else 'missing'})"
        )
        click.echo(f"  green_runtime  : {paths.green_runtime}")
        click.echo(
            f"  green_venv     : {paths.green_venv} " f"({'present' if paths.green_venv.exists() else 'missing'})"
        )
        click.echo(f"  backups_root   : {paths.backups_root}")

    @doppelganger.command("sync")
    @click.pass_context
    def dg_sync(ctx: click.Context) -> None:
        """Sync Blue -> Green (creates/updates the green sandbox working copy)."""
        from thomas.forge.anvil.doppelganger import get_paths, sync_blue_to_green

        paths = get_paths()
        paths.dg_root.mkdir(parents=True, exist_ok=True)
        sync_blue_to_green(paths)
        click.echo(f"Synced Blue -> Green at: {paths.green_root}")

    @doppelganger.command("test")
    @click.option(
        "--sync-from-blue",
        is_flag=True,
        help="Sync Blue -> Green before running tests (WARNING: overwrites green).",
    )
    @click.pass_context
    def dg_test(ctx: click.Context, sync_from_blue: bool) -> None:
        """Run tests in Green (uses isolated green venv)."""
        from thomas.forge.anvil.doppelganger import (
            get_paths,
            run_green_tests,
            sync_blue_to_green,
        )

        paths = get_paths()
        if sync_from_blue:
            sync_blue_to_green(paths)
        if not paths.green_root.exists():
            click.echo("Green slot not found. Run: thomas doppelganger sync", err=True)
            sys.exit(2)
        run_green_tests(paths)
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
        from thomas.forge.anvil.doppelganger import (
            get_paths,
            run_green_server,
            sync_blue_to_green,
        )

        paths = get_paths()
        if sync_from_blue:
            sync_blue_to_green(paths)
        if not paths.green_root.exists():
            click.echo("Green slot not found. Run: thomas doppelganger sync", err=True)
            sys.exit(2)
        click.echo(f"Green UI: http://{host}:{int(port)}/ (memory root: {paths.green_runtime})")
        run_green_server(paths, host=host, port=int(port))

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
        from thomas.forge.anvil.doppelganger import get_paths, latest_backup, promote_green_to_blue

        paths = get_paths()
        if not paths.green_root.exists():
            click.echo("Green slot not found. Run: thomas doppelganger sync", err=True)
            sys.exit(2)

        before = latest_backup(paths)
        backup = promote_green_to_blue(paths, stop_port=int(stop_port))
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
    def dg_rollback(ctx: click.Context, backup_path: str | None) -> None:
        """Rollback Blue to the latest (or specified) backup snapshot."""
        from thomas.forge.anvil.doppelganger import get_paths, rollback

        paths = get_paths()
        backup = Path(backup_path).resolve() if backup_path else None
        restored = rollback(paths, backup_dir=backup)
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
        model_name: str | None,
        shared_memory: bool,
        all_memories: bool,
        profile_memory: bool,
        sessions_file: Path | None,
        no_session_persist: bool,
    ) -> None:
        """Run a Telegram bot that routes messages through Thomas."""
        telegram_run_cmd(
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
            build_tools=build_tools,
            build_memory=build_memory,
            logger=logger,
        )

    @cli.command()
    @click.pass_context
    def tools(ctx: click.Context) -> None:
        """List available tools."""
        config: AppConfig = ctx.obj["config"]
        registry = build_tools(config)

        for category in registry.list_categories():
            click.echo(f"\n{category}:")
            for tool in registry.list_tools(category):
                click.echo(f"  {tool.name} - {tool.description[:80]}")
