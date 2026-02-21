"""CLI command: restart the node host service.

This command is intended to be discovered by the Thomas CLI command registry.

Design goals
------------
* Thomas-native naming and behavior.
* Deterministic, machine-readable output with ``--json``.
* Avoid deep coupling to unrelated subsystems; call into a single nodes API.

The underlying restart logic lives in :mod:`thomas.nodes.p034_node_command_restart`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from thomas.nodes.p034_node_command_restart import (
    NodeRestartError,
    NodeRestartRequest,
    restart_node_host_service,
)


PROMPT_ID = "P034"
HELP = "Restart the local node host service"


# Most Thomas CLI command groups are plural (e.g., "nodes"). Provide a conservative
# alias mechanism in case the registry uses "node".
PRIMARY_GROUP = "nodes"
ALIAS_GROUPS = ("node",)

COMMAND_NAME = f"{PRIMARY_GROUP} restart"


def build_parser(subparsers: Any) -> argparse.ArgumentParser:
    """Register the ``restart`` leaf command on the provided subparsers."""
    parser = subparsers.add_parser("restart", help=HELP, description=HELP)

    parser.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="Emit machine-readable JSON",
    )

    # Optional explicit overrides that won't collide with typical global flags.
    parser.add_argument(
        "--config-path",
        dest="config_path",
        default=None,
        help="Path to the node config file (node.json)",
    )
    parser.add_argument(
        "--service-name",
        dest="service_name",
        default=None,
        help="Override the service name to restart",
    )
    parser.add_argument(
        "--manager",
        dest="manager",
        default=None,
        help="Force a service manager (systemd, launchd, windows)",
    )
    parser.add_argument(
        "--timeout-s",
        dest="timeout_s",
        type=float,
        default=None,
        help="Timeout (seconds) for each service-manager step (default: 30)",
    )

    parser.set_defaults(func=run)
    return parser


# Common aliases used by various command registries.
add_parser = build_parser
register_parser = build_parser


def register(subparsers: Any) -> argparse.ArgumentParser:
    """Defensive registration entrypoint.

    Some registries pass:
    * the subparsers for the *group* already (preferred)
    * the root subparsers (we then attach to "nodes" if it exists)
    """
    group_parser = _maybe_get_group_parser(subparsers, PRIMARY_GROUP)
    if group_parser is not None:
        return build_parser(_ensure_subparsers(group_parser))

    for alias in ALIAS_GROUPS:
        group_parser = _maybe_get_group_parser(subparsers, alias)
        if group_parser is not None:
            return build_parser(_ensure_subparsers(group_parser))

    # Fall back: assume caller already provided the correct group's subparsers.
    return build_parser(subparsers)


def run(args: argparse.Namespace) -> int:
    """Execute the restart command for the parsed CLI args."""
    json_mode = bool(getattr(args, "json", False) or getattr(args, "json_output", False))

    state_dir = _resolve_state_dir_from_args(args)
    timeout_s = _resolve_timeout_s_from_args(args)

    config_path = getattr(args, "config_path", None)
    if config_path is not None:
        config_path = Path(config_path)

    service_name = getattr(args, "service_name", None)
    manager = getattr(args, "manager", None)

    req = NodeRestartRequest(
        state_dir=state_dir,
        config_path=config_path,
        service_name=service_name,
        timeout_s=timeout_s,
        manager=manager,
    )

    try:
        result = restart_node_host_service(req)
    except NodeRestartError as e:
        _emit_error(e, json_mode=json_mode)
        return e.exit_code

    if json_mode:
        sys.stdout.write(json.dumps({"ok": True, "result": result.to_dict()}, sort_keys=True))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(f"Restarted node host service '{result.service_name}' via {result.manager}.\n")

    return 0


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _emit_error(err: NodeRestartError, *, json_mode: bool) -> None:
    if json_mode:
        sys.stdout.write(json.dumps({"ok": False, "error": err.to_dict()}, sort_keys=True))
        sys.stdout.write("\n")
    else:
        sys.stderr.write(f"{err}\n")


# ---------------------------------------------------------------------------
# State dir / timeout resolution
# ---------------------------------------------------------------------------


def _resolve_state_dir_from_args(args: argparse.Namespace) -> Path | None:
    """Best-effort resolution of the Thomas state directory.

    The Thomas CLI usually supports global options that influence state location
    (profile, dev mode, explicit state_dir). We try to respect those values.
    """
    explicit = getattr(args, "state_dir", None)
    if explicit:
        return Path(explicit)

    # Ask parity_compat if it exposes a helper. We try multiple possible function
    # names to stay compatible across refactors.
    try:
        from thomas.cli import parity_compat as pc  # type: ignore

        for name in ("resolve_state_dir", "get_state_dir", "state_dir_for_args", "state_dir"):
            fn = getattr(pc, name, None)
            if callable(fn):
                try:
                    val = fn(args)
                except TypeError:
                    continue
                if val:
                    return Path(val)
    except Exception:
        pass

    # Simple fallback convention.
    home = Path.home()
    if bool(getattr(args, "dev", False)):
        return home / ".thomas-dev"

    profile = getattr(args, "profile", None)
    if isinstance(profile, str) and profile.strip():
        return home / f".thomas-{profile.strip()}"

    return home / ".thomas"


def _resolve_timeout_s_from_args(args: argparse.Namespace) -> float:
    local = getattr(args, "timeout_s", None)
    if local is not None:
        try:
            f = float(local)
            if f > 0:
                return f
        except (TypeError, ValueError):
            # Let the core layer emit deterministic invalid_input errors for bad values.
            return float(local)  # type: ignore[arg-type]

    for name in ("timeout", "timeout_seconds"):
        val = getattr(args, name, None)
        if val is None:
            continue
        try:
            f = float(val)
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f

    return 30.0


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def _maybe_get_group_parser(subparsers: Any, group_name: str) -> argparse.ArgumentParser | None:
    name_map = getattr(subparsers, "_name_parser_map", None) or getattr(subparsers, "choices", None)
    if isinstance(name_map, dict):
        p = name_map.get(group_name)
        if isinstance(p, argparse.ArgumentParser):
            return p
    return None


def _ensure_subparsers(parser: argparse.ArgumentParser) -> Any:
    for action in getattr(parser, "_actions", []):
        if isinstance(action, argparse._SubParsersAction):
            return action
    return parser.add_subparsers(dest=f"{PRIMARY_GROUP}_command")


def get_command_info() -> dict[str, Any]:
    """Command metadata for registries that prefer a data contract."""
    return {
        "prompt_id": PROMPT_ID,
        "command": COMMAND_NAME,
        "help": HELP,
        "builder": build_parser,
        "runner": run,
    }


COMMAND_INFO = get_command_info()
