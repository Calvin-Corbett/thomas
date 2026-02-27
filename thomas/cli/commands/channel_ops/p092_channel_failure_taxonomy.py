from __future__ import annotations

"""CLI hook for P092: channel failure taxonomy.

This module is designed to be imported/discovered by `thomas cli channels` and
register a `failure-taxonomy` subcommand.
"""

import json
from pathlib import Path
from typing import Any

from thomas.channels.p092_channel_failure_taxonomy import (
    ChannelFailureTaxonomyError,
    FailureTaxonomyRequest,
    InvalidTaxonomyInputError,
    build_failure_taxonomy_report,
    parse_event_json,
    taxonomy_schema,
)

COMMAND_NAME = "failure-taxonomy"
COMMAND = COMMAND_NAME
NAME = COMMAND_NAME
SUBCOMMAND = COMMAND_NAME
OPERATION_ID = "channel_failure_taxonomy"


def _load_event(*, event: str | None, event_file: Path | None) -> dict[str, Any] | None:
    if event is not None and event_file is not None:
        raise InvalidTaxonomyInputError(
            "Provide only one of --event or --event-file.",
            details={"provided": ["event", "event_file"]},
        )

    if event is not None:
        return dict(parse_event_json(event))

    if event_file is not None:
        raw = event_file.read_text(encoding="utf-8")
        return dict(parse_event_json(raw))

    return None


def _load_config(config: str | None) -> dict[str, Any] | None:
    if config is None:
        return None
    try:
        data = json.loads(config)
    except json.JSONDecodeError as e:
        raise InvalidTaxonomyInputError(
            "Invalid --config JSON.",
            details={"error": str(e)},
        ) from e
    if not isinstance(data, dict):
        raise InvalidTaxonomyInputError(
            "--config must be a JSON object.",
            details={"received_type": type(data).__name__},
        )
    return data


def _render_human(report: Any, *, echo: Any) -> None:
    # Keep output dependency-free and stable.
    echo("Channel failure taxonomy")
    if report.channel:
        echo(f"  Channel: {report.channel}")
    echo("")
    for entry in report.taxonomy:
        echo(f"- {entry.category.value}: {entry.title}")
        echo(f"    Severity: {entry.severity.value} | Retryable: {entry.retryable}")
        echo(f"    {entry.description}")
        echo(f"    Remediation: {entry.remediation}")
        echo("")
    if report.classification is not None:
        c = report.classification
        echo("Classification")
        echo(f"  Category: {c.category.value}")
        echo(f"  Severity: {c.severity.value} | Retryable: {c.retryable}")
        echo(f"  Rationale: {c.rationale}")


def _run(
    *,
    channel: str | None,
    event: str | None,
    event_file: Path | None,
    probe: bool,
    config: str | None,
    schema: bool,
    json_output: bool,
    echo: Any,
) -> None:
    if schema:
        echo(json.dumps(taxonomy_schema(), sort_keys=True))
        return

    try:
        event_obj = _load_event(event=event, event_file=event_file)
        config_obj = _load_config(config)
        report = build_failure_taxonomy_report(
            FailureTaxonomyRequest(channel=channel, event=event_obj, probe=probe, config=config_obj)
        )
    except ChannelFailureTaxonomyError as e:
        if json_output:
            echo(json.dumps(e.to_dict(), sort_keys=True))
        else:
            echo(f"Error: {e.error_code}: {e}")
        raise SystemExit(e.exit_code)
    except Exception as e:  # pragma: no cover
        wrapped = ChannelFailureTaxonomyError(
            "Unexpected error while building failure taxonomy report.",
            details={"exception_type": type(e).__name__},
        )
        if json_output:
            echo(json.dumps(wrapped.to_dict(), sort_keys=True))
        else:
            echo(f"Error: {wrapped.error_code}: {wrapped}")
        raise SystemExit(wrapped.exit_code)

    if json_output:
        echo(json.dumps(report.to_dict(), sort_keys=True))
    else:
        _render_human(report, echo=echo)


def register(parent: Any) -> None:
    """Register this operation with the parent `channels` command.

    Implemented defensively so it can be wired into either Typer or argparse
    style CLIs depending on how Thomas is configured.
    """
    # Typer-style group
    if hasattr(parent, "add_typer"):
        _register_typer(parent)
        return

    # argparse subparsers
    if hasattr(parent, "add_parser"):
        _register_argparse(parent)
        return

    # Unknown registry type: do nothing (discovery shouldn't explode).
    return


# Compatibility aliases for differing discovery conventions.
def register_command(app: Any) -> None:  # pragma: no cover
    register(app)


def register_commands(app: Any) -> None:  # pragma: no cover
    register(app)


def add_parser(subparsers: Any) -> None:  # pragma: no cover
    register(subparsers)


def add_subcommand(app: Any) -> None:  # pragma: no cover
    register(app)


def _register_typer(parent: Any) -> None:
    try:
        import typer
    except ImportError:  # pragma: no cover
        return

    app = typer.Typer(add_completion=False, help="Show channel failure taxonomy and optionally classify an event.")

    @app.callback(invoke_without_command=True)
    def failure_taxonomy(
        channel: str | None = typer.Option(None, "--channel", "-c", help="Channel identifier (e.g., telegram)."),
        event: str | None = typer.Option(None, "--event", help="Failure event as a JSON object string."),
        event_file: Path | None = typer.Option(
            None,
            "--event-file",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Read the event JSON from a file.",
        ),
        probe: bool = typer.Option(
            False,
            "--probe",
            help="Validate channel configuration (offline-safe by default).",
        ),
        config: str | None = typer.Option(
            None,
            "--config",
            help="Channel configuration as JSON (used with --probe).",
        ),
        schema: bool = typer.Option(
            False,
            "--schema",
            help="Emit the JSON schema for --json output.",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit machine-readable JSON.",
        ),
    ) -> None:
        _run(
            channel=channel,
            event=event,
            event_file=event_file,
            probe=probe,
            config=config,
            schema=schema,
            json_output=json_output,
            echo=typer.echo,
        )

    parent.add_typer(app, name=COMMAND_NAME)


def _register_argparse(subparsers: Any) -> None:  # pragma: no cover
    import argparse
    import sys

    parser = subparsers.add_parser(
        COMMAND_NAME,
        help="Show channel failure taxonomy and optionally classify an event.",
    )
    parser.add_argument("--channel", "-c", default=None, help="Channel identifier (e.g., telegram).")
    parser.add_argument("--event", default=None, help="Failure event as a JSON object string.")
    parser.add_argument("--event-file", default=None, help="Read the event JSON from a file.")
    parser.add_argument("--probe", action="store_true", help="Validate channel configuration (offline-safe).")
    parser.add_argument("--config", default=None, help="Channel configuration as JSON (used with --probe).")
    parser.add_argument("--schema", action="store_true", help="Emit the JSON schema for --json output.")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit machine-readable JSON.")

    def _echo(msg: str) -> None:
        sys.stdout.write(msg)
        if not msg.endswith("\n"):
            sys.stdout.write("\n")

    def _run_args(args: argparse.Namespace) -> None:
        _run(
            channel=args.channel,
            event=args.event,
            event_file=Path(args.event_file) if args.event_file else None,
            probe=args.probe,
            config=args.config,
            schema=args.schema,
            json_output=args.json_output,
            echo=_echo,
        )

    parser.set_defaults(func=_run_args)
