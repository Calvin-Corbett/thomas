from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class P148CompatModelCapabilityResolverArgs:
    model: str
    json_output: bool = False


def resolve_locally(model: str) -> Dict[str, Any]:
    """Local resolver path used by tests and CLI offline mode."""

    from thomas.server.routes.gateway.p148_compat_model_capability_resolver import (
        resolve_compat_model_capabilities,
    )

    return resolve_compat_model_capabilities({"model": model}).to_dict()


def build_arg_parser(subparsers) -> Any:  # pragma: no cover
    """Hook for CLI frameworks that use argparse-like subparsers."""

    p = subparsers.add_parser(
        "compat-model-capabilities",
        help="Resolve compat-layer capabilities for a given model identifier.",
    )
    p.add_argument("--model", required=True, help="Model identifier to resolve (e.g., gpt-4.1-mini).")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout.")
    p.set_defaults(func=run_from_parsed_args)
    return p


def run_from_parsed_args(args) -> int:  # pragma: no cover
    parsed = P148CompatModelCapabilityResolverArgs(
        model=str(getattr(args, "model", "") or ""),
        json_output=bool(getattr(args, "json", False)),
    )
    return run(parsed)


def run(parsed: P148CompatModelCapabilityResolverArgs, *, stdout=None) -> int:
    """CLI entrypoint (local/offline).

    Returns:
      - 0 on ok
      - 2 on invalid input/config
    """

    if stdout is None:  # pragma: no cover
        import sys

        stdout = sys.stdout

    result = resolve_locally(parsed.model)
    ok = bool(result.get("ok"))

    if parsed.json_output:
        stdout.write(json.dumps(result, sort_keys=True))
        stdout.write("\n")
        return 0 if ok else 2

    if ok:
        caps = result.get("capabilities", {}) or {}
        stdout.write(f"model: {caps.get('model')}\n")
        stdout.write(f"family: {caps.get('family')}\n")
        stdout.write("capabilities:\n")
        for k in [
            "supports_chat_completions",
            "supports_responses_api",
            "supports_streaming",
            "supports_function_tools",
            "supports_json_schema_response_format",
        ]:
            stdout.write(f"  - {k}: {caps.get(k)}\n")
        notes = caps.get("notes") or []
        if notes:
            stdout.write("notes:\n")
            for n in notes:
                stdout.write(f"  - {n}\n")
        return 0

    err = result.get("error", {}) or {}
    stdout.write(f"error: {err.get('code')} {err.get('message')}\n")
    return 2
