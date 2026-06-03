from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from thomas.channels.p088_channel_secret_resolution_precedence import (
    ChannelSecretRequest,
    SecretResolutionError,
    resolve_channel_secret,
)

# The primary name is derived from the prompt id so it can be deterministically
# discovered in automation, while still offering shorter aliases for humans.
_COMMAND = "p088-channel-secret-resolution-precedence"
_ALIASES: Sequence[str] = (
    "secret-precedence",
    "channel-secret-precedence",
    "channel-secret-resolution-precedence",
    "p088-secret-precedence",
    "p088-channel-secret-precedence",
)

OP_ID = "p088"

COMMAND_NAME = _COMMAND
COMMAND_ALIASES = _ALIASES


def register(subparsers: Any) -> None:
    """Register the channel secret precedence helper under `thomas channels`."""

    if not hasattr(subparsers, "add_parser"):
        raise TypeError("Expected an argparse subparsers object with add_parser().")

    kwargs = {
        "help": "Resolve which channel secret would be used, following Thomas precedence rules.",
        "description": (
            "Resolve which secret value would be used, following Thomas precedence rules. "
            "This is primarily for debugging automation configuration."
        ),
    }

    # argparse supports aliases in modern Python, but be defensive.
    try:
        parser = subparsers.add_parser(_COMMAND, aliases=list(_ALIASES), **kwargs)
    except TypeError:
        parser = subparsers.add_parser(_COMMAND, **kwargs)

    parser.add_argument("provider", help="Channel provider/integration name (e.g., telegram).")
    parser.add_argument("secret_key", help="Which secret is being resolved (e.g., token).")

    parser.add_argument(
        "--cli",
        dest="cli_spec",
        help="Secret spec provided explicitly (highest precedence).",
    )
    parser.add_argument(
        "--channel",
        dest="channel_spec",
        help="Secret spec from channel configuration.",
    )
    parser.add_argument(
        "--config",
        dest="config_spec",
        help="Secret spec from global/integration configuration.",
    )
    parser.add_argument(
        "--env",
        dest="env_var_names",
        action="append",
        default=None,
        help="Environment variable name(s) to check (can be provided multiple times).",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow empty secrets (default: treat empty as an error).",
    )

    # JSON mode: try to add --json if the parent parser didn't already define it.
    try:
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    except argparse.ArgumentError:
        # Option already exists on an ancestor parser.
        pass

    parser.set_defaults(func=_run)


# Compatibility aliases for possible dispatcher conventions.
register_command = register
add_parser = register


def _run(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    env_names = tuple(args.env_var_names or ())

    req = ChannelSecretRequest(
        provider=str(args.provider),
        secret_key=str(args.secret_key),
        cli_spec=args.cli_spec,
        channel_spec=args.channel_spec,
        config_spec=args.config_spec,
        env_var_names=env_names,
        allow_empty=bool(args.allow_empty),
    )

    try:
        res = resolve_channel_secret(req)
    except SecretResolutionError as e:
        payload = e.to_dict()
        if json_mode:
            sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        else:
            err = payload.get("error", {})
            sys.stderr.write(f"ERROR [{err.get('code')}]: {err.get('message')}\n")
        return 2

    # include_secret=False => payload["secret"] is already redacted
    # (masked to the last few characters by ChannelSecretResolution.to_dict),
    # so the value emitted here is never the clear-text secret.
    payload = res.to_dict(include_secret=False)
    if json_mode:
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    else:
        masked_secret = payload["secret"]  # redacted representation, not the real value
        sys.stdout.write(
            " ".join(
                [
                    f"provider={payload['provider']}",
                    f"secret_key={payload['secret_key']}",
                    f"source={payload['source']}",
                    f"secret={masked_secret}",
                ]
            )
            + "\n"
        )
    return 0
