"""CLI: Responses create (non-stream).

Sends a non-streaming Responses create request to a running Thomas server.

Exposes loader-friendly entrypoints:
- build_parser(subparsers) / add_subparser(subparsers)
- run(args)
- main(argv=None)

Machine-readable output supported via `--json`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL_ENV = "THOMAS_BASE_URL"
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_ENDPOINT_PATH = "/v1/responses"

COMMAND_NAME = "p145-responses-create-non-stream"


@dataclass(frozen=True)
class ResponsesCreateNonStreamCliRequest:
    model: str
    input: str


@dataclass(frozen=True)
class ResponsesCreateNonStreamCliResult:
    payload: Mapping[str, Any]

    @property
    def output_text(self) -> str | None:
        try:
            out0 = self.payload.get("output", [None])[0]
            if isinstance(out0, dict):
                content0 = out0.get("content", [None])[0]
                if isinstance(content0, dict):
                    text = content0.get("text")
                    if isinstance(text, str):
                        return text
        except Exception:  # REVIEWED: broad catch
            return None
        return None


def _build_payload(req: ResponsesCreateNonStreamCliRequest) -> dict[str, Any]:
    return {"model": req.model, "input": req.input, "stream": False}


def _post_json(url: str, payload: Mapping[str, Any], *, timeout_s: float) -> Mapping[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection failed: {e.reason}") from None

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        raise RuntimeError("Server returned non-JSON response.") from None

    if not isinstance(decoded, dict):
        raise RuntimeError("Server returned a non-object JSON payload.")

    return decoded


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:  # type: ignore[name-defined]
    parser = subparsers.add_parser(COMMAND_NAME, help="Create a non-streaming response via the Responses API.")
    parser.add_argument("--model", required=True, help="Model identifier.")
    parser.add_argument("--input", required=True, help="Input text.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get(DEFAULT_BASE_URL_ENV, DEFAULT_BASE_URL),
        help=f"Thomas server base URL (env: {DEFAULT_BASE_URL_ENV}).",
    )
    parser.add_argument("--timeout-s", type=float, default=60.0, help="HTTP timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON response (machine-readable).")
    parser.set_defaults(_thomas_cmd_run=run)
    return parser


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:  # type: ignore[name-defined]
    return build_parser(subparsers)


# Compatibility aliases
register = add_subparser
register_command = add_subparser


def run(args: argparse.Namespace) -> int:
    req = ResponsesCreateNonStreamCliRequest(model=args.model, input=args.input)
    base_url = str(args.base_url).rstrip("/")
    url = f"{base_url}{DEFAULT_ENDPOINT_PATH}"

    payload = _build_payload(req)
    result_payload = _post_json(url, payload, timeout_s=float(args.timeout_s))
    result = ResponsesCreateNonStreamCliResult(payload=result_payload)

    if args.json:
        sys.stdout.write(json.dumps(result.payload, ensure_ascii=False, indent=2) + "\n")
        return 0

    text = result.output_text
    if text is None:
        sys.stdout.write(json.dumps(result.payload, ensure_ascii=False, indent=2) + "\n")
        return 0

    sys.stdout.write(text + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thomas")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser(subparsers)
    args = parser.parse_args(argv)

    runner = getattr(args, "_thomas_cmd_run", None)
    if runner is None:
        parser.error("No command selected.")
        return 2

    try:
        return int(runner(args))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
