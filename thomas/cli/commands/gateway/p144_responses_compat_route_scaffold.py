"""
CLI helper for the P144 Responses-compatibility route scaffold.

This command emits machine-readable schema/metadata about the `/v1/responses`
compatibility surface. It's intentionally small and side-effect free.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from thomas.server.routes.gateway.p144_responses_compat_route_scaffold import get_json_schema


@dataclass(frozen=True)
class ResponsesCompatCliReport:
    name: str
    schema: Dict[str, Any]


def build_report() -> ResponsesCompatCliReport:
    return ResponsesCompatCliReport(name="responses_compat", schema=get_json_schema())


def _print_report(report: ResponsesCompatCliReport, *, json_mode: bool) -> None:
    payload = asdict(report)
    if json_mode:
        print(json.dumps(payload, indent=None, separators=(",", ":"), ensure_ascii=False))
        return
    print(payload["name"])
    print(json.dumps(payload["schema"], indent=2, ensure_ascii=False))


def _build_arg_parser(subparsers: Optional[argparse._SubParsersAction] = None) -> argparse.ArgumentParser:
    name = "p144-responses-compat"
    help_text = "Emit schema/metadata for the Responses compatibility route."
    if subparsers is not None:
        parser = subparsers.add_parser(name, help=help_text)
    else:
        parser = argparse.ArgumentParser(prog=name, description=help_text)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    return parser


def run(args: argparse.Namespace) -> int:
    report = build_report()
    _print_report(report, json_mode=bool(getattr(args, "json", False)))
    return 0


COMMAND_NAME = "p144-responses-compat"


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    parser = _build_arg_parser(subparsers)
    parser.set_defaults(func=run)
    return parser


def register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    return add_parser(subparsers)


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    ns = parser.parse_args(argv)
    return run(ns)
