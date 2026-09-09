from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from thomas.nodes.p032_node_command_run import (
    NODES_RUN_ROUTE,
    NodeCommandRunException,
    NodeCommandRunRequest,
    NodeRunErrorCode,
    request_from_json,
)

# Environment variable fallbacks (kept intentionally simple & explicit).
DEFAULT_URL_ENV = "THOMAS_URL"
DEFAULT_TOKEN_ENV = "THOMAS_TOKEN"


def _add_argument_if_missing(parser: argparse.ArgumentParser, *option_strings: str, **kwargs: Any) -> None:
    # argparse doesn't expose a public "has_option" API; this is a pragmatic guard.
    existing = getattr(parser, "_option_string_actions", {})
    if any(opt in existing for opt in option_strings):
        return
    parser.add_argument(*option_strings, **kwargs)


def _parse_env_kv(items: Iterable[str] | None) -> dict[str, str] | None:
    if not items:
        return None
    env: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise NodeCommandRunException(NodeRunErrorCode.INVALID_INPUT, "--env must be KEY=VAL")
        k, v = item.split("=", 1)
        k = k.strip()
        if not k:
            raise NodeCommandRunException(NodeRunErrorCode.INVALID_INPUT, "--env key must be non-empty")
        env[k] = v
    return env


def _join_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    return f"{base}{path}"


def _resolve_gateway(url: str | None, token: str | None) -> tuple[str, str | None]:
    """Resolve gateway URL/token.

    Precedence:
    1) CLI args
    2) env vars
    """
    resolved_url = url or os.environ.get(DEFAULT_URL_ENV)
    resolved_token = token or os.environ.get(DEFAULT_TOKEN_ENV)

    if not resolved_url:
        raise NodeCommandRunException(
            NodeRunErrorCode.MISSING_CONFIG,
            f"Missing gateway URL (provide --url or set {DEFAULT_URL_ENV}).",
        )
    return resolved_url, resolved_token


def _http_post_json(url: str, token: str | None, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise NodeCommandRunException(
            NodeRunErrorCode.INVOKE_FAILED,
            f"Gateway HTTP error: {e.code}",
            details={"status": e.code, "body": raw},
        )
    except urllib.error.URLError as e:
        raise NodeCommandRunException(
            NodeRunErrorCode.INVOKE_FAILED,
            "Failed to reach gateway.",
            details={"reason": str(getattr(e, "reason", e))},
        )

    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise NodeCommandRunException(
            NodeRunErrorCode.INVOKE_FAILED,
            "Gateway returned non-JSON response.",
            details={"body": raw},
        )

    if not isinstance(data, dict):
        raise NodeCommandRunException(
            NodeRunErrorCode.INVOKE_FAILED,
            "Gateway returned invalid JSON shape.",
            details={"body": data},
        )

    return data


def build_request(
    *,
    node: str | None,
    argv: list[str] | None,
    raw: str | None,
    cwd: str | None,
    env_items: list[str] | None,
    command_timeout_ms: int | None,
    invoke_timeout_ms: int | None,
    needs_screen_recording: bool,
    agent: str | None,
    ask: str | None,
    security: str | None,
) -> NodeCommandRunRequest:
    env = _parse_env_kv(env_items)

    req = NodeCommandRunRequest(
        node=node,
        argv=argv,
        raw=raw,
        cwd=cwd,
        env=env,
        command_timeout_ms=command_timeout_ms,
        invoke_timeout_ms=invoke_timeout_ms,
        needs_screen_recording=needs_screen_recording,
        agent=agent,
        ask=ask,
        security=security,
    )

    # Reuse the server-side validator to keep contracts in lockstep.
    request_from_json(asdict(req))
    return req


def run_nodes_run(
    *,
    url: str | None,
    token: str | None,
    timeout_s: float,
    json_output: bool,
    req: NodeCommandRunRequest,
) -> int:
    gateway_url, gateway_token = _resolve_gateway(url, token)
    endpoint = _join_url(gateway_url, NODES_RUN_ROUTE)

    payload = {
        "node": req.node,
        "argv": req.argv,
        "raw": req.raw,
        "cwd": req.cwd,
        "env": req.env,
        "command_timeout_ms": req.command_timeout_ms,
        "invoke_timeout_ms": req.invoke_timeout_ms,
        "needs_screen_recording": req.needs_screen_recording,
        "agent": req.agent,
        "ask": req.ask,
        "security": req.security,
    }

    data = _http_post_json(endpoint, gateway_token, payload, timeout_s=timeout_s)

    if json_output:
        sys.stdout.write(json.dumps(data, sort_keys=True))
        sys.stdout.write("\n")
        return 0 if bool(data.get("ok")) else 1

    if bool(data.get("ok")):
        result = data.get("result") or {}
        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        if stdout:
            sys.stdout.write(stdout)
            if not stdout.endswith("\n"):
                sys.stdout.write("\n")
        if stderr:
            sys.stderr.write(stderr)
            if not stderr.endswith("\n"):
                sys.stderr.write("\n")
        try:
            return int(result.get("exit_code") or 0)
        except json.JSONDecodeError:
            return 0

    # Failure
    err = data.get("error") or {}
    msg = err.get("message") or "Command failed."
    code = err.get("code") or NodeRunErrorCode.INVOKE_FAILED
    sys.stderr.write(f"{code}: {msg}\n")
    return 1


def register_command(subparsers: Any, parent_parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    """Register `nodes run` on an argparse subparser action.

    The function is tolerant to existing "common options" supplied by parent parsers.
    """
    parser = subparsers.add_parser(
        "run",
        help="Run a command on a node",
        parents=[parent_parser] if parent_parser is not None else [],
        add_help=True,
    )

    _add_argument_if_missing(parser, "--node", dest="node", help="Node selector (id|name|ip)")
    _add_argument_if_missing(parser, "--cwd", dest="cwd", help="Working directory")
    _add_argument_if_missing(parser, "--env", dest="env", action="append", help="Env override KEY=VAL (repeatable)")
    _add_argument_if_missing(
        parser, "--command-timeout", dest="command_timeout_ms", type=int, help="Command timeout in ms"
    )
    _add_argument_if_missing(
        parser, "--invoke-timeout", dest="invoke_timeout_ms", type=int, help="Node invoke timeout in ms"
    )
    _add_argument_if_missing(
        parser,
        "--needs-screen-recording",
        dest="needs_screen_recording",
        action="store_true",
        help="Require screen recording permission",
    )
    _add_argument_if_missing(parser, "--raw", dest="raw", help="Run a shell string")
    _add_argument_if_missing(parser, "--agent", dest="agent", help="Agent id for scoped policy")
    _add_argument_if_missing(parser, "--ask", dest="ask", choices=["off", "on-miss", "always"], help="Policy override")
    _add_argument_if_missing(
        parser, "--security", dest="security", choices=["deny", "allowlist", "full"], help="Security override"
    )

    # Common options may already exist on a parent parser.
    _add_argument_if_missing(parser, "--url", dest="url", help="Gateway base URL")
    _add_argument_if_missing(parser, "--token", dest="token", help="Gateway auth token")
    _add_argument_if_missing(parser, "--timeout", dest="timeout", type=float, default=30.0, help="HTTP timeout seconds")
    _add_argument_if_missing(
        parser, "--json", dest="json_output", action="store_true", help="Machine-readable JSON output"
    )

    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command argv (e.g. ls -la)")
    parser.set_defaults(_thomas_handler=_handle_argparse)
    return parser


# Common aliases used by different command registries.
register = register_command
register_cli = register_command
add_parser = register_command
add_subparser = register_command


def _handle_argparse(args: Any) -> int:
    try:
        argv = [c for c in (args.command or []) if c != "--"]
        req = build_request(
            node=getattr(args, "node", None),
            argv=argv if argv else None,
            raw=getattr(args, "raw", None),
            cwd=getattr(args, "cwd", None),
            env_items=getattr(args, "env", None),
            command_timeout_ms=getattr(args, "command_timeout_ms", None),
            invoke_timeout_ms=getattr(args, "invoke_timeout_ms", None),
            needs_screen_recording=bool(getattr(args, "needs_screen_recording", False)),
            agent=getattr(args, "agent", None),
            ask=getattr(args, "ask", None),
            security=getattr(args, "security", None),
        )
        return run_nodes_run(
            url=getattr(args, "url", None),
            token=getattr(args, "token", None),
            timeout_s=float(getattr(args, "timeout", 30.0)),
            json_output=bool(getattr(args, "json_output", False)),
            req=req,
        )
    except NodeCommandRunException as e:
        sys.stderr.write(f"{e.code}: {e}\n")
        return 1


# --- Typer registration (best-effort) ---------------------------------------

try:  # pragma: no cover
    import typer
except ImportError:  # pragma: no cover
    typer = None  # type: ignore


def _typer_nodes_run(
    command: list[str],
    node: str | None,
    raw: str | None,
    cwd: str | None,
    env: list[str],
    command_timeout_ms: int | None,
    invoke_timeout_ms: int | None,
    needs_screen_recording: bool,
    agent: str | None,
    ask: str | None,
    security: str | None,
) -> int:
    """Implementation for typer callback (kept separate for reuse)."""
    argv = command if command else None
    req = build_request(
        node=node,
        argv=argv,
        raw=raw,
        cwd=cwd,
        env_items=list(env) if env else None,
        command_timeout_ms=command_timeout_ms,
        invoke_timeout_ms=invoke_timeout_ms,
        needs_screen_recording=needs_screen_recording,
        agent=agent,
        ask=ask,
        security=security,
    )

    # Typer doesn't force a global config shape; use ctx.obj when present.
    if typer is not None:
        ctx = typer.get_current_context()
        obj = ctx.obj or {}
        json_output = bool(obj.get("json"))
        url = obj.get("url")
        token = obj.get("token")
        timeout_s = float(obj.get("timeout") or 30.0)
    else:
        json_output = False
        url = None
        token = None
        timeout_s = 30.0

    return run_nodes_run(url=url, token=token, timeout_s=timeout_s, json_output=json_output, req=req)


def register_typer(parent_app: Any) -> None:
    """Register the command onto an existing Typer app."""
    if typer is None:
        return

    @parent_app.command("run")
    def typer_run(
        command: list[str] = typer.Argument([], help="Command argv (e.g. ls -la)"),
        node: str | None = typer.Option(None, "--node", help="Node selector (id|name|ip)"),
        raw: str | None = typer.Option(None, "--raw", help="Run a shell string"),
        cwd: str | None = typer.Option(None, "--cwd", help="Working directory"),
        env: list[str] = typer.Option([], "--env", help="Env override KEY=VAL", show_default=False),
        command_timeout_ms: int | None = typer.Option(None, "--command-timeout", help="Command timeout in ms"),
        invoke_timeout_ms: int | None = typer.Option(None, "--invoke-timeout", help="Node invoke timeout in ms"),
        needs_screen_recording: bool = typer.Option(False, "--needs-screen-recording", help="Require screen recording"),
        agent: str | None = typer.Option(None, "--agent", help="Agent id"),
        ask: str | None = typer.Option(None, "--ask", help="Policy override"),
        security: str | None = typer.Option(None, "--security", help="Security override"),
    ) -> None:
        code = _typer_nodes_run(
            command=command,
            node=node,
            raw=raw,
            cwd=cwd,
            env=env,
            command_timeout_ms=command_timeout_ms,
            invoke_timeout_ms=invoke_timeout_ms,
            needs_screen_recording=needs_screen_recording,
            agent=agent,
            ask=ask,
            security=security,
        )
        raise typer.Exit(code)


# Export an `app` symbol when possible, for loaders that auto-mount sub-apps.
if typer is not None:  # pragma: no cover
    try:
        # Prefer an existing nodes group app if the package defines one.
        from . import app as _nodes_app  # type: ignore

        app = _nodes_app  # re-export
        register_typer(app)
    except ImportError:
        app = typer.Typer(add_completion=False)
        register_typer(app)
else:  # pragma: no cover
    app = None  # type: ignore


__all__ = [
    "DEFAULT_URL_ENV",
    "DEFAULT_TOKEN_ENV",
    "build_request",
    "run_nodes_run",
    "register_command",
    "register",
    "register_cli",
    "add_parser",
    "add_subparser",
    "register_typer",
    "app",
]
