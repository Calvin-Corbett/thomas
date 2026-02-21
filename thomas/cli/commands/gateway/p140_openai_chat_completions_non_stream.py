from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from thomas.server.routes.gateway.p140_openai_chat_completions_non_stream import (
    _chat_completions_url,
    _error,
    resolve_openai_config,
    validate_request,
)

COMMAND_NAME = "p140-openai-chat-completions-non-stream"


def _build_request_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    if args.request_json:
        return json.loads(args.request_json)

    if not args.model:
        raise ValueError("--model is required when --request-json is not provided")

    messages: List[Dict[str, Any]] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    if args.user:
        messages.append({"role": "user", "content": args.user})

    if not messages:
        raise ValueError("Provide at least one message via --user and/or --system, or use --request-json")

    req: Dict[str, Any] = {"model": args.model, "messages": messages, "stream": False}
    if args.temperature is not None:
        req["temperature"] = args.temperature
    if args.max_tokens is not None:
        req["max_tokens"] = args.max_tokens
    return req


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_s: float) -> tuple[int, bytes, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.getcode(), resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")
    except urllib.error.URLError as e:
        raise ConnectionError(str(e)) from e


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=f"thomas gateway {COMMAND_NAME}",
        description="Call OpenAI Chat Completions (non-stream) and print the result.",
    )
    parser.add_argument("--model", help="OpenAI model name (e.g. gpt-4o-mini).")
    parser.add_argument("--system", help="Optional system message.")
    parser.add_argument("--user", help="User message.")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=None, dest="max_tokens")
    parser.add_argument("--request-json", help="Full OpenAI request JSON string (overrides other flags).")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    args = parser.parse_args(argv)

    try:
        req_obj = _build_request_from_args(args)
    except Exception as e:
        parser.error(str(e))
        return 2

    validated = validate_request(req_obj)
    if isinstance(validated, dict) and "error" in validated:
        _print_output(validated, json_only=args.json)
        return 1

    cfg_or_err = resolve_openai_config(None)
    if isinstance(cfg_or_err, dict) and "error" in cfg_or_err:
        _print_output(cfg_or_err, json_only=args.json)
        return 1

    cfg = cfg_or_err  # type: ignore[assignment]
    url = _chat_completions_url(cfg.base_url)

    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if cfg.organization:
        headers["OpenAI-Organization"] = cfg.organization

    try:
        status, body, content_type = _post_json(url, headers, validated, timeout_s=cfg.timeout_s)
    except ConnectionError:
        _print_output(
            _error(
                message="Failed to reach upstream OpenAI service.",
                error_type="upstream_error",
                code="upstream_unreachable",
            ),
            json_only=args.json,
        )
        return 1

    looks_like_json = (
        "application/json" in (content_type or "").lower()
        or body.lstrip().startswith(b"{")
        or body.lstrip().startswith(b"[")
    )
    if looks_like_json:
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = _error(
                message="Upstream OpenAI returned invalid JSON.",
                error_type="upstream_error",
                code="upstream_invalid_json",
            )
            _print_output(data, json_only=args.json)
            return 1
    else:
        data = _error(
            message="Upstream OpenAI returned a non-JSON response.",
            error_type="upstream_error",
            code="upstream_non_json",
        )
        _print_output(data, json_only=args.json)
        return 1

    _print_output(data, json_only=args.json)
    ok = status < 400 and not (isinstance(data, dict) and "error" in data)
    return 0 if ok else 1


def _print_output(data: Any, *, json_only: bool) -> None:
    if json_only:
        sys.stdout.write(json.dumps(data, ensure_ascii=False))
        sys.stdout.write("\n")
        return

    if isinstance(data, dict):
        try:
            content = data["choices"][0]["message"]["content"]
            sys.stdout.write(str(content).rstrip() + "\n")
            return
        except Exception:
            pass

    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")


def register(subparsers: Any) -> None:
    add_parser = getattr(subparsers, "add_parser", None)
    if add_parser is None:
        return

    p = add_parser(COMMAND_NAME, help="OpenAI chat completions (non-stream)")
    p.add_argument("--model", required=False)
    p.add_argument("--system", required=False)
    p.add_argument("--user", required=False)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--max-tokens", type=int, default=None, dest="max_tokens")
    p.add_argument("--request-json", required=False)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=lambda ns: run_cli(_argv_from_namespace(ns)))


def _argv_from_namespace(ns: Any) -> List[str]:
    argv: List[str] = []
    for key, flag in [
        ("model", "--model"),
        ("system", "--system"),
        ("user", "--user"),
        ("temperature", "--temperature"),
        ("max_tokens", "--max-tokens"),
        ("request_json", "--request-json"),
    ]:
        val = getattr(ns, key, None)
        if val is None:
            continue
        argv.extend([flag, str(val)])
    if getattr(ns, "json", False):
        argv.append("--json")
    return argv


def main() -> None:
    raise SystemExit(run_cli())
