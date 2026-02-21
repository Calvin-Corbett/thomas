"""CLI command: browser upload helper (P022).

This command stages a local file into a browser-accessible directory and prints
either a human-friendly message or JSON (with --json) for automation.

The implementation is intentionally small and relies only on stdlib + the helper
module in `thomas.browser.p022_browser_upload_helper`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from thomas.browser.p022_browser_upload_helper import (
    BROWSER_UPLOAD_ERROR_JSON_SCHEMA,
    BROWSER_UPLOAD_RESULT_JSON_SCHEMA,
    BrowserUploadHelperError,
    BrowserUploadInvalidInputError,
    BrowserUploadRequest,
    make_failure_payload,
    make_success_payload,
    stage_file_for_browser,
)

COMMAND_NAME = "upload"
HELP = "Stage a local file into a browser-accessible upload directory."

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_INVALID_USAGE = 2

# A tiny metadata object that some CLI dispatchers prefer.
COMMAND: dict[str, Any] = {
    "name": COMMAND_NAME,
    "help": HELP,
}


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=HELP)
    _add_parser_arguments(parser)
    return parser


def _add_parser_arguments(parser: argparse.ArgumentParser) -> None:
    # Optional so `--schema` can be invoked without requiring a file path.
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to the local file to stage for upload.",
    )
    parser.add_argument(
        "--dest",
        dest="destination_dir",
        default=None,
        help="Destination directory for staging. If omitted, uses THOMAS_BROWSER_UPLOAD_DIR.",
    )
    parser.add_argument(
        "--name",
        dest="destination_name",
        default=None,
        help="Override the staged filename (defaults to source filename).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite if the destination file already exists.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        help="Refuse to stage files larger than this size in bytes.",
    )
    parser.add_argument(
        "--fsync",
        action="store_true",
        help="fsync the staged file before returning (slower but safer on flaky disks).",
    )
    parser.add_argument(
        "--no-sha256",
        action="store_true",
        help="Skip sha256 computation.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout.",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the JSON schema for the --json output and exit.",
    )


def _schema_payload() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "result": BROWSER_UPLOAD_RESULT_JSON_SCHEMA,
            "error": BROWSER_UPLOAD_ERROR_JSON_SCHEMA,
        },
    }


def _emit_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")


def run_from_args(args: argparse.Namespace) -> int:
    if getattr(args, "schema", False):
        _emit_json(_schema_payload())
        return EXIT_SUCCESS

    if not getattr(args, "source", None):
        err = BrowserUploadInvalidInputError(
            "missing_source",
            "Source file argument is required.",
        )
        if args.json:
            _emit_json(make_failure_payload(err))
        else:
            sys.stderr.write(f"ERROR[{err.code}]: {err.message}\n")
        return EXIT_INVALID_USAGE

    req = BrowserUploadRequest(
        source_path=Path(args.source),
        destination_dir=Path(args.destination_dir) if args.destination_dir else None,
        destination_name=args.destination_name,
        overwrite=bool(args.overwrite),
        make_parents=True,
        max_bytes=args.max_bytes,
        compute_sha256=not bool(args.no_sha256),
        fsync=bool(getattr(args, "fsync", False)),
    )

    try:
        result = stage_file_for_browser(req)
    except BrowserUploadHelperError as e:
        if args.json:
            _emit_json(make_failure_payload(e))
        else:
            sys.stderr.write(f"ERROR[{e.code}]: {e.message}\n")
        return EXIT_FAILURE

    if args.json:
        _emit_json(make_success_payload(result))
    else:
        sys.stdout.write(f"Staged: {result.source_path} -> {result.staged_path}\n")

    return EXIT_SUCCESS


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register this command under an argparse subparser collection."""
    parser = subparsers.add_parser(COMMAND_NAME, help=HELP, description=HELP)
    _add_parser_arguments(parser)
    parser.set_defaults(func=run_from_args)


# Aliases that improve compatibility with a few different dispatcher styles.
add_parser = register
run = run_from_args


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser(prog="thomas browser upload")
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_from_args(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
