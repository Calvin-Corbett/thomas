"""
P147 - Responses tool result mapping (CLI)

CLI wrapper for the gateway endpoint:
  POST /gateway/responses/tool-result-map

Supports:
  --json (machine-readable output)
  --tool-call-id
  --tool-name (optional)
  --result-json (JSON string) OR --result-text
  --is-error, --error-code, --error-message
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "responses-tool-result-map",
        help="Map a tool result into a Responses-style tool output envelope.",
    )

    p.add_argument(
        "--gateway-url",
        required=False,
        default=None,
        help="Gateway base URL (e.g., http://127.0.0.1:8080). Default: http://127.0.0.1:8080",
    )
    p.add_argument("--tool-call-id", required=True, help="Tool call id to associate with this output")
    p.add_argument("--tool-name", required=False, default=None, help="Optional tool name")

    res = p.add_mutually_exclusive_group(required=False)
    res.add_argument("--result-json", required=False, default=None, help="Tool result as a JSON string")
    res.add_argument("--result-text", required=False, default=None, help="Tool result as plain text")

    p.add_argument("--is-error", action="store_true", help="Emit a failed tool output")
    p.add_argument(
        "--error-code",
        required=False,
        default=None,
        help="Machine-readable error code (required if --is-error)",
    )
    p.add_argument(
        "--error-message",
        required=False,
        default=None,
        help="Human-readable error message (required if --is-error)",
    )

    p.add_argument("--json", action="store_true", help="Machine-readable output mode")
    p.set_defaults(func=run)
    return p


def _build_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"tool_call_id": args.tool_call_id}
    if args.tool_name:
        payload["tool_name"] = args.tool_name

    if args.is_error:
        payload["is_error"] = True
        payload["error_code"] = args.error_code
        payload["error_message"] = args.error_message
        return payload

    payload["is_error"] = False
    if args.result_json is not None:
        try:
            payload["result"] = json.loads(args.result_json)
        except Exception as e:
            raise SystemExit(f"invalid --result-json: {e}")
    elif args.result_text is not None:
        payload["result"] = args.result_text
    else:
        payload["result"] = {}
    return payload


def run(args: argparse.Namespace) -> int:
    payload = _build_payload(args)

    gateway_url = args.gateway_url or "http://127.0.0.1:8080"
    url = gateway_url.rstrip("/") + "/gateway/responses/tool-result-map"

    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
    except Exception as e:
        err = {"ok": False, "error": {"code": "network_error", "message": str(e)}}
        if args.json:
            print(json.dumps(err))
        else:
            print(f"error: {err['error']['message']}")
        return 2

    try:
        out = json.loads(body) if body else {}
    except Exception:
        out = {
            "ok": False,
            "error": {"code": "invalid_json_response", "message": "gateway returned non-json"},
            "raw": body,
        }

    if args.json:
        print(json.dumps(out))
    else:
        if isinstance(out, dict) and out.get("ok") is True:
            print(json.dumps(out.get("tool_output", {}), indent=2, sort_keys=True))
        else:
            print(json.dumps(out, indent=2, sort_keys=True))

    return 0 if (isinstance(out, dict) and out.get("ok") is True and status < 400) else 1
