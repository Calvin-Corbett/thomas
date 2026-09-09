from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from thomas.server.routes.gateway.p125_gateway_ops_route_package_scaffold import (
    GatewayOpsRoutePackageScaffoldError,
    GatewayOpsRoutePackageScaffoldRequest,
    get_gateway_ops_route_package_scaffold_json_schema,
    scaffold_gateway_ops_route_package,
)

COMMAND_NAME = "gateway-ops-route-package-scaffold"
COMMAND_HELP = "Scaffold a gateway ops route package under thomas/server/routes/gateway/ops/."


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    p = parser or argparse.ArgumentParser(prog=COMMAND_NAME, description=COMMAND_HELP)
    p.add_argument(
        "package_name",
        help="Leaf Python package name to create under thomas/server/routes/gateway/ops/",
    )
    p.add_argument(
        "--project-root",
        dest="project_root",
        default=None,
        help="Filesystem path to the Thomas project root (defaults to THOMAS_PROJECT_ROOT).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute what would be created without writing to disk.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout.",
    )
    p.add_argument(
        "--schema",
        action="store_true",
        help="Print the JSON schema for this command and exit.",
    )
    return p


def _print_json(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if getattr(args, "schema", False):
        _print_json(get_gateway_ops_route_package_scaffold_json_schema())
        return 0

    req = GatewayOpsRoutePackageScaffoldRequest(
        package_name=args.package_name,
        project_root=args.project_root,
        dry_run=bool(args.dry_run),
    )

    try:
        result = scaffold_gateway_ops_route_package(req)
    except GatewayOpsRoutePackageScaffoldError as e:
        if args.json:
            _print_json({"ok": False, "error": e.to_dict()})
        else:
            sys.stdout.write(f"ERROR [{e.code}] {e.message}\n")
        return 2

    if args.json:
        _print_json({"ok": True, "result": result.to_dict()})
    else:
        sys.stdout.write(f"Created gateway ops route package: {result.package_dir}\n")
        if result.created_dirs:
            sys.stdout.write("Directories created:\n")
            for d in result.created_dirs:
                sys.stdout.write(f"  - {d}\n")
        if result.created_files:
            sys.stdout.write("Files created:\n")
            for f in result.created_files:
                sys.stdout.write(f"  - {f}\n")

    return 0


def register_subcommand(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Optional integration hook for CLIs that build argparse subcommands dynamically."""
    sub = subparsers.add_parser(COMMAND_NAME, help=COMMAND_HELP, description=COMMAND_HELP)
    build_parser(sub)
    sub.set_defaults(_thomas_cmd_main=main)
