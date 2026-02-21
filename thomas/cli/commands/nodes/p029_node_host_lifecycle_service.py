"""CLI: node host lifecycle.

This command module provides lifecycle management for the *local* node host
"service".

Machine-readable output
-----------------------
All subcommands accept ``--json`` which prints a single JSON object to stdout.

Integration strategy
--------------------
The Thomas CLI codebase may use different command registration patterns
(argparse, Typer/click, or an internal registry).

To stay easy to integrate, this module exposes:

- ``register(subparsers)``: argparse-style registration hook.
- ``PARITY_COMMANDS``: declarative command descriptions (list of dicts).
- ``PARITY_COMMAND_SPECS``: same info as small objects (duck-typed).
- ``app``: optional Typer app (if Typer is installed).
- ``main(argv=None)``: standalone entrypoint (useful for tests).

"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

try:
    import typer  # type: ignore
except Exception:  # pragma: no cover
    typer = None  # type: ignore

from thomas.nodes.p029_node_host_lifecycle_service import (
    NodeHostActionResult,
    NodeHostInstallRequest,
    NodeHostLifecycleService,
    NodeHostServiceError,
)


# ---------------------------------------------------------------------------
# Parity/metadata descriptions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParityCommandSpec(Mapping[str, Any]):
    """Duck-typed command spec for parity tooling.

    Some parity tooling expects dict-like data, while other tooling expects
    objects with attributes.

    This tiny spec supports both (Mapping interface + attributes).
    """

    path: List[str]
    summary: str

    @property
    def command(self) -> str:
        return " ".join(self.path)

    def to_dict(self) -> Dict[str, Any]:
        # Include a few common key names to maximize compatibility with
        # different parity consumers.
        return {
            "path": list(self.path),
            "command": self.command,
            "summary": self.summary,
            "help": self.summary,
            "description": self.summary,
        }

    # Mapping protocol
    def __getitem__(self, key: str) -> Any:  # type: ignore[override]
        return self.to_dict()[key]

    def __iter__(self) -> Iterable[str]:  # type: ignore[override]
        return iter(self.to_dict())

    def __len__(self) -> int:  # type: ignore[override]
        return len(self.to_dict())


PARITY_COMMAND_SPECS: List[ParityCommandSpec] = [
    ParityCommandSpec(["nodes", "host", "install"], "Install the node host as a background service"),
    ParityCommandSpec(["nodes", "host", "status"], "Show node host service status"),
    ParityCommandSpec(["nodes", "host", "stop"], "Stop the node host service"),
    ParityCommandSpec(["nodes", "host", "restart"], "Restart the node host service"),
    ParityCommandSpec(["nodes", "host", "uninstall"], "Remove the node host service"),
]

# Many parity systems expect dicts.
PARITY_COMMANDS: List[Dict[str, Any]] = [spec.to_dict() for spec in PARITY_COMMAND_SPECS]

# Some codebases look for `COMMANDS`.
COMMANDS = PARITY_COMMANDS


# ---------------------------------------------------------------------------
# Shared output helpers
# ---------------------------------------------------------------------------


def _result_payload(result: NodeHostActionResult) -> Dict[str, Any]:
    return result.to_dict()


def _error_payload(action: str, err: NodeHostServiceError) -> Dict[str, Any]:
    return {"ok": False, "action": action, "error": err.to_dict()}


def _print_json(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _print_human(result: NodeHostActionResult) -> None:
    st = result.status
    sys.stdout.write(f"{result.message}\n")
    sys.stdout.write(
        f"installed={st.installed} running={st.running} runtime={st.runtime or 'unknown'}\n"
    )
    if st.gateway_host and st.gateway_port:
        sys.stdout.write(f"gateway={st.gateway_host}:{st.gateway_port} tls={bool(st.tls)}\n")
    if st.display_name:
        sys.stdout.write(f"display_name={st.display_name}\n")


def _run_action(
    action: str,
    *,
    json_mode: bool,
    install_req: Optional[NodeHostInstallRequest] = None,
) -> int:
    svc = NodeHostLifecycleService()

    try:
        if action == "install":
            if install_req is None:
                raise ValueError("install_req is required for install")
            result = svc.install(install_req)
        elif action == "status":
            st = svc.status()
            result = NodeHostActionResult(
                ok=True,
                action="status",
                status=st,
                message="Node host status",
            )
        elif action == "stop":
            result = svc.stop()
        elif action == "restart":
            result = svc.restart()
        elif action == "uninstall":
            result = svc.uninstall()
        else:
            sys.stderr.write(f"Unknown action: {action}\n")
            return 2

        if json_mode:
            _print_json(_result_payload(result))
        else:
            _print_human(result)
        return 0

    except NodeHostServiceError as e:
        if json_mode:
            _print_json(_error_payload(action, e))
        else:
            sys.stderr.write(f"Error ({e.code.value}): {e}\n")
        return 2


# ---------------------------------------------------------------------------
# Argparse implementation
# ---------------------------------------------------------------------------


def _build_host_parser(subparsers: Any) -> argparse.ArgumentParser:
    host_parser = subparsers.add_parser(
        "host",
        help="Manage the local node host service",
        description="Install, query, and control the local node host service.",
    )
    host_sub = host_parser.add_subparsers(dest="host_cmd", required=True)

    def add_json_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # install
    p_install = host_sub.add_parser("install", help="Install the node host service")
    add_json_flag(p_install)
    p_install.add_argument("--host", dest="gateway_host", default="127.0.0.1", help="Gateway host")
    p_install.add_argument("--port", dest="gateway_port", type=int, default=18789, help="Gateway port")
    p_install.add_argument("--tls", action="store_true", help="Use TLS for the gateway connection")
    p_install.add_argument(
        "--tls-fingerprint",
        dest="tls_fingerprint_sha256",
        default=None,
        help="Expected TLS certificate fingerprint (sha256 hex)",
    )
    p_install.add_argument("--node-id", dest="node_id", default=None, help="Override node id")
    p_install.add_argument(
        "--display-name", dest="display_name", default=None, help="Override display name"
    )
    p_install.add_argument(
        "--runtime",
        dest="runtime",
        default="python",
        help="Service runtime identifier (implementation-dependent)",
    )
    p_install.add_argument("--force", action="store_true", help="Overwrite existing installation")

    # status
    p_status = host_sub.add_parser("status", help="Show node host service status")
    add_json_flag(p_status)

    # stop
    p_stop = host_sub.add_parser("stop", help="Stop the node host service")
    add_json_flag(p_stop)

    # restart
    p_restart = host_sub.add_parser("restart", help="Restart the node host service")
    add_json_flag(p_restart)

    # uninstall
    p_uninstall = host_sub.add_parser("uninstall", help="Uninstall the node host service")
    add_json_flag(p_uninstall)

    return host_parser


def register(subparsers: Any) -> None:
    """Argparse registration hook.

    The parent CLI is expected to pass the *nodes* subparser action.
    """

    _build_host_parser(subparsers)


def build_parser() -> argparse.ArgumentParser:
    """Standalone parser for this module (useful for tests)."""

    parser = argparse.ArgumentParser(prog="thomas")
    sub = parser.add_subparsers(dest="cmd", required=True)

    nodes = sub.add_parser("nodes", help="Node operations")
    nodes_sub = nodes.add_subparsers(dest="nodes_cmd", required=True)

    register(nodes_sub)
    return parser


def _dispatch(args: argparse.Namespace) -> int:
    action = args.host_cmd
    if action == "install":
        req = NodeHostInstallRequest(
            gateway_host=args.gateway_host,
            gateway_port=args.gateway_port,
            tls=bool(args.tls),
            tls_fingerprint_sha256=args.tls_fingerprint_sha256,
            node_id=args.node_id,
            display_name=args.display_name,
            runtime=args.runtime,
            force=bool(args.force),
        )
        return _run_action("install", json_mode=bool(args.json), install_req=req)

    return _run_action(action, json_mode=bool(args.json))


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Standalone entrypoint.

    Returns an exit code.
    """

    parser = build_parser()
    ns = parser.parse_args(list(argv) if argv is not None else None)

    # Argparse should make these unreachable, but keep deterministic.
    if ns.cmd != "nodes" or ns.nodes_cmd != "host":
        sys.stderr.write("Invalid command path\n")
        return 2

    return _dispatch(ns)


# ---------------------------------------------------------------------------
# Typer implementation (optional)
# ---------------------------------------------------------------------------


if typer is not None:  # pragma: no cover
    app = typer.Typer(help="Manage the local node host service")

    @app.command("install")
    def typer_install(
        host: str = typer.Option("127.0.0.1", "--host", help="Gateway host"),
        port: int = typer.Option(18789, "--port", help="Gateway port"),
        tls: bool = typer.Option(False, "--tls", help="Use TLS for the gateway connection"),
        tls_fingerprint: Optional[str] = typer.Option(
            None, "--tls-fingerprint", help="TLS cert fingerprint"
        ),
        node_id: Optional[str] = typer.Option(None, "--node-id", help="Override node id"),
        display_name: Optional[str] = typer.Option(
            None, "--display-name", help="Override display name"
        ),
        runtime: str = typer.Option("python", "--runtime", help="Service runtime identifier"),
        force: bool = typer.Option(False, "--force", help="Overwrite existing installation"),
        json_out: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
    ) -> None:
        code = _run_action(
            "install",
            json_mode=json_out,
            install_req=NodeHostInstallRequest(
                gateway_host=host,
                gateway_port=port,
                tls=tls,
                tls_fingerprint_sha256=tls_fingerprint,
                node_id=node_id,
                display_name=display_name,
                runtime=runtime,
                force=force,
            ),
        )
        raise typer.Exit(code=code)

    @app.command("status")
    def typer_status(
        json_out: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
    ) -> None:
        raise typer.Exit(code=_run_action("status", json_mode=json_out))

    @app.command("stop")
    def typer_stop(
        json_out: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
    ) -> None:
        raise typer.Exit(code=_run_action("stop", json_mode=json_out))

    @app.command("restart")
    def typer_restart(
        json_out: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
    ) -> None:
        raise typer.Exit(code=_run_action("restart", json_mode=json_out))

    @app.command("uninstall")
    def typer_uninstall(
        json_out: bool = typer.Option(False, "--json", help="Output machine-readable JSON"),
    ) -> None:
        raise typer.Exit(code=_run_action("uninstall", json_mode=json_out))

else:
    app = None  # type: ignore


if __name__ == "__main__":
    raise SystemExit(main())
