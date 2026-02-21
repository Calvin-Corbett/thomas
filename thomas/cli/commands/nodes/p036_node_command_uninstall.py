"""CLI command: nodes command uninstall.

This module is designed to be discovered by Thomas' CLI command registry.

It provides:
- argparse parser registration hooks
- a stable run() function
- machine-readable output via --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable, Sequence


def _load_core() -> Any:
    """Import the core implementation lazily."""

    from thomas.nodes.p036_node_command_uninstall import (  # type: ignore
        NodeCommandUninstallError,
        NodeCommandUninstallRequest,
        uninstall_node_command,
        NODE_COMMAND_UNINSTALL_REQUEST_SCHEMA,
        NODE_COMMAND_UNINSTALL_RESULT_SCHEMA,
    )

    return (
        NodeCommandUninstallError,
        NodeCommandUninstallRequest,
        uninstall_node_command,
        NODE_COMMAND_UNINSTALL_REQUEST_SCHEMA,
        NODE_COMMAND_UNINSTALL_RESULT_SCHEMA,
    )


@dataclass(frozen=True, slots=True)
class NodeCommandUninstallCliArgs:
    package: str
    project_dir: str
    global_install: bool
    dry_run: bool
    npm_executable: str
    timeout_s: int | None
    json_output: bool


def build_parser(subparsers: argparse._SubParsersAction | None = None) -> argparse.ArgumentParser:
    """Build an argparse parser for this command.

    If `subparsers` is provided, the parser will be registered as a subcommand
    called "uninstall".
    """

    if subparsers is None:
        parser = argparse.ArgumentParser(prog="thomas nodes command uninstall")
    else:
        parser = subparsers.add_parser(
            "uninstall",
            help="Uninstall an npm package (global or project).",
            description="Uninstall an npm package (global or project).",
        )

    parser.add_argument("package", help="npm package spec to uninstall (single package only)")
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory (searched upward for package.json) (default: .)",
    )
    parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Uninstall from the global npm prefix",
    )
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run (no changes made)")
    parser.add_argument(
        "--npm",
        dest="npm_executable",
        default="npm",
        help="npm executable name or path (default: npm)",
    )
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=300,
        help="Timeout in seconds for npm (default: 300). Use 0 to disable.",
    )
    parser.add_argument("--json", dest="json_output", action="store_true", help="Emit machine-readable JSON")

    # Common pattern in argparse-based registries: stash a handler callable.
    parser.set_defaults(_thomas_handler=_run_from_namespace)
    return parser


def _namespace_to_args(ns: argparse.Namespace) -> NodeCommandUninstallCliArgs:
    timeout_s = ns.timeout_s
    if timeout_s is not None and timeout_s <= 0:
        timeout_s = None

    return NodeCommandUninstallCliArgs(
        package=ns.package,
        project_dir=ns.project_dir,
        global_install=bool(getattr(ns, "global_install", False)),
        dry_run=bool(getattr(ns, "dry_run", False)),
        npm_executable=str(getattr(ns, "npm_executable", "npm")),
        timeout_s=timeout_s,
        json_output=bool(getattr(ns, "json_output", False)),
    )


def _run_from_namespace(ns: argparse.Namespace) -> int:
    return run(_namespace_to_args(ns))


def run(args: NodeCommandUninstallCliArgs) -> int:
    """Run the uninstall command and print output.

    Returns a shell-style exit code.
    """

    (
        NodeCommandUninstallError,
        NodeCommandUninstallRequest,
        uninstall_node_command,
        _in_schema,
        _out_schema,
    ) = _load_core()

    try:
        req = NodeCommandUninstallRequest(
            package=args.package,
            project_dir=args.project_dir,
            global_install=args.global_install,
            dry_run=args.dry_run,
            npm_executable=args.npm_executable,
            timeout_s=args.timeout_s,
        )
        result = uninstall_node_command(req)
    except NodeCommandUninstallError as e:
        if args.json_output:
            sys.stdout.write(json.dumps({"ok": False, "error": e.to_dict()}, sort_keys=True) + "\n")
        else:
            sys.stderr.write(f"Error ({e.code}): {e.message}\n")
        return 1

    if args.json_output:
        sys.stdout.write(json.dumps({"ok": True, "result": result.to_dict()}, sort_keys=True) + "\n")
    else:
        scope = "global" if result.global_install else f"project={result.project_dir}"
        sys.stdout.write(f"Uninstalled {result.package} ({scope})\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Standalone entrypoint."""

    parser = build_parser(None)
    ns = parser.parse_args(list(argv) if argv is not None else None)
    return _run_from_namespace(ns)


# -----------------------
# Plugin-style metadata
# -----------------------

COMMAND_NAME = "nodes command uninstall"
COMMAND_ALIASES = ["node command uninstall", "nodes uninstall"]
PROMPT_ID = "P036"


def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    return build_parser(subparsers)


# Additional aliases for differing registries.
add_parser: Callable[[argparse._SubParsersAction], argparse.ArgumentParser] = register
cli_register: Callable[[argparse._SubParsersAction], argparse.ArgumentParser] = register


def get_command() -> dict[str, Any]:
    return {
        "name": COMMAND_NAME,
        "aliases": list(COMMAND_ALIASES),
        "help": "Uninstall an npm package (global or project).",
        "register": register,
        "run": run,
        "prompt_id": PROMPT_ID,
    }


COMMAND = get_command()


def get_schemas() -> dict[str, Any]:
    """Expose JSON schemas for automation / routes."""

    (
        _NodeCommandUninstallError,
        _NodeCommandUninstallRequest,
        _uninstall_node_command,
        in_schema,
        out_schema,
    ) = _load_core()

    return {"input": in_schema, "output": out_schema}


SCHEMAS = get_schemas()
