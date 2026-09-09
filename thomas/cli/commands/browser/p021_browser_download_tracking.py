"""Browser download tracking CLI command.

This command is intentionally automation-friendly:
- `--json` emits a single JSON object (success or failure)
- `--schema` prints a JSON schema-like description for automation
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import typer

from thomas.browser.p021_browser_download_tracking import (
    DownloadTrackingError,
    DownloadTrackingInput,
    track_download,
)

_REGISTERED_APP_IDS: set[int] = set()


def _output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "result": {
                "type": "object",
                "required": ["file_path", "file_name", "bytes", "sha256", "detected_at", "duration_s"],
                "properties": {
                    "file_path": {"type": "string"},
                    "file_name": {"type": "string"},
                    "bytes": {"type": "integer"},
                    "sha256": {"type": "string"},
                    "detected_at": {"type": "number"},
                    "duration_s": {"type": "number"},
                },
            },
            "error": {
                "type": "object",
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        },
    }


def _emit_json(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _run(
    *,
    download_dir: Path | None,
    timeout_s: float,
    poll_interval_s: float,
    stable_checks: int,
    json_output: bool,
) -> None:
    try:
        result = track_download(
            DownloadTrackingInput(
                download_dir=download_dir,
                timeout_s=timeout_s,
                poll_interval_s=poll_interval_s,
                stable_checks=stable_checks,
            )
        )
    except DownloadTrackingError as exc:
        if json_output:
            _emit_json({"ok": False, "error": {"code": exc.code, "message": exc.message}})
        else:
            typer.secho(f"Error: {exc.code}: {exc.message}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc

    if json_output:
        _emit_json({"ok": True, "result": result.to_dict()})
    else:
        typer.echo(f"Download detected: {result.file_path} ({result.bytes} bytes)")


def register(browser_app: typer.Typer) -> None:
    """Register the browser download tracking command on a browser Typer app."""

    if id(browser_app) in _REGISTERED_APP_IDS:
        return
    _REGISTERED_APP_IDS.add(id(browser_app))

    @browser_app.command(name="download-tracking")
    def download_tracking(
        download_dir: Path | None = typer.Option(
            None,
            "--download-dir",
            help=(
                "Directory to watch for downloads. If omitted, uses THOMAS_BROWSER_DOWNLOAD_DIR/THOMAS_DOWNLOAD_DIR."
            ),
        ),
        timeout_s: float = typer.Option(30.0, "--timeout", min=0.01, help="Seconds to wait for a completed download."),
        poll_interval_s: float = typer.Option(0.1, "--poll", min=0.01, help="Polling interval in seconds."),
        stable_checks: int = typer.Option(
            2, "--stable-checks", min=1, help="Consecutive stable checks before accepting the file."
        ),
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
        schema: bool = typer.Option(False, "--schema", help="Print JSON schema for --json output and exit."),
    ) -> None:
        """Wait for the next completed download in a directory."""

        if schema:
            _emit_json(_output_schema())
            raise typer.Exit(code=0)

        _run(
            download_dir=download_dir,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
            stable_checks=stable_checks,
            json_output=json_output,
        )


# Some Thomas CLI setups discover modules by importing them for side effects. If the
# browser command package exposes a Typer app (commonly named `app`), try to
# register automatically, but never fail import if we can't.
def _autoregister() -> None:  # pragma: no cover
    try:
        import thomas.cli.commands.browser as browser_pkg  # type: ignore
    except ImportError:
        return

    for attr in ("app", "browser_app"):
        maybe = getattr(browser_pkg, attr, None)
        if isinstance(maybe, typer.Typer):
            try:
                register(maybe)
            except ImportError:
                # Avoid hard failures during import; explicit registration (if used)
                # will surface issues deterministically.
                return
            return


_autoregister()


def _build_standalone_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="download-tracking",
        description="Wait for the next completed download in a directory.",
    )
    parser.add_argument(
        "--download-dir",
        default=None,
        help="Directory to watch. Falls back to THOMAS_BROWSER_DOWNLOAD_DIR/THOMAS_DOWNLOAD_DIR.",
    )
    parser.add_argument("--timeout", dest="timeout_s", type=float, default=30.0)
    parser.add_argument("--poll", dest="poll_interval_s", type=float, default=0.1)
    parser.add_argument("--stable-checks", dest="stable_checks", type=int, default=2)
    parser.add_argument("--json", dest="json_output", action="store_true")
    parser.add_argument("--schema", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_standalone_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if bool(args.schema):
        _emit_json(_output_schema())
        return 0

    try:
        _run(
            download_dir=Path(args.download_dir) if args.download_dir else None,
            timeout_s=float(args.timeout_s),
            poll_interval_s=float(args.poll_interval_s),
            stable_checks=int(args.stable_checks),
            json_output=bool(args.json_output),
        )
    except typer.Exit as exc:
        return int(getattr(exc, "exit_code", 1) or 0)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
