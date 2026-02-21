from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from thomas.plugins.p100_plugin_discovery_scanner import (
    PluginDiscoveryScanRequest,
    PluginDiscoveryScannerError,
    scan_plugins,
)


COMMAND_NAME = "p100-plugin-discovery-scanner"
COMMAND_HELP = "Scan for Thomas plugin candidates (filesystem + Python entry points)."


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register this command with an argparse subparser collection."""
    parser = subparsers.add_parser(COMMAND_NAME, help=COMMAND_HELP, description=COMMAND_HELP)
    _add_arguments(parser)
    parser.set_defaults(_handler=_handle_parsed_args)
    return parser


def register(target: Any) -> Any:
    """Best-effort registration hook.

    Supports:
      - argparse subparsers (duck-typed by having add_parser)
      - Typer apps (duck-typed by having command)
    """
    if hasattr(target, "add_parser"):
        return build_parser(target)

    # Typer registration (if the host CLI uses Typer)
    if hasattr(target, "command"):
        try:
            import typer
        except Exception:  # pragma: no cover
            return target

        @target.command(COMMAND_NAME, help=COMMAND_HELP)  # type: ignore[misc]
        def _cmd(
            path: list[str] = typer.Option(  # noqa: B008
                None,
                "--path",
                "--search-path",
                help="Directory to scan for plugins. May be provided multiple times.",
            ),
            config: str | None = typer.Option(None, "--config", help="Config file path."),
            no_entry_points: bool = typer.Option(False, "--no-entry-points", help="Disable entry point scanning."),
            entry_point_group: str = typer.Option("thomas.plugins", "--entry-point-group", help="Entry point group."),
            do_import: bool = typer.Option(False, "--import", help="Attempt to import discovered plugins."),
            recursive: bool = typer.Option(False, "--recursive", help="Recursively scan directories."),
            strict: bool = typer.Option(False, "--strict", help="Fail if any plugin has issues."),
            json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
        ) -> None:
            argv: list[str] = []
            for p in path or []:
                argv.extend(["--path", str(p)])
            if config is not None:
                argv.extend(["--config", str(config)])
            if no_entry_points:
                argv.append("--no-entry-points")
            argv.extend(["--entry-point-group", entry_point_group])
            if do_import:
                argv.append("--import")
            if recursive:
                argv.append("--recursive")
            if strict:
                argv.append("--strict")
            if json_output:
                argv.append("--json")
            raise typer.Exit(code=run(argv))

        return target

    return target


def run(argv: Sequence[str] | None = None) -> int:
    """Standalone CLI entry point (useful for unit tests)."""
    parser = argparse.ArgumentParser(prog=COMMAND_NAME, description=COMMAND_HELP)
    _add_arguments(parser)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return _handle_parsed_args(args)


def _add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--path",
        "--search-path",
        dest="search_paths",
        action="append",
        default=None,
        help="Directory to scan for plugins. May be provided multiple times.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Config file path (toml/json/pyproject.toml). Used when --path is not provided.",
    )
    parser.add_argument(
        "--no-entry-points",
        dest="include_entry_points",
        action="store_false",
        help="Disable scanning Python entry points.",
    )
    parser.add_argument(
        "--entry-point-group",
        dest="entry_point_group",
        default="thomas.plugins",
        help="Entry point group to scan (default: thomas.plugins).",
    )
    parser.add_argument(
        "--import",
        dest="import_plugins",
        action="store_true",
        help="Attempt to import discovered plugins to validate loadability.",
    )
    parser.add_argument(
        "--recursive",
        dest="recursive",
        action="store_true",
        help="Recursively scan directories for plugin candidates.",
    )
    parser.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        help="Exit non-zero if any discovered plugin has issues (syntax/import errors).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )


def _handle_parsed_args(args: argparse.Namespace) -> int:
    try:
        req = PluginDiscoveryScanRequest(
            search_paths=args.search_paths,
            config_path=args.config_path,
            include_entry_points=bool(getattr(args, "include_entry_points", True)),
            entry_point_group=str(getattr(args, "entry_point_group", "thomas.plugins")),
            import_plugins=bool(getattr(args, "import_plugins", False)),
            recursive=bool(getattr(args, "recursive", False)),
        )
        result = scan_plugins(req)

        has_issues = any(not p.ok() for p in result.plugins)
        strict = bool(getattr(args, "strict", False))
        ok = not (strict and has_issues)

        if bool(getattr(args, "json_output", False)):
            if ok:
                payload = {"ok": True, "result": result.to_dict()}
                _print_json(payload, stream=sys.stdout)
                return 0

            payload = {
                "ok": False,
                "error": {
                    "code": "plugin_load_failure",
                    "message": "One or more plugins reported issues.",
                    "details": {
                        "issue_count": sum(len(p.issues) for p in result.plugins),
                        "plugins_with_issues": [p.to_dict() for p in result.plugins if not p.ok()],
                    },
                },
            }
            _print_json(payload, stream=sys.stdout)
            return 3

        # Human output mode
        _print_human(result, stream=sys.stdout)
        if strict and has_issues:
            return 3
        return 0

    except PluginDiscoveryScannerError as e:
        if bool(getattr(args, "json_output", False)):
            _print_json({"ok": False, "error": e.to_dict()}, stream=sys.stdout)
        else:
            sys.stderr.write(f"{e.code}: {e.message}\n")
        return _exit_code_for_error(e.code)
    except Exception as e:  # pragma: no cover
        if bool(getattr(args, "json_output", False)):
            _print_json({"ok": False, "error": {"code": "unexpected_error", "message": str(e)}}, stream=sys.stdout)
        else:
            sys.stderr.write(f"unexpected_error: {e}\n")
        return 4


def _exit_code_for_error(code: str) -> int:
    mapping = {
        "invalid_request": 2,
        "missing_config": 2,
        "invalid_config": 2,
        "path_not_found": 2,
        "path_not_directory": 2,
    }
    return mapping.get(code, 2)


def _print_json(payload: dict[str, Any], *, stream: Any) -> None:
    stream.write(json.dumps(payload, indent=2, sort_keys=True))
    stream.write("\n")


def _print_human(result: Any, *, stream: Any) -> None:
    ok_count = sum(1 for p in result.plugins if p.ok())
    bad_count = len(result.plugins) - ok_count
    stream.write(f"Scanned {len(result.scanned_paths)} path(s). Found {len(result.plugins)} plugin candidate(s).\n")
    if bad_count:
        stream.write(f"{bad_count} plugin(s) reported issues.\n")
    for p in result.plugins:
        status = "OK" if p.ok() else "ISSUES"
        loc = p.file_path or p.module or "<unknown>"
        stream.write(f"- {p.name} [{p.source}] {status} :: {loc}\n")
        for issue in p.issues:
            stream.write(f"    - {issue.code}: {issue.message}\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
