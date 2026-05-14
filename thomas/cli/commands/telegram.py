from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from collections.abc import Callable

import click

from thomas.core.config import AppConfig


def register_telegram_commands(
    cli: click.Group,
    *,
    build_tools: Callable[[AppConfig], Any],
    build_memory: Callable[[AppConfig], Any],
    logger: Any,
) -> None:
    @click.group(name="telegram")
    @click.pass_context
    def telegram(ctx: click.Context) -> None:
        """Telegram bot integration."""
        _ = ctx

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
        config: AppConfig = ctx.obj["config"]
        errors = config.validate()
        if errors:
            for e in errors:
                click.echo(f"Config error: {e}", err=True)
            sys.exit(1)

        selected_model = model_name or config.default_model
        if selected_model not in config.models:
            click.echo(
                f"Unknown model profile '{selected_model}'. "
                f"Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)

        token_value = str(token or os.environ.get("THOMAS_TELEGRAM_BOT_TOKEN") or "").strip()
        if not token_value:
            click.echo("Telegram token missing.", err=True)
            click.echo("Set THOMAS_TELEGRAM_BOT_TOKEN or pass --token.", err=True)
            sys.exit(2)

        try:
            from thomas.integrations.telegram import (
                default_sessions_path,
                parse_allowed_chat_ids,
                run_telegram_polling,
            )
        except Exception as e:
            click.echo(f"Telegram integration unavailable: {type(e).__name__}: {e}", err=True)
            sys.exit(1)

        allowlisted: set[int] = set(int(x) for x in allow_chat_ids)
        allowlisted.update(parse_allowed_chat_ids(os.environ.get("THOMAS_TELEGRAM_ALLOWED_CHAT_IDS")))
        allowlisted.update(parse_allowed_chat_ids(allow_chats_csv))

        env_sessions = os.environ.get("THOMAS_TELEGRAM_SESSIONS_FILE")
        if sessions_file is None and env_sessions:
            sessions_file = Path(env_sessions)
        session_store = None if no_session_persist else (sessions_file or default_sessions_path(config))

        tools_registry = build_tools(config)
        memory = build_memory(config)

        click.echo(f"Starting Telegram bot with model profile '{selected_model}'...")
        if allowlisted:
            click.echo("Allowlisted chat ids: " + ", ".join(str(x) for x in sorted(allowlisted)))
        else:
            click.echo("Allowlisted chat ids: none (all chats accepted).")
        click.echo(
            "Shared memory mode: "
            + ("enabled (thread telegram:global)" if shared_memory else "disabled (per-chat thread ids, recommended)")
        )
        click.echo(
            "Memory retrieval policy: " + ("thread episodic + global facts" if all_memories else "thread episodic only")
        )
        click.echo("Profile memory: " + ("enabled" if profile_memory else "disabled"))
        click.echo("Session persistence: " + (str(session_store) if session_store is not None else "disabled"))

        try:
            run_telegram_polling(
                config,
                token=token_value,
                tools=tools_registry,
                memory=memory,
                model_name=selected_model,
                allowed_chat_ids=allowlisted or None,
                sessions_path=session_store,
                shared_memory=shared_memory,
                memory_retrieval_scope="thread",
                include_global_memory=all_memories,
                include_profile_memory=profile_memory,
            )
        except RuntimeError as e:
            click.echo(str(e), err=True)
            sys.exit(1)
        finally:
            if memory is not None:
                try:
                    memory.close()
                except Exception as e:
                    logger.debug("Failed to close memory engine after telegram stop: %s", e)

    if "telegram" not in cli.commands:
        cli.add_command(telegram)

