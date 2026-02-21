"""Channel documentation generator.

This module is Thomas-native: it produces deterministic documentation for
messaging channels supported by the Thomas codebase.

Design goals:
- **Stable contracts**: clear request/result dataclasses for programmatic use.
- **Deterministic errors**: failures surface as ChannelDocsGeneratorError with a stable code.
- **Machine-readable output**: convert results to JSON-serializable payloads.
- **Low side effects**: avoid importing optional integrations when possible.

The CLI wiring lives in:
`thomas/cli/commands/channel_ops/p094_channel_docs_generator.py`
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = 1

ErrorCode = Literal[
    "INVALID_INPUT",
    "UNKNOWN_CHANNEL",
    "CONFIG_MISSING",
    "INTEGRATION_METADATA_FAILED",
    "OUTPUT_WRITE_FAILED",
]


class ChannelDocsGeneratorError(Exception):
    """Deterministic error for channel docs generation."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details: Dict[str, Any] = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "error": {
                "code": self.code,
                "message": str(self),
                "details": self.details,
            },
        }


@dataclass(frozen=True)
class ChannelConfigField:
    """A single configuration knob for a channel."""

    key: str
    kind: Literal["env", "config"]
    required: bool
    description: str
    default: Optional[str] = None


@dataclass(frozen=True)
class ChannelDoc:
    """Documentation for a single channel."""

    name: str
    title: str
    summary: str
    config: Tuple[ChannelConfigField, ...] = field(default_factory=tuple)
    examples: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ChannelDocsResult:
    """Structured output of the generator."""

    generated_at: str
    channels: Tuple[ChannelDoc, ...]


@dataclass(frozen=True)
class ChannelDocsRequest:
    """Input contract for docs generation."""

    # If provided, only these channel names will be included.
    channel_names: Optional[Tuple[str, ...]] = None

    # Optional safety/automation check: fail if required env config is missing.
    validate_required_config: bool = False

    # Optional env override (useful for tests). When omitted, `os.environ` is used.
    env: Optional[Mapping[str, str]] = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _module_origin(module_path: str) -> Optional[str]:
    """Return the filesystem path for a module without importing it."""

    spec = importlib.util.find_spec(module_path)
    if spec is None:
        return None
    origin = getattr(spec, "origin", None)
    if not origin or origin in ("built-in", "frozen"):
        return None
    return origin


def _extract_literal_string_constants(py_file: str, names: Sequence[str]) -> Dict[str, str]:
    """Extract simple module-level string constants via AST parsing.

    Only captures assignments like:
        FOO = "bar"
        FOO: str = "bar"

    Any failure returns an empty dict (docs generation should stay useful even
    if metadata extraction fails).
    """

    try:
        with open(py_file, "r", encoding="utf-8") as f:
            source = f.read()
    except OSError:
        return {}

    try:
        tree = ast.parse(source, filename=py_file)
    except SyntaxError:
        return {}

    wanted = set(names)
    found: Dict[str, str] = {}

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    found[target.id] = node.value.value
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name):
                continue
            if node.target.id not in wanted:
                continue
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                continue
            found[node.target.id] = node.value.value

    return found


def _telegram_doc() -> ChannelDoc:
    """Telegram channel docs with best-effort metadata extraction.

    We avoid importing `thomas.integrations.telegram` directly so docs generation
    does not depend on optional third-party libraries at import time.
    """

    origin = _module_origin("thomas.integrations.telegram")
    constants: Dict[str, str] = {}
    if origin and origin.endswith(".py") and os.path.exists(origin):
        constants = _extract_literal_string_constants(
            origin,
            [
                "CHANNEL_NAME",
                "CHANNEL_TITLE",
                "CHANNEL_SUMMARY",
                "TELEGRAM_BOT_TOKEN_ENV",
                "TELEGRAM_CHAT_ID_ENV",
                "BOT_TOKEN_ENV",
                "CHAT_ID_ENV",
            ],
        )

    name = constants.get("CHANNEL_NAME") or "telegram"
    title = constants.get("CHANNEL_TITLE") or "Telegram"
    summary = constants.get("CHANNEL_SUMMARY") or "Send and receive messages using the Telegram Bot API."

    # Support a couple of common constant name variants.
    bot_token_env = (
        constants.get("TELEGRAM_BOT_TOKEN_ENV")
        or constants.get("BOT_TOKEN_ENV")
        or "TELEGRAM_BOT_TOKEN"
    )
    chat_id_env = (
        constants.get("TELEGRAM_CHAT_ID_ENV")
        or constants.get("CHAT_ID_ENV")
        or "TELEGRAM_CHAT_ID"
    )

    config_fields = (
        ChannelConfigField(
            key=str(bot_token_env),
            kind="env",
            required=True,
            description="Telegram bot token (create a bot via @BotFather, then copy the token).",
        ),
        ChannelConfigField(
            key=str(chat_id_env),
            kind="env",
            required=False,
            description="Default chat/channel ID to post to (optional; can be overridden per send).",
        ),
    )

    examples = (
        'export TELEGRAM_BOT_TOKEN="123456:ABC..."',
        "thomas channels docs --channel telegram",
        "thomas channels docs --channel telegram --json",
    )

    return ChannelDoc(
        name=str(name),
        title=str(title),
        summary=str(summary),
        config=tuple(config_fields),
        examples=tuple(examples),
    )


def discover_channels() -> Tuple[ChannelDoc, ...]:
    """Discover channels supported by this Thomas build.

    This P094 implementation is intentionally conservative and documents the
    baseline Telegram integration described in the prompt context.
    """

    channels: List[ChannelDoc] = []
    if _module_origin("thomas.integrations.telegram") is not None:
        channels.append(_telegram_doc())

    channels.sort(key=lambda c: c.name)
    return tuple(channels)


def _validate_required_config(
    channels: Iterable[ChannelDoc], *, env: Optional[Mapping[str, str]]
) -> None:
    """Fail if required env config is missing."""

    env_map = env if env is not None else os.environ

    missing: List[str] = []
    for channel in channels:
        for field_doc in channel.config:
            if field_doc.kind != "env" or not field_doc.required:
                continue
            val = env_map.get(field_doc.key)
            if val is None or str(val).strip() == "":
                missing.append(field_doc.key)

    if missing:
        missing_sorted = sorted(set(missing))
        raise ChannelDocsGeneratorError(
            "CONFIG_MISSING",
            "Required configuration is missing.",
            details={"missing": missing_sorted},
        )


def generate_channel_docs(request: Optional[ChannelDocsRequest] = None) -> ChannelDocsResult:
    """Generate structured channel documentation."""

    req = request or ChannelDocsRequest()

    channels = list(discover_channels())

    if req.channel_names is not None:
        wanted = {c.strip() for c in req.channel_names if c.strip()}
        if not wanted:
            raise ChannelDocsGeneratorError(
                "INVALID_INPUT",
                "channel_names was provided but empty.",
            )

        known = {c.name for c in channels}
        unknown = sorted(wanted - known)
        if unknown:
            raise ChannelDocsGeneratorError(
                "UNKNOWN_CHANNEL",
                "Unknown channel name(s).",
                details={"unknown": unknown, "known": sorted(known)},
            )

        channels = [c for c in channels if c.name in wanted]

    if req.validate_required_config:
        _validate_required_config(channels, env=req.env)

    return ChannelDocsResult(generated_at=_utc_now_iso(), channels=tuple(channels))


def render_markdown(result: ChannelDocsResult) -> str:
    """Render docs to Markdown."""

    lines: List[str] = []
    lines.append("# Thomas Channels")
    lines.append("")
    lines.append(f"Generated: `{result.generated_at}`")
    lines.append("")
    lines.append(f"Schema version: `{SCHEMA_VERSION}`")
    lines.append("")
    if not result.channels:
        lines.append("No channels were discovered in this build.")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    for channel in result.channels:
        lines.append(f"## {channel.title}")
        lines.append("")
        lines.append(channel.summary.strip())
        lines.append("")
        lines.append(f"**Channel name:** `{channel.name}`")
        lines.append("")
        if channel.config:
            lines.append("### Configuration")
            lines.append("")
            for field_doc in sorted(channel.config, key=lambda f: (f.kind, f.key)):
                req = "required" if field_doc.required else "optional"
                default = (
                    f" (default: `{field_doc.default}`)"
                    if field_doc.default is not None
                    else ""
                )
                lines.append(
                    f"- **{field_doc.key}** ({field_doc.kind}, {req}){default}: {field_doc.description}"
                )
            lines.append("")

        if channel.examples:
            lines.append("### Examples")
            lines.append("")
            lines.append("```bash")
            for ex in channel.examples:
                lines.append(ex)
            lines.append("```")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_machine_readable(
    result: ChannelDocsResult, *, include_markdown: bool = False
) -> Dict[str, Any]:
    """Convert result into a JSON-serializable dict."""

    payload: Dict[str, Any] = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "generated_at": result.generated_at,
        "channels": [
            {
                "name": c.name,
                "title": c.title,
                "summary": c.summary,
                "config": [asdict(f) for f in c.config],
                "examples": list(c.examples),
            }
            for c in result.channels
        ],
    }
    if include_markdown:
        payload["markdown"] = render_markdown(result)
    return payload


def dumps_json(data: Mapping[str, Any]) -> str:
    """Deterministic JSON dump."""

    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def normalize_channel_names(value: Optional[str]) -> Optional[Tuple[str, ...]]:
    """Parse a comma-separated channel list into a tuple."""

    if value is None:
        return None
    names = [part.strip() for part in value.split(",")]
    names = [n for n in names if n]
    return tuple(names)


def validate_output_path(path: Optional[str]) -> None:
    if path is None:
        return
    if not str(path).strip():
        raise ChannelDocsGeneratorError("INVALID_INPUT", "Output path was empty.")


def write_text_file(path: str, content: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as exc:  # pragma: no cover
        raise ChannelDocsGeneratorError(
            "OUTPUT_WRITE_FAILED",
            "Failed to write output file.",
            details={"path": path, "reason": repr(exc)},
        ) from exc
