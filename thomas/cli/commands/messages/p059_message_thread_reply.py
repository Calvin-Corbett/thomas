"""thomas.cli.commands.messages.p059_message_thread_reply

CLI command: reply inside an existing message thread.

This module is designed to be discoverable by the Thomas parity CLI registry.
It supports:
- human output (default)
- machine output via --json

It is intentionally Thomas-native and avoids OpenClaw naming reuse.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PARITY_ID = "p059_message_thread_reply"
COMMAND_NAME = "thread-reply"
COMMAND_HELP = "Reply within an existing message thread"


def _load_impl():
    """Import the implementation.

    In normal repo usage, the import path works.
    In some isolated test harnesses, we fall back to loading by relative path.
    """

    try:
        from thomas.messages.p059_message_thread_reply import (  # type: ignore
            MessageThreadReplyConfigError,
            MessageThreadReplyError,
            MessageThreadReplyExternalError,
            MessageThreadReplyInputError,
            MessageThreadReplyRequest,
            message_thread_reply,
        )

        return (
            MessageThreadReplyRequest,
            MessageThreadReplyError,
            MessageThreadReplyInputError,
            MessageThreadReplyConfigError,
            MessageThreadReplyExternalError,
            message_thread_reply,
        )
    except ImportError:
        this_file = Path(__file__).resolve()
        repo_root = this_file.parents[4]
        impl_path = repo_root / "thomas" / "messages" / "p059_message_thread_reply.py"
        if not impl_path.exists():
            raise

        import importlib.util

        spec = importlib.util.spec_from_file_location("_p059_message_thread_reply_impl", impl_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load implementation module from {impl_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        return (
            mod.MessageThreadReplyRequest,
            mod.MessageThreadReplyError,
            mod.MessageThreadReplyInputError,
            mod.MessageThreadReplyConfigError,
            mod.MessageThreadReplyExternalError,
            mod.message_thread_reply,
        )


def build_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--thread-id", required=True, help="Identifier of the thread/root message")
    parser.add_argument("--text", required=True, help="Reply text")
    parser.add_argument("--channel-id", default=None, help="Channel/conversation id (provider-specific)")
    parser.add_argument(
        "--provider",
        default=None,
        choices=["slack_webhook", "slack_web_api"],
        help="Force a specific provider/transport",
    )
    parser.add_argument(
        "--provider-payload-json",
        default=None,
        help="Provider-specific payload JSON object (e.g., '{\"reply_broadcast\": true}')",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    return parser


def add_parser(subparsers: Any) -> argparse.ArgumentParser:
    """Registry hook (argparse-style) used by the parity command loader."""

    parser = subparsers.add_parser(COMMAND_NAME, help=COMMAND_HELP, description=COMMAND_HELP)
    build_parser(parser)
    parser.set_defaults(_thomas_handler=run_from_args)
    return parser


def _parse_provider_payload(raw: str | None) -> Mapping[str, Any]:
    if raw is None:
        return {}
    try:
        payload = json.loads(raw)
    except Exception as e:
        raise ValueError("provider-payload-json must be valid JSON") from e

    if not isinstance(payload, dict):
        raise ValueError("provider-payload-json must be a JSON object")
    return payload


def _render_success(result: Any) -> str:
    if hasattr(result, "to_dict"):
        payload = {"ok": True, "result": result.to_dict()}  # type: ignore[no-untyped-call]
    else:
        payload = {"ok": True, "result": result}
    return json.dumps(payload, sort_keys=True)


def _render_error(err: Exception) -> str:
    if hasattr(err, "to_dict"):
        payload = {"ok": False, "error": err.to_dict()}  # type: ignore[no-untyped-call]
    elif hasattr(err, "code") and hasattr(err, "message") and hasattr(err, "details"):
        payload = {
            "ok": False,
            "error": {
                "code": err.code,
                "message": err.message,
                "details": err.details,
            },
        }
    else:
        payload = {"ok": False, "error": {"code": "error", "message": str(err), "details": {}}}
    return json.dumps(payload, sort_keys=True)


def _exit_code_for_error(err: Exception) -> int:
    (
        _Req,
        _Base,
        InputError,
        ConfigError,
        ExternalError,
        _fn,
    ) = _load_impl()

    if isinstance(err, InputError):
        return 2
    if isinstance(err, ConfigError):
        return 3
    if isinstance(err, ExternalError):
        return 4
    if isinstance(err, _Base):
        return 2
    return 1


def run_from_args(args: argparse.Namespace) -> int:
    (
        MessageThreadReplyRequest,
        _MessageThreadReplyError,
        _MessageThreadReplyInputError,
        _MessageThreadReplyConfigError,
        _MessageThreadReplyExternalError,
        message_thread_reply,
    ) = _load_impl()

    try:
        provider_payload = _parse_provider_payload(getattr(args, "provider_payload_json", None))
        req = MessageThreadReplyRequest(
            thread_id=args.thread_id,
            text=args.text,
            channel_id=args.channel_id,
            provider=args.provider,
            provider_payload=provider_payload,
        )
        result = message_thread_reply(req)
    except Exception as e:
        if getattr(args, "json", False):
            print(_render_error(e))
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        return _exit_code_for_error(e)

    if getattr(args, "json", False):
        print(_render_success(result))
    else:
        msg_id = getattr(result, "message_id", None)
        provider = getattr(result, "provider", "unknown")
        suffix = f" (message_id={msg_id})" if msg_id else ""
        print(f"Replied in thread {args.thread_id} via {provider}{suffix}")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thomas messages thread-reply", description=COMMAND_HELP)
    build_parser(parser)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_from_args(args)


# ---- Optional Typer integration ----
try:  # pragma: no cover
    import typer  # type: ignore

    app = typer.Typer(help=COMMAND_HELP, add_completion=False)

    @app.command(name=COMMAND_NAME)
    def _typer_cmd(
        thread_id: str = typer.Option(..., "--thread-id", help="Identifier of the thread/root message"),
        text: str = typer.Option(..., "--text", help="Reply text"),
        channel_id: str | None = typer.Option(None, "--channel-id", help="Channel/conversation id (provider-specific)"),
        provider: str | None = typer.Option(None, "--provider", help="Force a specific provider/transport"),
        provider_payload_json: str | None = typer.Option(
            None,
            "--provider-payload-json",
            help="Provider-specific payload JSON object",
        ),
        json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output"),
    ) -> None:
        args = argparse.Namespace(
            thread_id=thread_id,
            text=text,
            channel_id=channel_id,
            provider=provider,
            provider_payload_json=provider_payload_json,
            json=json_out,
        )
        code = run_from_args(args)
        raise typer.Exit(code=code)

except Exception:  # REVIEWED: broad catch:  # pragma: no cover
    app = None  # type: ignore


# ---- Compatibility aliases for various registries ----
cli_main = main
run = main
register = add_parser
register_command = add_parser


# Some registries like a dict-shaped spec.
COMMAND_SPEC: Mapping[str, Any] = {
    "id": PARITY_ID,
    "name": COMMAND_NAME,
    "help": COMMAND_HELP,
    "add_parser": add_parser,
    "run": run_from_args,
}


__all__ = [
    "PARITY_ID",
    "COMMAND_NAME",
    "COMMAND_HELP",
    "COMMAND_SPEC",
    "build_parser",
    "add_parser",
    "run_from_args",
    "main",
    "app",
]
