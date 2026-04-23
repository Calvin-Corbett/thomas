"""Channel provider interface contract CLI operation.

Adds a `channels provider-contract` subcommand with machine output via `--json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping

from thomas.channels.p075_channel_provider_interface_contract import (
    ERROR_INVALID_INPUT,
    ERROR_MISSING_CONFIG,
    ERROR_PROVIDER_EXTERNAL_FAILURE,
    ERROR_PROVIDER_LOAD_FAILED,
    ERROR_PROVIDER_NOT_FOUND,
    ProviderContractRequest,
    dumps_response_json,
    run_provider_contract,
)

COMMAND_NAME = "provider-contract"


def _parse_json_object(value: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e.msg}") from e
    if not isinstance(parsed, Mapping):
        raise ValueError("JSON must be an object")
    return parsed


def _load_config(args: argparse.Namespace) -> Mapping[str, Any] | None:
    cfg_inline = getattr(args, "config", None)
    cfg_file = getattr(args, "config_file", None)

    if cfg_inline is None and cfg_file is None:
        return None

    if cfg_inline is not None and cfg_file is not None:
        raise ValueError("use only one of --config or --config-file")

    if cfg_inline is not None:
        return _parse_json_object(str(cfg_inline))

    with open(str(cfg_file), "r", encoding="utf-8") as f:
        return _parse_json_object(f.read())


def _exit_code_from_error_code(code: str) -> int:
    # Stable mapping for automation.
    if code == ERROR_INVALID_INPUT:
        return 2
    if code == ERROR_MISSING_CONFIG:
        return 3
    if code == ERROR_PROVIDER_NOT_FOUND:
        return 4
    if code == ERROR_PROVIDER_LOAD_FAILED:
        return 5
    if code == ERROR_PROVIDER_EXTERNAL_FAILURE:
        return 6
    return 1


def _print_human(response_dict: Mapping[str, Any]) -> None:
    if response_dict.get("ok"):
        print(f"OK: {response_dict.get('provider')} ({response_dict.get('action')})")
        result = response_dict.get("result")
        if isinstance(result, Mapping):
            for k, v in result.items():
                print(f"- {k}: {v}")
        return

    err = response_dict.get("error") or {}
    print(f"ERROR: {err.get('code', 'unknown')}: {err.get('message', '')}")
    details = err.get("details")
    if isinstance(details, Mapping) and details:
        for k, v in details.items():
            print(f"- {k}: {v}")


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"channels {COMMAND_NAME}")
    _build_parser(parser)
    args = parser.parse_args(argv)

    try:
        config = _load_config(args)
    except ValueError as e:
        response = {
            "ok": False,
            "provider": getattr(args, "provider", ""),
            "action": getattr(args, "action", ""),
            "result": None,
            "error": {"code": ERROR_INVALID_INPUT, "message": str(e), "details": {}},
        }
        if args.json:
            print(json.dumps(response, sort_keys=True, indent=2))
        else:
            _print_human(response)
        return _exit_code_from_error_code(ERROR_INVALID_INPUT)

    req = ProviderContractRequest(
        provider=args.provider,
        action=args.action,
        config=config,
        recipient=args.recipient,
        message=args.message,
        subject=args.subject,
        timeout_seconds=args.timeout,
        dry_run=bool(args.dry_run),
    )

    resp = run_provider_contract(req)

    if args.json:
        print(dumps_response_json(resp))
    else:
        _print_human(resp.to_dict())

    if resp.ok:
        return 0
    assert resp.error is not None
    return _exit_code_from_error_code(resp.error.code)


def _build_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("provider", help="Provider id (e.g. telegram)")
    parser.add_argument("--action", default="describe", choices=["describe", "health_check", "send"], help="Action")

    parser.add_argument("--recipient", "--to", dest="recipient", help="Recipient identifier")
    parser.add_argument("--message", help="Message text")
    parser.add_argument("--subject", help="Optional subject")

    parser.add_argument("--config", help="Provider config JSON object")
    parser.add_argument("--config-file", help="Path to JSON config file")

    parser.add_argument("--timeout", type=float, help="Timeout in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Validate without sending externally")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    return parser


def register_argparse(subparsers: Any) -> None:
    """Register to an argparse subparsers object."""

    parser = subparsers.add_parser(COMMAND_NAME, help="Run the channel provider contract")
    _build_parser(parser)

    def _runner(ns: argparse.Namespace) -> int:
        argv: list[str] = [str(ns.provider), "--action", str(ns.action)]
        if getattr(ns, "recipient", None):
            argv += ["--recipient", str(ns.recipient)]
        if getattr(ns, "message", None):
            argv += ["--message", str(ns.message)]
        if getattr(ns, "subject", None):
            argv += ["--subject", str(ns.subject)]
        if getattr(ns, "config", None):
            argv += ["--config", str(ns.config)]
        if getattr(ns, "config_file", None):
            argv += ["--config-file", str(ns.config_file)]
        if getattr(ns, "timeout", None) is not None:
            argv += ["--timeout", str(ns.timeout)]
        if getattr(ns, "dry_run", False):
            argv += ["--dry-run"]
        if getattr(ns, "json", False):
            argv += ["--json"]
        return run_cli(argv)

    parser.set_defaults(func=_runner)


add_parser = register_argparse


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_cli(sys.argv[1:]))
