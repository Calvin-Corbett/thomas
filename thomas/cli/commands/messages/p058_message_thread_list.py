"""CLI command for listing message threads (P058).

This module is intentionally defensive about integration points: it provides
common symbols used by multiple CLI loader patterns while remaining a valid
standalone Click command.

Machine-readable output is supported via --json.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping, MutableMapping
from typing import Any

import click

from thomas.messages.p058_message_thread_list import (
    MessageThreadListError,
    MessageThreadListRequest,
    list_message_threads,
)

PROMPT_ID = "p058"
DOMAIN = "messages"
ACTION = "message_thread_list"

# Extra aliases commonly used by parity loaders.
PARITY_PROMPT_ID = PROMPT_ID
PARITY_DOMAIN = DOMAIN
PARITY_NAME = ACTION
COMMAND_NAME = ACTION


@click.command(name="message-thread-list", help="List message threads.")
@click.option(
    "--channel-id",
    "channel_id",
    default=None,
    help="Only include threads from this channel.",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    show_default=True,
    help="Maximum number of threads to return.",
)
@click.option(
    "--cursor",
    default=None,
    help="Pagination cursor (backend-defined; for the JSONL backend this is an integer offset).",
)
@click.option(
    "--include-archived",
    is_flag=True,
    default=False,
    help="Include archived threads when supported by the backend.",
)
@click.option(
    "--store",
    "store_path",
    default=None,
    help="Optional local JSONL message store path (fallback backend).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON.",
)
def message_thread_list_cmd(
    channel_id: str | None,
    limit: int,
    cursor: str | None,
    include_archived: bool,
    store_path: str | None,
    as_json: bool,
) -> None:
    config: dict[str, Any] = {}
    if store_path is not None:
        config["message_store_path"] = store_path

    req = MessageThreadListRequest(
        channel_id=channel_id,
        limit=limit,
        cursor=cursor,
        include_archived=include_archived,
    )

    try:
        result = list_message_threads(req, config=config)
    except MessageThreadListError as exc:
        if as_json:
            click.echo(json.dumps({"ok": False, **exc.to_dict()}, sort_keys=True))
            raise SystemExit(1)
        raise click.ClickException(f"{exc.code}: {exc.message}") from exc

    if as_json:
        click.echo(json.dumps({"ok": True, **result.to_dict()}, sort_keys=True))
        return

    if not result.threads:
        click.echo("No threads found.")
        return

    # Human-friendly: tab-separated rows.
    for t in result.threads:
        last = t.last_message_at.isoformat() if t.last_message_at else ""
        title = t.title or ""
        channel = t.channel_id or ""
        participants = ",".join(t.participants)
        click.echo(f"{t.thread_id}	{channel}	{t.message_count}	{last}	{title}	{participants}".rstrip())


# Common integration hooks expected by various CLI loader patterns.
COMMAND = message_thread_list_cmd
CLI_COMMAND = COMMAND

PARITY_SPEC: Mapping[str, Any] = {
    "prompt": PROMPT_ID,
    "domain": DOMAIN,
    "name": ACTION,
    "command": COMMAND,
}


def get_command() -> click.Command:
    return COMMAND


_REGISTERED = False


def register_with_parity() -> None:
    """Best-effort registration with Thomas parity CLI.

    If the parity registry is unavailable (or uses a different API), this is a
    no-op.
    """

    global _REGISTERED
    if _REGISTERED:
        return

    try:
        from thomas.cli import parity_compat  # type: ignore
    except ImportError:
        return

    if _is_already_registered(parity_compat):
        _REGISTERED = True
        return

    spec: MutableMapping[str, Any] = dict(PARITY_SPEC)

    for fn_name in (
        "register_command",
        "register_parity_command",
        "register",
        "add_command",
    ):
        fn = getattr(parity_compat, fn_name, None)
        if not callable(fn):
            continue
        if _try_register_call(fn, spec):
            _REGISTERED = True
            return


def _is_already_registered(parity_compat: Any) -> bool:
    for attr_name in (
        "PARITY_COMMANDS",
        "COMMANDS",
        "REGISTRY",
        "COMMAND_REGISTRY",
    ):
        reg = getattr(parity_compat, attr_name, None)
        if isinstance(reg, Mapping):
            if ACTION in reg or PROMPT_ID in reg:
                return True
        if isinstance(reg, list):
            for item in reg:
                if isinstance(item, Mapping) and item.get("name") == ACTION:
                    return True
                if getattr(item, "name", None) == ACTION:
                    return True
    return False


def _try_register_call(fn: Any, spec: Mapping[str, Any]) -> bool:
    try:
        sig = inspect.signature(fn)
    except (subprocess.CalledProcessError, OSError):
        sig = None

    attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    attempts.append(((spec,), {}))
    attempts.append(((spec["command"],), {}))
    attempts.append(((spec["name"], spec["command"]), {}))
    attempts.append(((spec["prompt"], spec["command"]), {}))
    attempts.append(((), dict(spec)))

    for args, kwargs in attempts:
        try:
            if sig is not None and kwargs:
                if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    fn(*args, **kwargs)
                    return True
                if all(k in sig.parameters for k in kwargs.keys()):
                    fn(*args, **kwargs)
                    return True

            fn(*args, **kwargs)
            return True
        except TypeError:
            continue
        except (ValueError, TypeError):
            return False

    return False


# Side-effect registration for loader patterns that import modules for discovery.
register_with_parity()
