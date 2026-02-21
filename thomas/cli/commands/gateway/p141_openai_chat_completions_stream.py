"""CLI: stream OpenAI Chat Completions via the Thomas gateway.

This command is intended for parity / prompt-pack testing. It calls the
Thomas server's gateway route implemented in:
  thomas.server.routes.gateway.p141_openai_chat_completions_stream

Output modes:
- default: prints streamed assistant text to stdout as it arrives
- --json: prints a single JSON object with the final concatenated text and
  basic metadata (useful for automation)

The exact CLI wiring (how parsers are discovered and registered) is handled
by the Thomas CLI framework. This module exposes a couple of common entry
points (`register`, `add_parser`, `run`) to maximize compatibility.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List

from aiohttp import ClientConnectorError, ClientSession, ClientTimeout


@dataclass(frozen=True)
class ChatCompletionsStreamArgs:
    server: str
    model: str
    message: str
    json_output: bool


def _default_server() -> str:
    # Thomas servers often bind on localhost; the exact port is config-driven.
    return "http://127.0.0.1:8000"


def _endpoint_url(server: str) -> str:
    return server.rstrip("/") + "/gateway/p141/openai_chat_completions_stream"


async def _iter_sse_data_lines(resp: Any) -> AsyncIterator[str]:
    """Yield the `data:` payload for each SSE line (best-effort)."""

    async for raw in resp.content.iter_any():
        text = raw.decode("utf-8", errors="replace")
        # Chunk may contain multiple lines.
        for line in text.splitlines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            yield line[len("data:") :].strip()


def _extract_delta_text(chunk: Dict[str, Any]) -> str:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


async def _run_async(args: ChatCompletionsStreamArgs) -> int:
    url = _endpoint_url(args.server)

    payload: Dict[str, Any] = {
        "model": args.model,
        "messages": [{"role": "user", "content": args.message}],
        "stream": True,
    }

    timeout = ClientTimeout(total=300)

    async with ClientSession(timeout=timeout) as session:
        try:
            async with session.post(url, json=payload) as resp:
                if resp.status >= 400:
                    # Gateway errors are JSON.
                    try:
                        err = await resp.json(content_type=None)
                    except Exception:
                        err = {"status": resp.status, "body": await resp.text()}

                    if args.json_output:
                        print(json.dumps({"ok": False, "error": err}, ensure_ascii=False))
                    else:
                        print(f"ERROR ({resp.status}): {err}")
                    return 1

                collected: List[str] = []
                async for data_str in _iter_sse_data_lines(resp):
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta = _extract_delta_text(chunk)
                    if delta:
                        collected.append(delta)
                        if not args.json_output:
                            print(delta, end="", flush=True)

                if args.json_output:
                    print(json.dumps({"ok": True, "model": args.model, "text": "".join(collected)}, ensure_ascii=False))

                return 0

        except asyncio.TimeoutError:
            if args.json_output:
                print(json.dumps({"ok": False, "error": {"code": "timeout"}}, ensure_ascii=False))
            else:
                print("ERROR: timed out")
            return 1
        except ClientConnectorError:
            if args.json_output:
                print(json.dumps({"ok": False, "error": {"code": "connect_error"}}, ensure_ascii=False))
            else:
                print("ERROR: could not connect to server")
            return 1


def build_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--server", default=_default_server(), help="Thomas server base URL")
    parser.add_argument("--model", required=True, help="OpenAI model name")
    parser.add_argument("--message", required=True, help="User message")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit machine-readable JSON")
    return parser


def run(parsed: argparse.Namespace) -> int:
    args = ChatCompletionsStreamArgs(
        server=str(parsed.server),
        model=str(parsed.model),
        message=str(parsed.message),
        json_output=bool(getattr(parsed, "json_output", False)),
    )
    return asyncio.run(_run_async(args))


# ---- Compatibility shims for different CLI discovery mechanisms ----


COMMAND_NAME = "p141-openai-chat-completions-stream"


def register(subparsers: argparse._SubParsersAction) -> None:  # pragma: no cover
    """Register this command with an argparse subparser collection."""

    parser = subparsers.add_parser(COMMAND_NAME, help="Stream OpenAI Chat Completions via gateway")
    build_parser(parser)
    parser.set_defaults(func=run)


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:  # pragma: no cover
    """Alternative registration hook used by some command loaders."""

    parser = subparsers.add_parser(COMMAND_NAME)
    build_parser(parser)
    parser.set_defaults(func=run)
    return parser
