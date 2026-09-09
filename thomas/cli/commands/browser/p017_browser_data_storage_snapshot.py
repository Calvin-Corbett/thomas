from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import typer

from thomas.browser.p017_browser_data_storage_snapshot import (
    TOOL_INPUT_SCHEMA,
    TOOL_OUTPUT_SCHEMA,
    BrowserDataStorageSnapshotError,
    BrowserDataStorageSnapshotRequest,
    browser_data_storage_snapshot,
)

COMMAND_NAME = "data-storage-snapshot"


def _register(app: typer.Typer) -> None:
    # Idempotent registration: avoid duplicate command errors if discovery calls us multiple times.
    for cmd in getattr(app, "registered_commands", []):
        if getattr(cmd, "name", None) == COMMAND_NAME:
            return

    @app.command(COMMAND_NAME, help="Create a ZIP snapshot of the browser's persisted data storage directory.")
    def data_storage_snapshot(
        data_dir: Path | None = typer.Option(
            None,
            "--data-dir",
            help="Path to the browser data directory to snapshot. If omitted, Thomas will try to resolve it from config/env.",
        ),
        profile: str | None = typer.Option(
            None,
            "--profile",
            help="Optional browser profile name. Used when resolving the data dir from config/env.",
        ),
        output: Path | None = typer.Option(
            None,
            "--output",
            "-o",
            help="Output path for the snapshot .zip. Can be a directory.",
        ),
        overwrite: bool = typer.Option(
            False,
            "--overwrite",
            help="Overwrite the output file if it already exists.",
        ),
        compress_level: int = typer.Option(
            6,
            "--compress-level",
            help="ZIP deflate compression level (0-9). 0 = store, 6 = default balance, 9 = smallest.",
        ),
        strict: bool = typer.Option(
            True,
            "--strict/--no-strict",
            help="When strict, fail if any file cannot be read.",
        ),
        include_hash: bool = typer.Option(
            True,
            "--hash/--no-hash",
            help="Compute a SHA-256 hash for the resulting archive.",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit machine-readable JSON to stdout.",
        ),
        schema: bool = typer.Option(
            False,
            "--schema",
            help="Print this command's JSON input/output schema and exit.",
        ),
    ) -> None:
        exit_code = _run(
            data_dir=data_dir,
            profile=profile,
            output=output,
            overwrite=overwrite,
            compress_level=compress_level,
            strict=strict,
            include_hash=include_hash,
            json_output=json_output,
            schema=schema,
        )
        raise typer.Exit(code=exit_code)


def _run(
    *,
    data_dir: Path | None,
    profile: str | None,
    output: Path | None,
    overwrite: bool,
    compress_level: int,
    strict: bool,
    include_hash: bool,
    json_output: bool,
    schema: bool,
) -> int:
    if schema:
        payload = {"input_schema": TOOL_INPUT_SCHEMA, "output_schema": TOOL_OUTPUT_SCHEMA}
        sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
        return 0

    req = BrowserDataStorageSnapshotRequest(
        data_dir=data_dir,
        profile=profile,
        output_path=output,
        overwrite=overwrite,
        strict=strict,
        include_hash=include_hash,
        include_manifest=True,
        compress_level=compress_level,
    )

    try:
        result = browser_data_storage_snapshot(req)
    except BrowserDataStorageSnapshotError as e:
        if json_output:
            sys.stdout.write(json.dumps({"ok": False, "error": e.to_dict()}, sort_keys=True) + "\n")
        else:
            sys.stderr.write(f"Error [{e.code}]: {e.message}\n")
        return 1
    except Exception as e:  # pragma: no cover - defensive
        if json_output:
            sys.stdout.write(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "external_failure",
                            "message": "Unexpected failure while creating snapshot.",
                            "details": {"exception_type": type(e).__name__, "exception": str(e)},
                        },
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        else:
            sys.stderr.write(f"Error [external_failure]: {e}\n")
        return 1

    if json_output:
        sys.stdout.write(json.dumps(result.to_dict(), sort_keys=True) + "\n")
    else:
        sys.stdout.write(f"Snapshot written: {result.snapshot_path}\n")
        sys.stdout.write(f"Data dir:        {result.data_dir}\n")
        sys.stdout.write(f"Files included:  {result.file_count} (skipped {len(result.skipped_files)})\n")
        sys.stdout.write(f"Bytes written:   {result.bytes_written}\n")
        if result.sha256:
            sys.stdout.write(f"SHA-256:         {result.sha256}\n")

    return 0


def register(app: typer.Typer) -> None:
    """Registration hook for Typer-based CLI discovery."""
    _register(app)


# Aliases for alternate discovery conventions.
register_cli = register
register_command = register


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Registration hook for argparse-based CLI discovery.

    This is a best-effort compatibility layer; Typer-based CLIs should call `register()`.
    """
    parser = subparsers.add_parser(
        COMMAND_NAME,
        help="Create a ZIP snapshot of the browser's persisted data storage directory.",
    )
    parser.add_argument("--data-dir", dest="data_dir", default=None)
    parser.add_argument("--profile", dest="profile", default=None)
    parser.add_argument("--output", "-o", dest="output", default=None)
    parser.add_argument("--overwrite", dest="overwrite", action="store_true", default=False)
    parser.add_argument("--compress-level", dest="compress_level", default=6, type=int)
    parser.add_argument("--no-strict", dest="strict", action="store_false", default=True)
    parser.add_argument("--no-hash", dest="include_hash", action="store_false", default=True)
    parser.add_argument("--json", dest="json_output", action="store_true", default=False)
    parser.add_argument("--schema", dest="schema", action="store_true", default=False)
    parser.set_defaults(func=_run_from_argparse)
    return parser


def _run_from_argparse(args: argparse.Namespace) -> int:
    return _run(
        data_dir=Path(args.data_dir) if args.data_dir else None,
        profile=args.profile,
        output=Path(args.output) if args.output else None,
        overwrite=bool(args.overwrite),
        compress_level=int(args.compress_level),
        strict=bool(args.strict),
        include_hash=bool(args.include_hash),
        json_output=bool(args.json_output),
        schema=bool(args.schema),
    )


# Best-effort auto-registration for codebases that expose a package-level `app`.
try:  # pragma: no cover - import-time behavior depends on the wider Thomas CLI structure
    from . import app as _browser_app  # type: ignore
except ImportError:
    _browser_app = None  # type: ignore

if _browser_app is not None:
    try:
        _register(_browser_app)  # type: ignore[arg-type]
    except ImportError:
        # Never fail import due to CLI registration; discovery can call `register` explicitly.
        pass


def main(argv: Sequence[str] | None = None) -> int:
    """Pack-proxy runtime entrypoint."""
    parser = argparse.ArgumentParser(
        prog="browser data-storage-snapshot",
        description="Create a ZIP snapshot of browser data storage.",
    )
    parser.add_argument("--data-dir", dest="data_dir", default=None)
    parser.add_argument("--profile", dest="profile", default=None)
    parser.add_argument("--output", "-o", dest="output", default=None)
    parser.add_argument("--overwrite", dest="overwrite", action="store_true", default=False)
    parser.add_argument("--compress-level", dest="compress_level", default=6, type=int)
    parser.add_argument("--no-strict", dest="strict", action="store_false", default=True)
    parser.add_argument("--no-hash", dest="include_hash", action="store_false", default=True)
    parser.add_argument("--json", dest="json_output", action="store_true", default=False)
    parser.add_argument("--schema", dest="schema", action="store_true", default=False)
    try:
        args = parser.parse_args(list(argv or []))
    except SystemExit as exc:
        return int(exc.code or 0)
    return _run_from_argparse(args)
