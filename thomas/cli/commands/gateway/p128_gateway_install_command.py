from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from thomas.server.routes.gateway.p128_gateway_install_command import (
    GatewayInstallCommandError,
    GatewayInstallCommandRequest,
    GatewayInstallCommandResult,
    install_gateway_artifact,
)


@dataclass(frozen=True, slots=True)
class GatewayInstallCliResult:
    ok: bool
    result: Optional[GatewayInstallCommandResult] = None
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        if self.ok and self.result is not None:
            return {"ok": True, "result": dataclasses.asdict(self.result)}
        return {"ok": False, "error": self.error or {"message": "unknown error"}}


def run_gateway_install(
    *,
    source: str,
    name: Optional[str] = None,
    install_dir: Optional[str] = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> GatewayInstallCliResult:
    try:
        req = GatewayInstallCommandRequest(
            source=source,
            name=name,
            install_dir=install_dir,
            overwrite=overwrite,
            dry_run=dry_run,
        )
        res = install_gateway_artifact(req, app=None)
        return GatewayInstallCliResult(ok=True, result=res)
    except GatewayInstallCommandError as exc:
        # Mirror the server error envelope for determinism.
        return GatewayInstallCliResult(ok=False, error=exc.to_error_payload()["error"])


def render_cli_output(cli_result: GatewayInstallCliResult, *, as_json: bool) -> str:
    if as_json:
        return json.dumps(cli_result.to_dict(), sort_keys=True)

    if cli_result.ok and cli_result.result is not None:
        r = cli_result.result
        status = "DRY-RUN" if r.dry_run else "OK"
        lines = [
            f"[{status}] Installed gateway artifact: {r.name}",
            f"Path: {r.installed_path}",
        ]
        if r.actions:
            lines.append("Actions:")
            lines.extend([f"  - {a}" for a in r.actions])
        return "\n".join(lines)

    err = cli_result.error or {"message": "unknown error", "code": "unknown"}
    code = err.get("code", "unknown")
    msg = err.get("message", "unknown error")
    return f"[ERROR:{code}] {msg}"


def build_arg_parser(subparsers: Optional[argparse._SubParsersAction] = None) -> argparse.ArgumentParser:
    """Build an argparse parser for integration with Thomas' CLI."""

    if subparsers is None:
        parser = argparse.ArgumentParser(prog="thomas-gateway-install")
    else:
        parser = subparsers.add_parser("install", help="Install a gateway artifact (P128).")

    parser.add_argument("source", help="Path to a plugin directory or .zip archive.")
    parser.add_argument("--name", default=None, help="Optional install name. Defaults to source basename.")
    parser.add_argument(
        "--install-dir",
        default=None,
        help="Destination directory for gateway artifacts. If omitted, config/env must provide it.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite if destination exists.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and plan actions without writing files.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    parser.set_defaults(_thomas_entrypoint=main)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    cli_result = run_gateway_install(
        source=args.source,
        name=args.name,
        install_dir=args.install_dir,
        overwrite=bool(args.overwrite),
        dry_run=bool(args.dry_run),
    )

    output = render_cli_output(cli_result, as_json=bool(args.json))
    stream = sys.stdout if cli_result.ok else sys.stderr
    stream.write(output + "\n")
    return 0 if cli_result.ok else 2


# Compatibility shims for potential Thomas command loaders
COMMAND_ID = "p128_gateway_install_command"
COMMAND_NAME = "gateway_install"
