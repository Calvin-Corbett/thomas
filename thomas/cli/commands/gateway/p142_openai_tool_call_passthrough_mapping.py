from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DEFAULT_ROUTE_PATHS: tuple[str, ...] = (
    "/v1/gateway/p142_openai_tool_call_passthrough_mapping",
    "/gateway/p142_openai_tool_call_passthrough_mapping",
)

DEFAULT_SCHEMA_PATHS: tuple[str, ...] = (
    "/v1/gateway/p142_openai_tool_call_passthrough_mapping/schema",
    "/gateway/p142_openai_tool_call_passthrough_mapping/schema",
)


@dataclass(frozen=True)
class CliError(Exception):
    code: str
    message: str
    exit_code: int = 2
    details: dict[str, Any] | None = None

    def __str__(self) -> str:  # pragma: no cover
        return self.message


def _load_json_input(path: str | None) -> Any:
    """Load request JSON.
    - If `path` is None: returns a small sample request.
    - If `path` is "-": reads stdin.
    - Else: reads the file.
    """
    if path is None:
        return {
            "messages": [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "functions.read:0",
                            "type": "function",
                            "function": {"name": "read", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "functions.read:0", "content": "ok"},
            ]
        }

    if path == "-":
        raw = sys.stdin.read()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise CliError(code="invalid_json", message=f"stdin is not valid JSON: {e}") from e

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as e:
        raise CliError(code="missing_input", message=f"Input file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise CliError(code="invalid_json", message=f"Input file is not valid JSON: {path}: {e}") from e


def _get_json(url: str, *, timeout_s: float = 30.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else None


def _post_json(url: str, payload: Any, *, timeout_s: float = 30.0) -> Any:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else None


def _call_first_working(base_url: str, payload: Any, paths: Iterable[str]) -> Any:
    last_http_error: urllib.error.HTTPError | None = None
    for path in paths:
        url = base_url.rstrip("/") + path
        try:
            return _post_json(url, payload)
        except urllib.error.HTTPError as e:
            last_http_error = e
            if e.code != 404:
                raise
    if last_http_error is not None:
        raise last_http_error
    raise CliError(code="no_routes", message="No route paths configured")  # pragma: no cover


def _get_first_working(base_url: str, paths: Iterable[str]) -> Any:
    last_http_error: urllib.error.HTTPError | None = None
    for path in paths:
        url = base_url.rstrip("/") + path
        try:
            return _get_json(url)
        except urllib.error.HTTPError as e:
            last_http_error = e
            if e.code != 404:
                raise
    if last_http_error is not None:
        raise last_http_error
    raise CliError(code="no_routes", message="No schema route paths configured")  # pragma: no cover


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "p142-openai-tool-call-passthrough-mapping",
        help="Normalize OpenAI tool_call ids for passthrough transcripts.",
    )
    p.add_argument("--server-url", default=os.environ.get("THOMAS_SERVER_URL"))
    p.add_argument("--input", help="JSON file path, or '-' for stdin. If omitted, uses a sample payload.")
    p.add_argument("--schema", action="store_true", help="Fetch the JSON schema for this endpoint and print it.")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON only.")
    p.set_defaults(_thomas_run=run_from_args)
    return p


def run_from_args(args: argparse.Namespace) -> int:
    server_url = getattr(args, "server_url", None)
    if not server_url:
        raise CliError(
            code="missing_config",
            message="Missing server URL. Pass --server-url or set THOMAS_SERVER_URL.",
            exit_code=2,
        )

    try:
        if getattr(args, "schema", False):
            out = _get_first_working(server_url, DEFAULT_SCHEMA_PATHS)
        else:
            payload = _load_json_input(getattr(args, "input", None))
            out = _call_first_working(server_url, payload, DEFAULT_ROUTE_PATHS)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
            parsed = json.loads(body) if body else None
        except json.JSONDecodeError:
            parsed = None
        raise CliError(
            code="http_error",
            message=f"HTTP {e.code} calling {server_url}",
            exit_code=3,
            details={"status": e.code, "body": parsed},
        ) from e
    except urllib.error.URLError as e:
        raise CliError(code="connection_failed", message=f"Failed to reach server: {e}", exit_code=3) from e

    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True))
        sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="thomas gateway")
    sub = parser.add_subparsers(dest="command")
    build_parser(sub)
    args = parser.parse_args(argv)
    if not hasattr(args, "_thomas_run"):
        parser.print_help()
        return 2
    try:
        return args._thomas_run(args)
    except CliError as e:
        sys.stderr.write(
            json.dumps({"ok": False, "error": {"code": e.code, "message": e.message, "details": e.details or {}}})
            + "\n"
        )
        return e.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
