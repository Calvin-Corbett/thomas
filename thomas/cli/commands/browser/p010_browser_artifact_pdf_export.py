from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

try:
    import typer
except ImportError:  # pragma: no cover
    typer = None  # type: ignore[assignment]

from thomas.browser.p010_browser_artifact_pdf_export import (
    BrowserArtifactPdfExportError,
    BrowserArtifactPdfExportRequest,
    export_browser_artifact_to_pdf,
)

_COMMAND_NAME = "artifact-pdf-export"


def _emit_json(payload: dict[str, object]) -> None:
    # Deterministic JSON for automation (stable key order, no extra whitespace).
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _emit_human_error(*, code: str, message: str) -> None:
    print(f"Error [{code}]: {message}", file=sys.stderr)


def _run_export(
    *,
    artifact_ref: str,
    output: str | None,
    overwrite: bool,
    page_size: str,
    artifacts_root: str | None,
    output_format: str,
    include_images_in_zip: bool,
) -> dict[str, object]:
    req = BrowserArtifactPdfExportRequest(
        artifact_ref=artifact_ref,
        output_path=output,
        overwrite=overwrite,
        page_size=page_size,
        artifacts_root=artifacts_root,
        output_format=output_format,
        include_images_in_zip=include_images_in_zip,
    )
    result = export_browser_artifact_to_pdf(req)
    return {"ok": True, **result.to_dict()}


def _run_cli_common(
    *,
    artifact_ref: str,
    output: str | None,
    overwrite: bool,
    page_size: str,
    artifacts_root: str | None,
    output_format: str,
    include_images_in_zip: bool,
    json_output: bool,
) -> int:
    try:
        payload = _run_export(
            artifact_ref=artifact_ref,
            output=output,
            overwrite=overwrite,
            page_size=page_size,
            artifacts_root=artifacts_root,
            output_format=output_format,
            include_images_in_zip=include_images_in_zip,
        )
    except BrowserArtifactPdfExportError as e:
        if json_output:
            _emit_json({"ok": False, "error": e.to_dict()})
        else:
            _emit_human_error(code=e.code, message=str(e))
        return e.exit_code
    except Exception as e:  # noqa: BLE001
        if json_output:
            _emit_json({"ok": False, "error": {"code": "UNHANDLED_ERROR", "message": str(e)}})
        else:
            _emit_human_error(code="UNHANDLED_ERROR", message=str(e))
        return 1

    if json_output:
        _emit_json(payload)
    else:
        out_path = payload.get("output_path")
        fmt = payload.get("output_format")
        pages = payload.get("pages")
        print(f"Wrote {fmt}: {out_path} ({pages} pages)")
    return 0


# --- Typer integration (preferred if the Thomas CLI is Typer-based) -------------------------------

_browser_app = None
if typer is not None:
    try:
        import thomas.cli.commands.browser as browser_cmds  # type: ignore

        for attr in ("app", "browser_app", "browser", "cli", "typer_app"):
            candidate = getattr(browser_cmds, attr, None)
            if candidate is not None:
                _browser_app = candidate
                break
    except ImportError:
        _browser_app = None

if typer is not None and _browser_app is not None:

    @_browser_app.command(_COMMAND_NAME)
    def artifact_pdf_export(  # noqa: D401
        artifact_ref: str = typer.Argument(..., help="Artifact id or filesystem path."),
        output: Path | None = typer.Option(None, "--output", "-o", help="Output .pdf or .zip path."),
        overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite output if it exists."),
        page_size: str = typer.Option("letter", "--page-size", help="letter | a4 | auto"),
        artifacts_root: Path | None = typer.Option(
            None,
            "--artifacts-root",
            help="Artifacts root used to resolve artifact ids.",
        ),
        output_format: str = typer.Option(
            "auto",
            "--format",
            help="auto | pdf | zip (auto infers from --output extension).",
        ),
        zip_output: bool = typer.Option(
            False,
            "--zip",
            help="Shortcut for --format zip.",
        ),
        include_images_in_zip: bool = typer.Option(
            False,
            "--include-images",
            help="When producing a ZIP bundle, include original images under images/.",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit machine-readable JSON output.",
        ),
    ) -> None:
        if zip_output:
            output_format = "zip"
        exit_code = _run_cli_common(
            artifact_ref=artifact_ref,
            output=str(output) if output is not None else None,
            overwrite=overwrite,
            page_size=page_size,
            artifacts_root=str(artifacts_root) if artifacts_root is not None else None,
            output_format=output_format,
            include_images_in_zip=include_images_in_zip,
            json_output=json_output,
        )
        raise typer.Exit(code=exit_code)


# --- Argparse integration (fallback) --------------------------------------------------------------


def _add_common_argparse_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("artifact_ref", help="Artifact id or filesystem path.")
    parser.add_argument("--output", "-o", default=None, help="Output .pdf or .zip path.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite output if it exists.")
    parser.add_argument("--page-size", default="letter", help="letter | a4 | auto")
    parser.add_argument("--artifacts-root", default=None, help="Artifacts root for resolving ids.")
    parser.add_argument("--format", default="auto", help="auto | pdf | zip")
    parser.add_argument("--zip", dest="zip_output", action="store_true", help="Shortcut for --format zip")
    parser.add_argument(
        "--include-images",
        dest="include_images_in_zip",
        action="store_true",
        help="When producing a ZIP bundle, include original images under images/.",
    )
    parser.add_argument("--json", dest="json_output", action="store_true", help="JSON output.")


def register(subparsers: argparse._SubParsersAction) -> None:
    """
    Register the command with an argparse-based CLI.

    This is a no-op unless the Thomas CLI uses argparse and calls command-module `register()` hooks.
    """
    parser = subparsers.add_parser(
        _COMMAND_NAME,
        help="Export a browser artifact (screenshots) to a multi-page PDF or a ZIP bundle.",
    )
    _add_common_argparse_args(parser)
    parser.set_defaults(func=_run_argparse)


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    # Alias used by some command discovery patterns.
    register(subparsers)


def _run_argparse(args: argparse.Namespace) -> int:
    output_format = "zip" if getattr(args, "zip_output", False) else args.format
    return _run_cli_common(
        artifact_ref=args.artifact_ref,
        output=args.output,
        overwrite=args.overwrite,
        page_size=args.page_size,
        artifacts_root=args.artifacts_root,
        output_format=output_format,
        include_images_in_zip=bool(getattr(args, "include_images_in_zip", False)),
        json_output=bool(args.json_output),
    )


def _build_standalone_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_COMMAND_NAME,
        description="Export a browser artifact to a multi-page PDF or ZIP bundle.",
    )
    _add_common_argparse_args(parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_standalone_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return _run_argparse(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
