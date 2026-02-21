from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from thomas.server.routes.gateway.p149_compat_request_validation_layer import json_schema, validate_compat_request


def _read_json_arg(value: str) -> Any:
    """Accept raw JSON, or @/path/to/file.json."""

    if value.startswith("@"):
        path = value[1:]
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(value)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="thomas-gateway-compat-validate",
        description="Validate compat request payloads deterministically (machine-readable).",
    )
    p.add_argument("kind", help="Compat kind: openai_chat_completions | responses_create")
    p.add_argument("payload", help="JSON payload string, or @/path/to/file.json")
    p.add_argument("--json", action="store_true", help="Emit JSON result to stdout.")
    p.add_argument("--schema", action="store_true", help="Print JSON schema for the validation envelope and exit.")
    return p


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.schema:
        print(json.dumps(json_schema(), indent=2, sort_keys=True))
        return 0

    try:
        payload = _read_json_arg(args.payload)
    except FileNotFoundError:
        out = {
            "ok": False,
            "kind": str(args.kind),
            "normalized": {},
            "errors": [{"code": "file_not_found", "message": "Payload file not found.", "path": "$"}],
        }
        if args.json:
            print(json.dumps(out, indent=2, sort_keys=True))
        else:
            print("file_not_found: $ Payload file not found.", file=sys.stderr)
        return 2
    except Exception:
        out = {
            "ok": False,
            "kind": str(args.kind),
            "normalized": {},
            "errors": [{"code": "invalid_json", "message": "Payload must be valid JSON.", "path": "$"}],
        }
        if args.json:
            print(json.dumps(out, indent=2, sort_keys=True))
        else:
            print("invalid_json: $ Payload must be valid JSON.", file=sys.stderr)
        return 2

    result = validate_compat_request(str(args.kind), payload)
    out = result.to_dict()

    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        if out["ok"]:
            print("OK")
        else:
            for e in out["errors"]:
                code = e.get("code", "error")
                path = e.get("path", "")
                msg = e.get("message", "")
                print(f"{code}: {path} {msg}".strip(), file=sys.stderr)

    return 0 if out["ok"] else 1


def main() -> None:
    raise SystemExit(run())
