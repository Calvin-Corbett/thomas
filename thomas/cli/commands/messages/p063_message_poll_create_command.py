"""CLI wrapper for creating a message poll.

This module maps CLI args/flags to the core implementation in
`thomas.messages.p063_message_poll_create_command`.

We intentionally expose multiple conventional symbols (`COMMAND`, `CLI_COMMAND`,
`command`, `get_command`) because different Thomas CLI loaders may look for
different hooks.
"""

from __future__ import annotations

import json
from typing import Any, Mapping
import click

from thomas.messages.p063_message_poll_create_command import (
    MessagePollCreateInput,
    MessagePollCreateCommandError,
    run as run_poll_create,
)


CLI_COMMAND_PATH = ("message", "poll", "create")


_EXIT_BY_CODE: Mapping[str, int] = {
    "invalid_input": 2,
    "missing_config": 3,
    "external_failure": 4,
    "internal_error": 1,
}


def _emit_json(payload: dict[str, Any]) -> None:
    click.echo(json.dumps(payload, sort_keys=True))


def _parse_metadata(metadata_json: str | None) -> dict[str, Any] | None:
    if not metadata_json:
        return None
    try:
        obj = json.loads(metadata_json)
    except Exception:
        raise click.ClickException("metadata must be valid JSON")
    if not isinstance(obj, dict):
        raise click.ClickException("metadata must be a JSON object")
    return obj


def build_command() -> click.Command:
    @click.command("create")
    @click.argument("question", required=False)
    @click.argument("options", nargs=-1, required=False)
    @click.option("--question", "question_opt", type=str, help="Poll question (if not passed as an argument).")
    @click.option("--option", "option_opt", multiple=True, type=str, help="Poll option (repeatable).")
    @click.option("--options", "options_csv", type=str, help="Comma-separated poll options (supplemental).")
    @click.option("--channel", "--provider", "channel", type=str, default=None, help="Provider/adapter id.")
    @click.option("--target", "--to", "target", type=str, default=None, help="Destination identifier.")
    @click.option("--allow-multiple/--single", default=False, help="Allow multiple selections.")
    @click.option("--anonymous/--not-anonymous", default=False, help="Anonymous voting (if supported).")
    @click.option("--expires-in", "expires_in_seconds", type=int, default=None, help="Expiration in seconds.")
    @click.option("--duration-seconds", type=int, default=None, help="Alias for --expires-in (seconds).")
    @click.option("--duration-hours", type=int, default=None, help="Expiration in hours (converted to seconds).")
    @click.option("--idempotency-key", type=str, default=None, help="Stable key for idempotent creation.")
    @click.option("--send", is_flag=True, help="Deliver the poll via webhook.")
    @click.option("--webhook-url", type=str, default=None, help="Webhook URL to deliver the poll.")
    @click.option("--base-url", type=str, default=None, help="Base URL to generate a vote link.")
    @click.option("--metadata", "metadata_json", type=str, default=None, help="Extra metadata JSON object.")
    @click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
    def _cmd(
        question: str | None,
        options: tuple[str, ...],
        question_opt: str | None,
        option_opt: tuple[str, ...],
        options_csv: str | None,
        channel: str | None,
        target: str | None,
        allow_multiple: bool,
        anonymous: bool,
        expires_in_seconds: int | None,
        duration_seconds: int | None,
        duration_hours: int | None,
        idempotency_key: str | None,
        send: bool,
        webhook_url: str | None,
        base_url: str | None,
        metadata_json: str | None,
        as_json: bool,
    ) -> None:
        q = question_opt if question_opt is not None else question
        all_opts = list(options)
        all_opts.extend(option_opt)
        if options_csv:
            all_opts.extend([seg.strip() for seg in options_csv.split(",") if seg.strip()])

        expires: int | None = expires_in_seconds
        if expires is None and duration_seconds is not None:
            expires = duration_seconds
        if expires is None and duration_hours is not None:
            expires = int(duration_hours) * 3600

        metadata = _parse_metadata(metadata_json)

        inp = MessagePollCreateInput(
            question=q or "",
            options=tuple(all_opts),
            channel=channel,
            target=target,
            allow_multiple=bool(allow_multiple),
            anonymous=bool(anonymous),
            expires_in_seconds=expires,
            idempotency_key=idempotency_key,
            send=bool(send),
            webhook_url=webhook_url,
            base_url=base_url,
            metadata=metadata,
        )

        try:
            out = run_poll_create(inp)
        except MessagePollCreateCommandError as exc:
            if as_json:
                _emit_json({"ok": False, "error": exc.to_dict()})
                raise SystemExit(_EXIT_BY_CODE.get(exc.code, 1))
            raise click.ClickException(f"{exc.code}: {exc.message}")

        if as_json:
            _emit_json({"ok": True, "poll": out.to_dict()})
            return

        click.echo(f"Created poll {out.poll_id}")
        click.echo(out.message_text)
        click.echo(f"Delivered: {'yes' if out.sent else 'no'}")

    return _cmd


COMMAND = build_command()
CLI_COMMAND = COMMAND
command = COMMAND


def get_command() -> click.Command:
    return COMMAND
