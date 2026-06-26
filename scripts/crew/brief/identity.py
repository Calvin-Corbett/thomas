#!/usr/bin/env python3
"""Shared agent identity resolution helpers for CLI coordination scripts."""

from __future__ import annotations

import argparse
import json
import os
import sys

AGENT_ID_ENV_KEYS: tuple[str, ...] = (
    "THOMAS_AGENT_ID",
    "AGENT_ID",
    "CODEX_AGENT_ID",
    "GEMINI_AGENT_ID",
    "CLAUDE_AGENT_ID",
)

AGENT_NAME_ENV_KEYS: tuple[str, ...] = (
    "THOMAS_AGENT_NAME",
    "CODEX_AGENT_NAME",
    "AGENT_NAME",
)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def resolve_agent_source(
    explicit_agent: str | None,
    *,
    include_name_fallback: bool = True,
) -> tuple[str | None, str | None]:
    """Resolve agent id/name and report where it came from."""
    explicit = _clean(explicit_agent)
    if explicit:
        return explicit, "explicit"

    for key in AGENT_ID_ENV_KEYS:
        value = _clean(os.getenv(key))
        if value:
            return value, key

    if include_name_fallback:
        for key in AGENT_NAME_ENV_KEYS:
            value = _clean(os.getenv(key))
            if value:
                return value, key

    return None, None


def resolve_agent(
    explicit_agent: str | None,
    *,
    include_name_fallback: bool = True,
) -> str | None:
    """Resolve agent id/name from explicit argument, then env vars."""
    agent, _source = resolve_agent_source(
        explicit_agent,
        include_name_fallback=include_name_fallback,
    )
    return agent


def resolution_help(*, include_name_fallback: bool = True) -> str:
    keys = list(AGENT_ID_ENV_KEYS)
    if include_name_fallback:
        keys.extend(AGENT_NAME_ENV_KEYS)
    return "/".join(keys)


def identity_with_env(
    explicit_agent: str | None,
    *,
    include_name_fallback: bool = True,
) -> dict[str, str | None]:
    """Return the resolved identity plus the source used for audit logs."""
    agent, source = resolve_agent_source(
        explicit_agent,
        include_name_fallback=include_name_fallback,
    )
    return {
        "agent": agent,
        "source": source,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve the current Thomas agent identity.")
    parser.add_argument(
        "--agent",
        default=None,
        help="Explicit agent id/name. Takes precedence over identity environment variables.",
    )
    parser.add_argument(
        "--no-name-fallback",
        action="store_true",
        help="Do not fall back from *_AGENT_ID variables to *_AGENT_NAME variables.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a structured JSON payload.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    include_name_fallback = not bool(args.no_name_fallback)
    payload = identity_with_env(
        args.agent,
        include_name_fallback=include_name_fallback,
    )
    agent = payload["agent"]
    if agent:
        if args.json:
            print(json.dumps({"ok": True, **payload}, sort_keys=True))
        else:
            print(agent)
        return 0

    help_text = resolution_help(include_name_fallback=include_name_fallback)
    error = f"agent identity unavailable; pass --agent or set {help_text}"
    if args.json:
        print(json.dumps({"ok": False, "error": error, **payload}, sort_keys=True))
    else:
        print(error, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
