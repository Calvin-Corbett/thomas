"""CLI command: plugins list (P121, runtime-backed).

Thin CLI wrapper around:
  thomas.plugins.p121_plugin_list_command_runtime_backed.list_plugins_runtime_backed

Supports:
  - human output (default)
  - machine output (--json)
  - JSON schema output (--schema)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from collections.abc import Iterable, Sequence

from thomas.plugins.p121_plugin_list_command_runtime_backed import (
    PLUGIN_LIST_JSON_SCHEMA,
    PluginListError,
    PluginListRequest,
    PluginListResult,
    failure_payload,
    list_plugins_runtime_backed,
)


@dataclass(frozen=True, slots=True)
class PluginListCliArgs:
    json: bool = False
    schema: bool = False
    config: Path | None = None
    plugins_dir: Path | None = None
    only_enabled: bool = False


def build_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout.")
    parser.add_argument("--schema", action="store_true", help="Emit the JSON schema for --json and exit.")
    parser.add_argument("--config", type=Path, default=None, help="Override config path.")
    parser.add_argument("--plugins-dir", type=Path, default=None, help="Override plugins directory.")
    parser.add_argument("--only-enabled", action="store_true", help="Only include enabled plugins in output.")
    return parser


def run_from_args(args: PluginListCliArgs, *, out: TextIO, err: TextIO) -> int:
    if args.schema:
        json.dump(PLUGIN_LIST_JSON_SCHEMA, out, indent=2, sort_keys=True)
        out.write("\n")
        return 0

    req = PluginListRequest(
        config_path=args.config,
        plugins_dir=args.plugins_dir,
        include_disabled=not args.only_enabled,
    )

    try:
        result = list_plugins_runtime_backed(req)
    except PluginListError as exc:
        if args.json:
            json.dump(failure_payload(exc), out, indent=2, sort_keys=True)
            out.write("\n")
        else:
            err.write(f"ERROR: {exc}\n")
        return 1

    if args.json:
        json.dump(result.to_json(), out, indent=2, sort_keys=True)
        out.write("\n")
        return 0

    _print_human(result, out)
    return 0


def run(argv: Sequence[str] | None = None, *, out: TextIO | None = None, err: TextIO | None = None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = argparse.ArgumentParser(prog="thomas plugins list", add_help=True)
    build_parser(parser)
    ns = parser.parse_args(list(argv) if argv is not None else None)
    cli_args = PluginListCliArgs(
        json=bool(getattr(ns, "json", False)),
        schema=bool(getattr(ns, "schema", False)),
        config=getattr(ns, "config", None),
        plugins_dir=getattr(ns, "plugins_dir", None),
        only_enabled=bool(getattr(ns, "only_enabled", False)),
    )
    return run_from_args(cli_args, out=out, err=err)


# Argparse integration hook used by some Thomas CLI assemblies.
def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:  # noqa: SLF001
    parser = subparsers.add_parser(
        "list",
        help="List configured plugins (runtime-backed).",
        description="Lists plugins from config + installed payloads on disk.",
    )
    build_parser(parser)
    parser.set_defaults(_thomas_handler=_argparse_handler)
    return parser


def _argparse_handler(ns: argparse.Namespace) -> int:
    cli_args = PluginListCliArgs(
        json=bool(getattr(ns, "json", False)),
        schema=bool(getattr(ns, "schema", False)),
        config=getattr(ns, "config", None),
        plugins_dir=getattr(ns, "plugins_dir", None),
        only_enabled=bool(getattr(ns, "only_enabled", False)),
    )
    return run_from_args(cli_args, out=sys.stdout, err=sys.stderr)


def _print_human(result: PluginListResult, out: TextIO) -> None:
    plugins = list(result.plugins)
    if not plugins:
        out.write("No plugins found.\n")
        return

    headers = ["ID", "ENABLED", "INSTALLED", "STATUS", "VERSION", "SOURCE"]
    rows: list[list[str]] = []
    for p in plugins:
        rows.append(
            [
                p.plugin_id,
                "yes" if p.enabled else "no",
                "yes" if p.installed else "no",
                p.status,
                p.version or "-",
                p.source or "-",
            ]
        )

    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells: Iterable[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    out.write(fmt_row(headers) + "\n")
    out.write(fmt_row(["-" * w for w in widths]) + "\n")
    for r in rows:
        out.write(fmt_row(r) + "\n")

    ok = sum(1 for p in plugins if p.status == "ok")
    missing = sum(1 for p in plugins if p.status == "missing")
    errc = sum(1 for p in plugins if p.status == "error")
    out.write(f"\nSummary: {len(plugins)} total, {ok} ok, {missing} missing, {errc} error\n")

    errors = [p for p in plugins if p.error]
    if errors:
        out.write("\nErrors:\n")
        for p in errors:
            out.write(f"- {p.plugin_id}: {p.error}\n")

