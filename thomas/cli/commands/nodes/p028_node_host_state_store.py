from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from thomas.nodes.p028_node_host_state_store import (
    NodeHostStateStore,
    NodeHostStateStoreError,
    NodeHostStateStoreExternalFailureError,
    NodeHostStateStoreInvalidInputError,
    delete_host_state_json,
    get_host_state_json,
    put_host_state_json,
    resolve_host_state_store_dir,
    scan_host_states_json,
)

COMMAND_NAME = "host-state-store"
COMMAND_ALIASES = ("host_state_store",)
COMMAND_HELP = "Persist and query per-host node state snapshots."
COMMAND_DESCRIPTION = (
    "Manage a simple, local, file-backed store of host state snapshots.\n\n"
    "This is useful for automation and tooling that needs to persist lightweight host-level\n"
    "state between runs (e.g., inventory facts, last-seen timestamps, connectivity flags).\n"
)

# Discovery metadata (kept intentionally plain to reduce coupling).
CLI_METADATA: dict[str, Any] = {
    "group": "nodes",
    "name": COMMAND_NAME,
    "aliases": list(COMMAND_ALIASES),
    "help": COMMAND_HELP,
    "supports_json": True,
}

# A few alias names commonly used by CLI parity registries.
PARITY_COMMANDS = [CLI_METADATA]
CLI_COMMANDS = [CLI_METADATA]
COMMANDS = [CLI_METADATA]


def get_parity_commands() -> list[dict[str, Any]]:
    """
    Optional discovery hook for CLI parity registries.

    Some Thomas CLI wiring code discovers commands by importing modules and calling a known function.
    Returning a plain dict keeps this module decoupled from any particular registry implementation.
    """
    return [CLI_METADATA]


def _read_stdin() -> str:
    try:
        return sys.stdin.read()
    except Exception as exc:  # pragma: no cover
        raise NodeHostStateStoreExternalFailureError(
            "stdin_read_failed",
            "Failed to read state from stdin.",
            details={"error": str(exc)},
        ) from exc


def _load_state_from_args(state_json: str | None, state_file: str | None) -> dict[str, Any]:
    if state_json and state_file:
        raise NodeHostStateStoreInvalidInputError(
            "invalid_state_input",
            "Provide either --state or --state-file, not both.",
        )
    if not state_json and not state_file:
        raise NodeHostStateStoreInvalidInputError(
            "invalid_state_input",
            "Missing state input. Provide --state or --state-file.",
        )

    raw: str
    if state_file:
        if state_file == "-":
            raw = _read_stdin()
        else:
            path = Path(state_file)
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise NodeHostStateStoreExternalFailureError(
                    "state_file_read_failed",
                    "Failed to read state file.",
                    details={"path": str(path), "error": str(exc)},
                ) from exc
    else:
        if state_json == "-":
            raw = _read_stdin()
        else:
            raw = state_json or ""

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NodeHostStateStoreInvalidInputError(
            "invalid_state_json",
            "State must be valid JSON.",
            details={"error": str(exc)},
        ) from exc

    if not isinstance(data, dict):
        raise NodeHostStateStoreInvalidInputError(
            "invalid_state",
            "State JSON must be an object (dict).",
            details={"received_type": type(data).__name__},
        )
    return data


def _emit(obj: Any, *, json_mode: bool) -> None:
    if json_mode:
        sys.stdout.write(json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n")
        return

    # Human output: keep it readable and stable.
    if isinstance(obj, str):
        sys.stdout.write(obj + "\n")
    else:
        sys.stdout.write(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _store_from_args(store_dir: str | None, *, env: Mapping[str, str] | None = None) -> NodeHostStateStore:
    resolved = resolve_host_state_store_dir(
        Path(store_dir) if store_dir else None,
        env=env,
        allow_default=True,
    )
    return NodeHostStateStore(resolved, create=True)


def _cmd_set(args: argparse.Namespace, *, env: Mapping[str, str] | None = None) -> int:
    store = _store_from_args(args.store_dir, env=env)
    state = _load_state_from_args(args.state, args.state_file)

    if getattr(args, "merge", False):
        existing = store.get(args.host_id)
        if existing is not None:
            merged = dict(existing.state)
            merged.update(state)
            state = merged

    payload = put_host_state_json(store, args.host_id, state, updated_at=args.updated_at)
    _emit(payload if args.json else payload["record"], json_mode=args.json)
    return 0


def _cmd_get(args: argparse.Namespace, *, env: Mapping[str, str] | None = None) -> int:
    store = _store_from_args(args.store_dir, env=env)
    payload = get_host_state_json(store, args.host_id)
    if args.json:
        _emit(payload, json_mode=True)
        return 0 if payload["found"] else 1

    if not payload["found"]:
        _emit(f"No record found for host_id={args.host_id}", json_mode=False)
        return 1
    _emit(payload["record"], json_mode=False)
    return 0


def _cmd_delete(args: argparse.Namespace, *, env: Mapping[str, str] | None = None) -> int:
    store = _store_from_args(args.store_dir, env=env)
    payload = delete_host_state_json(store, args.host_id)
    _emit(payload, json_mode=args.json)
    return 0 if payload["deleted"] else 1


def _cmd_list(args: argparse.Namespace, *, env: Mapping[str, str] | None = None) -> int:
    store = _store_from_args(args.store_dir, env=env)
    payload = scan_host_states_json(store)

    if args.json:
        _emit(payload, json_mode=True)
        return 0

    _emit(payload["records"], json_mode=False)
    if payload["errors"]:
        sys.stderr.write(f"Warning: {len(payload['errors'])} record(s) could not be read. Use --json for details.\n")
    return 0


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """
    Register the command with an argparse subparser collection.

    This is intentionally a small, dependency-free surface that can be imported
    by Thomas's CLI wiring without needing to know about this module's internals.
    """
    add_kwargs: dict[str, Any] = {
        "help": COMMAND_HELP,
        "description": COMMAND_DESCRIPTION,
    }
    # `aliases=` exists on argparse SubParsersAction in modern Python versions; guard for safety.
    try:
        parser = subparsers.add_parser(COMMAND_NAME, aliases=list(COMMAND_ALIASES), **add_kwargs)
    except TypeError:  # pragma: no cover
        parser = subparsers.add_parser(COMMAND_NAME, **add_kwargs)

    parser.add_argument(
        "--store-dir",
        help="Directory backing the store. Overrides environment/default resolution.",
        default=None,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout.",
    )

    actions = parser.add_subparsers(dest="action", required=True)

    p_set = actions.add_parser("set", help="Create or replace a host state record.")
    p_set.add_argument("host_id", help="Host identifier (safe ASCII slug).")
    p_set.add_argument("--state", help="State as a JSON string (or '-' for stdin).", default=None)
    p_set.add_argument(
        "--state-file", help="Path to a JSON file containing the state (or '-' for stdin).", default=None
    )
    p_set.add_argument(
        "--updated-at", help="Override updated_at ISO-8601 timestamp (must include timezone).", default=None
    )
    p_set.add_argument("--merge", action="store_true", help="Merge state into an existing record (shallow).")
    p_set.set_defaults(_handler=_cmd_set)

    p_get = actions.add_parser("get", help="Fetch a host state record.")
    p_get.add_argument("host_id", help="Host identifier.")
    p_get.set_defaults(_handler=_cmd_get)

    p_del = actions.add_parser("delete", help="Delete a host state record.")
    p_del.add_argument("host_id", help="Host identifier.")
    p_del.set_defaults(_handler=_cmd_delete)

    p_list = actions.add_parser("list", help="List all host state records.")
    p_list.set_defaults(_handler=_cmd_list)

    return parser


# Compatibility aliases (Thomas CLI wiring may look for different function names).
register = build_parser
add_parser = build_parser
add_subparser = build_parser


def cli_main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    """
    Standalone entrypoint primarily intended for tests and automation.

    If Thomas already wires this module into its main CLI, prefer that integration.
    """
    parser = argparse.ArgumentParser(prog=f"{COMMAND_NAME}")
    build_parser(parser.add_subparsers(dest="cmd", required=True))

    args = parser.parse_args(list(argv) if argv is not None else None)
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.error("No action selected.")
        return 2  # pragma: no cover

    try:
        return int(handler(args, env=env))
    except NodeHostStateStoreError as exc:
        if getattr(args, "json", False):
            _emit({"ok": False, "error": exc.to_json()}, json_mode=True)
            return 2
        sys.stderr.write(f"{exc.code}: {exc}\n")
        return 2


# Optional Typer integration (if Thomas uses Typer/Click).
try:  # pragma: no cover
    import typer
except ImportError:  # pragma: no cover
    typer_app = None
else:  # pragma: no cover
    typer_app = typer.Typer(
        name=COMMAND_NAME,
        help=COMMAND_HELP,
        add_completion=False,
        no_args_is_help=True,
    )

    @typer_app.callback()
    def _cb(
        ctx: typer.Context,
        store_dir: Path | None = typer.Option(None, "--store-dir", help="Directory backing the store."),
        json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    ) -> None:
        ctx.ensure_object(dict)
        ctx.obj["store_dir"] = str(store_dir) if store_dir else None
        ctx.obj["json"] = bool(json_mode)

    @typer_app.command("set")
    def _typer_set(
        ctx: typer.Context,
        host_id: str = typer.Argument(...),
        state: str | None = typer.Option(None, "--state"),
        state_file: Path | None = typer.Option(None, "--state-file"),
        updated_at: str | None = typer.Option(None, "--updated-at"),
        merge: bool = typer.Option(False, "--merge"),
    ) -> None:
        args = argparse.Namespace(
            store_dir=ctx.obj["store_dir"],
            json=ctx.obj["json"],
            host_id=host_id,
            state=state,
            state_file=str(state_file) if state_file else None,
            updated_at=updated_at,
            merge=merge,
        )
        code = _cmd_set(args, env=os.environ)
        raise typer.Exit(code=code)

    @typer_app.command("get")
    def _typer_get(ctx: typer.Context, host_id: str = typer.Argument(...)) -> None:
        args = argparse.Namespace(store_dir=ctx.obj["store_dir"], json=ctx.obj["json"], host_id=host_id)
        code = _cmd_get(args, env=os.environ)
        raise typer.Exit(code=code)

    @typer_app.command("delete")
    def _typer_delete(ctx: typer.Context, host_id: str = typer.Argument(...)) -> None:
        args = argparse.Namespace(store_dir=ctx.obj["store_dir"], json=ctx.obj["json"], host_id=host_id)
        code = _cmd_delete(args, env=os.environ)
        raise typer.Exit(code=code)

    @typer_app.command("list")
    def _typer_list(ctx: typer.Context) -> None:
        args = argparse.Namespace(store_dir=ctx.obj["store_dir"], json=ctx.obj["json"])
        code = _cmd_list(args, env=os.environ)
        raise typer.Exit(code=code)
