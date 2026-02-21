"""CLI: push a JSON payload to one or more nodes.

This command is intentionally implemented with minimal coupling so it can be
registered by whatever CLI wiring Thomas uses (argparse, click, or registry
scanning).

Machine-readable output is available via ``--json``.

Supported payload sources
-------------------------

* inline JSON: ``--payload '{"a": 1}'``
* file JSON:   ``--payload @payload.json``

Node identifiers
----------------

* If a ``--node`` value is an absolute http(s) URL:
  * if the URL path is root ("/" or empty), ``--endpoint-path`` is appended.
  * if the URL already includes a non-root path, it is treated as the full
    target URL.
* Otherwise the value is treated as a node ID and requires ``--node-map``.

Exit codes
----------

* 0: all pushes succeeded
* 1: at least one node push failed
* 2: invalid input / missing config
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

try:
    import click  # type: ignore

    _HAS_CLICK = True
except Exception:  # pragma: no cover
    click = None
    _HAS_CLICK = False

from thomas.nodes.p041_nodes_push_payload import (
    NodesPushPayloadError,
    NodesPushPayloadRequest,
    push_payload_to_nodes_sync,
)


COMMAND_GROUP = "nodes"
COMMAND_NAME = "push-payload"
COMMAND_ALIASES = ["push_payload"]
HELP = "Push a JSON payload to one or more nodes"
PROMPT_ID = "P041"


# Convenience aliases (different CLI/discovery layers may look for these names).
GROUP = COMMAND_GROUP
NAME = COMMAND_NAME
ALIASES = COMMAND_ALIASES
DESCRIPTION = HELP


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise NodesPushPayloadError("invalid_input", f"file not found: {path}") from e
    except OSError as e:
        raise NodesPushPayloadError("invalid_input", f"unable to read file: {path}") from e


def _parse_json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise NodesPushPayloadError(
            "invalid_input",
            "value must be valid JSON",
            details={"reason": str(e)},
        ) from e


def _parse_payload_arg(payload_arg: str) -> Any:
    """Parse --payload.

    Supports:
    * inline JSON (e.g. '{"a": 1}')
    * @file.json (reads file content as JSON)
    """

    payload_arg = payload_arg.strip()
    if payload_arg.startswith("@"):
        text = _read_text_file(Path(payload_arg[1:]))
        return _parse_json_value(text)
    return _parse_json_value(payload_arg)


def _parse_nodes(values: Iterable[str]) -> List[str]:
    nodes: List[str] = []
    for v in values:
        if not v:
            continue
        # Allow comma-separated lists for convenience.
        parts = [p.strip() for p in str(v).split(",") if p.strip()]
        nodes.extend(parts)
    if not nodes:
        raise NodesPushPayloadError("invalid_input", "at least one --node is required")
    return nodes


def _parse_headers(values: Iterable[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for v in values:
        if not v:
            continue
        v = str(v)
        if ":" in v:
            k, val = v.split(":", 1)
        elif "=" in v:
            k, val = v.split("=", 1)
        else:
            raise NodesPushPayloadError(
                "invalid_input",
                "header must be in 'Key: Value' or 'Key=Value' format",
                details={"header": v},
            )
        k = k.strip()
        val = val.strip()
        if not k:
            raise NodesPushPayloadError("invalid_input", "header key must be non-empty")
        headers[k] = val
    return headers


def _parse_node_map(value: Optional[str]) -> Optional[Dict[str, str]]:
    if not value:
        return None
    value = str(value).strip()
    if value.startswith("@"):
        text = _read_text_file(Path(value[1:]))
        data = _parse_json_value(text)
    else:
        data = _parse_json_value(value)

    if not isinstance(data, dict):
        raise NodesPushPayloadError("invalid_input", "--node-map must be a JSON object")

    out: Dict[str, str] = {}
    for k, v in data.items():
        out[str(k)] = str(v)
    return out


def _dump_json(obj: Mapping[str, Any]) -> str:
    # Deterministic output for automation and tests.
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _print_human(resp_dict: Mapping[str, Any]) -> None:
    ok = bool(resp_dict.get("ok"))
    total = resp_dict.get("total")
    pushed = resp_dict.get("pushed")
    failed = resp_dict.get("failed")

    sys.stdout.write(f"ok={ok} total={total} pushed={pushed} failed={failed}\n")
    for r in resp_dict.get("results", []):
        status = r.get("status")
        node = r.get("node")
        url = r.get("url")
        if r.get("ok"):
            sys.stdout.write(f"  ✓ {node} -> {url} ({status})\n")
        else:
            sys.stdout.write(
                f"  ✗ {node} -> {url} ({status}) {r.get('error_code')}: {r.get('error')}\n"
            )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"{COMMAND_GROUP} {COMMAND_NAME}")
    _add_arguments(parser)
    return parser


def _add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--node",
        dest="nodes",
        action="append",
        required=True,
        help="Node URL or node id. Repeatable; comma-separated also supported.",
    )
    parser.add_argument(
        "--payload",
        required=True,
        help="JSON payload inline, or @path/to/payload.json",
    )
    parser.add_argument(
        "--endpoint-path",
        default="/payload",
        help="Path appended when --node is a base URL (default: /payload)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        dest="timeout_s",
        help="Per-request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Maximum concurrent requests (default: 10)",
    )
    parser.add_argument(
        "--header",
        action="append",
        default=[],
        help="Extra HTTP header (repeatable). Format: 'Key: Value' or 'Key=Value'",
    )
    parser.add_argument(
        "--node-map",
        default=None,
        help="JSON object mapping node ids to base URLs, or @path/to/map.json",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout",
    )


def run(argv: Optional[List[str]] = None) -> int:
    """Standalone entry point used by tests and registry wiring."""

    args = _build_parser().parse_args(argv)
    return _run_from_args(args)


def _run_from_args(args: argparse.Namespace) -> int:
    try:
        nodes = _parse_nodes(args.nodes)
        payload = _parse_payload_arg(args.payload)
        headers = _parse_headers(args.header)
        node_map = _parse_node_map(args.node_map)

        req = NodesPushPayloadRequest(
            nodes=nodes,
            payload=payload,
            endpoint_path=args.endpoint_path,
            timeout_s=float(args.timeout_s),
            concurrency=int(args.concurrency),
            headers=headers or None,
            node_endpoints=node_map,
        )

        resp = push_payload_to_nodes_sync(req)
        resp_dict = resp.to_dict()

        if args.json:
            sys.stdout.write(_dump_json(resp_dict) + "\n")
        else:
            _print_human(resp_dict)

        return 0 if resp_dict.get("ok") else 1

    except NodesPushPayloadError as e:
        if getattr(args, "json", False):
            sys.stdout.write(_dump_json({"ok": False, "error": e.to_dict()}) + "\n")
        else:
            sys.stderr.write(f"error[{e.code}]: {e}\n")
        return 2


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Argparse integration hook."""

    # argparse aliases were added long ago, but be defensive in case Thomas runs
    # on a constrained runtime.
    try:
        parser = subparsers.add_parser(COMMAND_NAME, help=HELP, description=HELP, aliases=COMMAND_ALIASES)
    except TypeError:  # pragma: no cover
        parser = subparsers.add_parser(COMMAND_NAME, help=HELP, description=HELP)

    _add_arguments(parser)
    parser.set_defaults(func=_run_from_args)
    return parser


# Alternate hook names sometimes used by registry scanners.
build_parser = add_parser
register_parser = add_parser
register = add_parser


def _click_impl(
    nodes: Tuple[str, ...],
    payload: str,
    endpoint_path: str,
    timeout_s: float,
    concurrency: int,
    header: Tuple[str, ...],
    node_map: Optional[str],
    json_out: bool,
) -> int:
    ns = argparse.Namespace(
        nodes=list(nodes),
        payload=payload,
        endpoint_path=endpoint_path,
        timeout_s=timeout_s,
        concurrency=concurrency,
        header=list(header),
        node_map=node_map,
        json=json_out,
    )
    return _run_from_args(ns)


if _HAS_CLICK:  # pragma: no cover

    @click.command(COMMAND_NAME, help=HELP)
    @click.option("--node", "nodes", multiple=True, required=True, help="Node URL or id (repeatable)")
    @click.option("--payload", required=True, help="JSON payload inline, or @file.json")
    @click.option("--endpoint-path", default="/payload", show_default=True)
    @click.option("--timeout", "timeout_s", default=10.0, show_default=True, type=float)
    @click.option("--concurrency", default=10, show_default=True, type=int)
    @click.option("--header", multiple=True, help="Extra HTTP header (repeatable)")
    @click.option("--node-map", default=None, help="JSON object mapping node ids to base URLs, or @file")
    @click.option("--json", "json_out", is_flag=True, help="Emit machine-readable JSON")
    def cli_command(
        nodes: Tuple[str, ...],
        payload: str,
        endpoint_path: str,
        timeout_s: float,
        concurrency: int,
        header: Tuple[str, ...],
        node_map: Optional[str],
        json_out: bool,
    ) -> None:
        rc = _click_impl(nodes, payload, endpoint_path, timeout_s, concurrency, header, node_map, json_out)
        raise SystemExit(rc)

else:
    cli_command = None


# Registry-friendly metadata. Different Thomas subsystems may look for different
# keys; keep it plain and self-describing.
COMMAND: Dict[str, Any] = {
    "prompt_id": PROMPT_ID,
    "group": COMMAND_GROUP,
    "name": COMMAND_NAME,
    "aliases": COMMAND_ALIASES,
    "help": HELP,
    "add_parser": add_parser,
    "run": run,
    "click_command": cli_command,
    "supports_json": True,
}


# Convenience aliases for potential registry/discovery patterns.
COMMANDS = [COMMAND]
PARITY_COMMAND = COMMAND
PARITY_COMMANDS = COMMANDS


def get_command() -> Mapping[str, Any]:
    return COMMAND


def get_commands() -> List[Mapping[str, Any]]:
    return COMMANDS


def main(argv: Optional[List[str]] = None) -> None:
    """Console-script friendly entrypoint."""

    raise SystemExit(run(argv))
