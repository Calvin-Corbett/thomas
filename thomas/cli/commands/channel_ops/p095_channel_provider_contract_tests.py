"""CLI: channel provider contract tests (P095).

This command is intentionally provider-focused and automation-friendly.

Features:
- Human output (default)
- Machine-readable output via --json
- JSON schema output via --schema
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from thomas.channels.p095_channel_provider_contract_tests import (
    ProviderContractTestRequest,
    report_json_schema,
    run_channel_provider_contract_tests,
)


def _parse_config_blob(config_blob: str | None) -> dict[str, Any] | None:
    """Parse a config payload.

    Accepted formats:
    - None / empty
    - Inline JSON object
    - Path to a JSON file containing an object
    """

    if not config_blob:
        return None

    raw = config_blob.strip()
    if not raw:
        return None

    if raw.startswith("{") or raw.startswith("["):
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("--config JSON must be an object")

    path = Path(raw)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {raw}")

    parsed = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(parsed, dict):
        return parsed
    raise ValueError("Config file JSON must be an object")


def _merge_telegram_overrides(
    base: dict[str, Any] | None,
    *,
    token: str | None,
    chat_id: str | None,
) -> dict[str, Any] | None:
    if base is None and token is None and chat_id is None:
        return None

    merged: dict[str, Any] = dict(base or {})
    if token is not None:
        merged["token"] = token
    if chat_id is not None:
        merged["chat_id"] = chat_id
    return merged


def _format_human(report: dict[str, Any]) -> str:
    lines: list[str] = []
    provider = report.get("provider")
    ok = report.get("ok")
    lines.append(f"Provider: {provider}")
    lines.append(f"Overall: {'OK' if ok else 'FAIL'}")

    checks = report.get("checks") or []
    if checks:
        lines.append("Checks:")
        for chk in checks:
            status = "OK" if chk.get("ok") else "FAIL"
            msg = chk.get("message")
            tail = f" - {msg}" if msg else ""
            lines.append(f"  - {chk.get('name')}: {status}{tail}")

    errors = report.get("errors") or []
    if errors:
        lines.append("Errors:")
        for err in errors:
            lines.append(f"  - {err.get('code')}: {err.get('message')}")
    return "\n".join(lines) + "\n"


# ----------------------------- click registration ----------------------------


def _build_click_command():
    try:
        import click
    except ImportError:  # pragma: no cover
        return None

    @click.command(
        name="provider-contract-tests",
        help="Run contract tests for a channel provider (default: telegram).",
    )
    @click.option("--provider", type=str, default="telegram", show_default=True)
    @click.option(
        "--config",
        "config_blob",
        type=str,
        default=None,
        help="Inline JSON object or a path to a JSON file containing provider config.",
    )
    @click.option("--token", "telegram_token", type=str, default=None, help="Telegram bot token override.")
    @click.option("--chat-id", "telegram_chat_id", type=str, default=None, help="Telegram chat id override.")
    @click.option(
        "--external/--no-external",
        "run_external",
        default=False,
        show_default=True,
        help="Run an optional external health check (read-only when possible).",
    )
    @click.option(
        "--timeout",
        "timeout_seconds",
        type=float,
        default=5.0,
        show_default=True,
        help="Timeout (seconds) for external checks.",
    )
    @click.option("--json", "json_mode", is_flag=True, default=False, help="Emit machine-readable JSON.")
    @click.option("--schema", "schema_mode", is_flag=True, default=False, help="Emit the JSON schema.")
    def _cmd(
        provider: str,
        config_blob: str | None,
        telegram_token: str | None,
        telegram_chat_id: str | None,
        run_external: bool,
        timeout_seconds: float,
        json_mode: bool,
        schema_mode: bool,
    ) -> None:
        if schema_mode:
            click.echo(json.dumps(report_json_schema(), sort_keys=True))
            raise click.exceptions.Exit(0)

        try:
            parsed = _parse_config_blob(config_blob)
        except Exception as exc:
            payload = {
                "provider": (provider or ""),
                "ok": False,
                "checks": [],
                "errors": [{"code": "invalid_request", "message": str(exc), "details": {"field": "config"}}],
            }
            if json_mode:
                click.echo(json.dumps(payload, sort_keys=True))
            else:
                click.echo(_format_human(payload), err=True)
            raise click.exceptions.Exit(1)

        merged = _merge_telegram_overrides(parsed, token=telegram_token, chat_id=telegram_chat_id)

        report = run_channel_provider_contract_tests(
            ProviderContractTestRequest(
                provider=provider,
                config=merged,
                run_external=run_external,
                timeout_seconds=timeout_seconds,
            )
        ).to_dict()

        if json_mode:
            click.echo(json.dumps(report, sort_keys=True))
        else:
            click.echo(_format_human(report))

        raise click.exceptions.Exit(0 if report.get("ok") else 1)

    return _cmd


COMMAND = _build_click_command()

# Compatibility with a range of command discovery patterns.
cli = COMMAND
COMMANDS = [COMMAND] if COMMAND is not None else []
NAME = "provider-contract-tests"


# ---------------------------- argparse registration --------------------------


def _register_argparse(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        NAME,
        help="Run contract tests for a channel provider (default: telegram).",
    )
    parser.add_argument("--provider", default="telegram")
    parser.add_argument(
        "--config",
        dest="config_blob",
        default=None,
        help="Inline JSON object or a path to a JSON file containing provider config.",
    )
    parser.add_argument("--token", dest="telegram_token", default=None)
    parser.add_argument("--chat-id", dest="telegram_chat_id", default=None)
    parser.add_argument("--external", dest="run_external", action="store_true")
    parser.add_argument("--timeout", dest="timeout_seconds", type=float, default=5.0)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parser.add_argument("--schema", dest="schema_mode", action="store_true")
    parser.set_defaults(func=_handle_argparse)


def _handle_argparse(args: argparse.Namespace) -> int:
    if getattr(args, "schema_mode", False):
        sys.stdout.write(json.dumps(report_json_schema(), sort_keys=True) + "\n")
        return 0

    try:
        parsed = _parse_config_blob(getattr(args, "config_blob", None))
    except Exception as exc:
        payload = {
            "provider": (getattr(args, "provider", "") or ""),
            "ok": False,
            "checks": [],
            "errors": [{"code": "invalid_request", "message": str(exc), "details": {"field": "config"}}],
        }
        if getattr(args, "json_mode", False):
            sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        else:
            sys.stderr.write(_format_human(payload))
        return 1

    merged = _merge_telegram_overrides(
        parsed,
        token=getattr(args, "telegram_token", None),
        chat_id=getattr(args, "telegram_chat_id", None),
    )

    report = run_channel_provider_contract_tests(
        ProviderContractTestRequest(
            provider=getattr(args, "provider", "telegram"),
            config=merged,
            run_external=bool(getattr(args, "run_external", False)),
            timeout_seconds=float(getattr(args, "timeout_seconds", 5.0)),
        )
    ).to_dict()

    if getattr(args, "json_mode", False):
        sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    else:
        sys.stdout.write(_format_human(report))

    return 0 if report.get("ok") else 1


def register(parent: Any) -> None:
    """Register this command under the channels CLI.

    Supports both click (Group.add_command) and argparse (subparsers.add_parser).
    """

    if parent is None:
        return

    # click-style registration
    if COMMAND is not None and hasattr(parent, "add_command"):
        try:
            parent.add_command(COMMAND)  # type: ignore[attr-defined]
            return
        except (OSError, FileNotFoundError):
            pass

    # argparse-style registration
    if hasattr(parent, "add_parser"):
        _register_argparse(parent)
        return

    raise TypeError(f"Unsupported CLI parent for registration: {type(parent).__name__}")


# Aliases that some loaders may look for.
def add_to_cli(parent: Any) -> None:
    register(parent)


def add_command(parent: Any) -> None:
    register(parent)


def get_command():
    return COMMAND


def get_commands():
    return COMMANDS


__all__ = [
    "COMMAND",
    "COMMANDS",
    "NAME",
    "cli",
    "register",
    "add_to_cli",
    "add_command",
    "get_command",
    "get_commands",
]
