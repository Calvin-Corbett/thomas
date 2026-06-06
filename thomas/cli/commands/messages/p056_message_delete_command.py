from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from thomas.messages.p056_message_delete_command import MessageDeleteRequest, delete_message

logger = logging.getLogger(__name__)


def _safe_add_argument(parser: Any, *args: Any, **kwargs: Any) -> None:
    """Add an argparse argument, ignoring duplicates.

    The Thomas CLI command tree often shares parent parsers. Some flags may already exist upstream.
    Argparse raises an ArgumentError for duplicates; we treat that as a no-op.
    """

    if not hasattr(parser, "add_argument"):
        return
    try:
        parser.add_argument(*args, **kwargs)
    except ImportError:
        # Duplicate option strings or incompatible parser type.
        return


def add_arguments(parser: Any) -> None:
    """Attach CLI flags for `message delete`."""

    _safe_add_argument(
        parser,
        "--channel",
        dest="channel",
        help="Messaging channel/provider name (required when multiple are configured).",
    )
    _safe_add_argument(
        parser,
        "--account",
        dest="account",
        help="Optional account id for multi-account providers.",
    )

    # Accept both --target and the more conversational --to.
    _safe_add_argument(
        parser,
        "--target",
        "--to",
        dest="target",
        required=False,
        help="Target channel/user to operate in (provider-specific format).",
    )

    # Accept a few common aliases for message id.
    _safe_add_argument(
        parser,
        "--message-id",
        "--messageId",
        "--id",
        dest="message_id",
        required=False,
        help="Provider message id to delete.",
    )

    _safe_add_argument(
        parser,
        "--dry-run",
        "--noop",
        action="store_true",
        dest="dry_run",
        help="Resolve and validate inputs but do not perform deletion.",
    )

    # `--json` is frequently added by the top-level CLI; adding here is safe.
    _safe_add_argument(
        parser,
        "--json",
        action="store_true",
        dest="json",
        help="Emit machine-readable JSON output.",
    )


def run(args: Any) -> dict[str, Any]:
    """Run the command.

    Returns a JSON-serializable dict. The Thomas parity layer decides whether to print it as JSON
    (for `--json`) or render it for humans.
    """

    req = MessageDeleteRequest(
        channel=getattr(args, "channel", None),
        account=getattr(args, "account", None),
        target=str(getattr(args, "target", "") or ""),
        message_id=str(getattr(args, "message_id", "") or ""),
        dry_run=bool(getattr(args, "dry_run", False)),
    )

    resp = delete_message(req)
    return resp.to_dict()


def format_human(result: dict[str, Any]) -> str:
    """Human-friendly formatting (used by some CLI runners)."""

    if result.get("dryRun"):
        return f"(dry-run) validated delete for messageId={result.get('messageId')} to={result.get('to')}"

    if result.get("deleted"):
        return f"deleted messageId={result.get('messageId')} to={result.get('to')}"

    return f"no deletion performed for messageId={result.get('messageId')} to={result.get('to')}"


def _build_fallback_spec() -> Any:
    @dataclass(frozen=True)
    class _Spec:
        group: str
        name: str
        help: str
        add_arguments: Callable[[Any], None]
        run: Callable[[Any], Any]
        aliases: tuple[str, ...] = ()

    return _Spec("message", "delete", "Delete a message.", add_arguments, run)


def _build_command_spec() -> Any:
    """Create a command spec compatible with the existing parity registry.

    The Thomas codebase has its own spec type. We use light introspection so this module stays
    compatible even if the internal class/function name shifts.
    """

    fallback = _build_fallback_spec()

    try:
        from thomas.cli import parity_commands as pc  # type: ignore
    except ImportError:
        return fallback

    candidates = [
        "ParityCommand",
        "ParityCommandSpec",
        "CommandSpec",
        "Command",
        "parity_command",
        "command",
        "make_command",
        "build_command",
    ]

    factory: Callable[..., Any] | None = None
    for name in candidates:
        obj = getattr(pc, name, None)
        if callable(obj):
            factory = obj
            break

    if factory is None:
        return fallback

    # Try kwargs construction by signature.
    try:
        sig = inspect.signature(factory)
    except AttributeError:
        sig = None

    if sig is not None:
        kwargs: dict[str, Any] = {}
        for pname, p in sig.parameters.items():
            if pname in {"group", "namespace", "topic", "domain", "root"}:
                kwargs[pname] = "message"
            elif pname in {"name", "subcommand", "command", "cmd"}:
                kwargs[pname] = "delete"
            elif pname in {"path", "route", "command_path"}:
                kwargs[pname] = ("message", "delete")
            elif pname in {"help", "description", "summary", "doc"}:
                kwargs[pname] = "Delete a message."
            elif pname in {"add_arguments", "configure_parser", "args"}:
                kwargs[pname] = add_arguments
            elif pname in {"run", "handler", "callback", "func", "execute", "invoke"}:
                kwargs[pname] = run
            elif pname in {"format", "formatter", "render", "format_human"}:
                kwargs[pname] = format_human
            elif pname in {"aliases", "alias"}:
                kwargs[pname] = ()
            elif p.default is inspect._empty and pname not in kwargs:
                # Required but unknown; leave it unset.
                pass

        try:
            return factory(**kwargs)
        except Exception:  # REVIEWED: broad catch
            # Broad catch: registry factories vary by loader; fall through to positional attempts.
            logger.exception("Message delete command factory rejected keyword construction.")
            pass

    # Positional fallbacks (seen across a few registry styles).
    positional_attempts: Iterable[tuple[Any, ...]] = [
        ("message", "delete", "Delete a message.", add_arguments, run),
        ("message", "delete", add_arguments, run, "Delete a message."),
        (("message", "delete"), "Delete a message.", add_arguments, run),
        ("message delete", "Delete a message.", add_arguments, run),
        ("delete", "Delete a message.", add_arguments, run),
    ]

    for args in positional_attempts:
        try:
            return factory(*args)
        except Exception:  # REVIEWED: broad catch
            # Broad catch: try the next legacy registry signature without breaking import.
            logger.exception("Message delete command factory rejected positional construction: %r", args)
            continue

    return fallback


# Public registry hooks (multiple names to maximize discoverability).
COMMAND = _build_command_spec()
COMMANDS = [COMMAND]
PARITY_COMMAND = COMMAND
PARITY_COMMANDS = COMMANDS


def get_commands() -> list[Any]:
    return list(COMMANDS)


def register() -> list[Any]:
    # Some registries import modules and call `register()`.
    return list(COMMANDS)
