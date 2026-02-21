"""CLI command: P071 - message voice metadata stub.

This command emits a placeholder voice-metadata payload for a message. It is a
*stub* on purpose: it avoids network fetches and expensive decoding, and instead
returns a stable schema that future implementations can extend.

Machine-readable output: --json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Mapping, Optional

from thomas.messages.p071_message_voice_metadata_stub import (
    VoiceMetadataStubError,
    VoiceMetadataStubRequest,
    create_voice_metadata_stub,
)

PROMPT_ID = "P071"
COMMAND_GROUP = "message"
COMMAND_NAME = "voice-metadata-stub"
HELP = "Emit a stub voice-metadata payload for a message."


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--message-id", required=True, help="Message identifier.")
    parser.add_argument(
        "--audio-path",
        default=None,
        help="Local audio file path. WAV is best-effort inspected via stdlib.",
    )
    parser.add_argument(
        "--audio-url",
        default=None,
        help="Remote URL. Not fetched; requires explicit config/policy gate.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output (recommended for automation).",
    )
    parser.set_defaults(_thomas_handler=run_from_parsed_args)


def build_parser(subparsers: Optional[argparse._SubParsersAction] = None) -> argparse.ArgumentParser:
    if subparsers is None:
        parser = argparse.ArgumentParser(prog=f"{COMMAND_GROUP} {COMMAND_NAME}", description=HELP)
    else:
        parser = subparsers.add_parser(COMMAND_NAME, help=HELP, description=HELP)

    configure_parser(parser)
    return parser


# Common aliases some loaders look for.
register = build_parser
add_parser = build_parser


def _load_config_best_effort() -> Optional[Mapping[str, Any]]:
    """
    Thomas has multiple runtime surfaces for config; this is best-effort.
    If no config surface exists, returns None (and URL mode will error deterministically).
    """
    # Import lazily to avoid hard coupling.
    candidates = [
        ("thomas.cli.parity_compat", ("get_config", "load_config", "CONFIG", "settings")),
        ("thomas.config", ("get_config", "load_config", "CONFIG", "settings")),
    ]

    for mod_name, attrs in candidates:
        try:
            mod = __import__(mod_name, fromlist=["*"])
        except Exception:
            continue
        for attr in attrs:
            if not hasattr(mod, attr):
                continue
            value = getattr(mod, attr)
            try:
                cfg = value() if callable(value) else value
            except Exception:
                cfg = None
            if isinstance(cfg, Mapping):
                return cfg
            # allow "settings" objects that behave like mappings via __dict__
            if cfg is not None and hasattr(cfg, "__dict__"):
                return cfg.__dict__  # type: ignore[return-value]
    return None


def run_from_parsed_args(args: argparse.Namespace) -> int:
    req = VoiceMetadataStubRequest(
        message_id=args.message_id,
        audio_path=args.audio_path,
        audio_url=args.audio_url,
    )

    cfg = _load_config_best_effort()

    try:
        result = create_voice_metadata_stub(req, config=cfg)
    except VoiceMetadataStubError as e:
        return _emit_error(e, json_mode=bool(args.json))

    payload: Dict[str, Any] = {"ok": True, "result": result.to_dict()}
    if args.json:
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    else:
        _print_human(result.to_dict())
    return 0


# Some loaders look for `run(args)`.
run = run_from_parsed_args


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "_thomas_handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2
    return int(handler(args))


def _emit_error(err: VoiceMetadataStubError, *, json_mode: bool) -> int:
    payload: Dict[str, Any] = {"ok": False, "error": err.to_dict()}
    if json_mode:
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    else:
        sys.stderr.write(f"ERROR[{err.code}]: {err}\n")
    return 2


def _print_human(result_dict: Mapping[str, Any]) -> None:
    sys.stdout.write(f"message_id: {result_dict.get('message_id')}\n")
    sys.stdout.write(f"stub: {result_dict.get('is_stub')}\n")
    sys.stdout.write(f"source: {result_dict.get('source')}\n")
    sys.stdout.write(f"metadata: {result_dict.get('metadata')}\n")
    warnings = result_dict.get("warnings") or []
    if warnings:
        sys.stdout.write(f"warnings: {warnings}\n")
