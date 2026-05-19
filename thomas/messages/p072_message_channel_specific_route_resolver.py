"""Message channel specific route resolver.

Thomas supports multiple messaging channels. When an inbound message arrives, we
need a deterministic way to choose **which internal assistant** should process
it.

This module implements that routing decision as a pure function:

    resolve_message_route(context, config) -> MessageRouteResolution

The decision is rule-based and ordered by specificity. Rules can match on:

- channel
- account id (when a channel has multiple accounts)
- peer (direct / group / channel, and its id)
- parent peer (thread inheritance)
- Discord guild + roles
- Slack team

The resolver is intentionally strict:
- invalid input raises a deterministic, machine-readable exception
- invalid / missing configuration raises a deterministic, machine-readable
  exception

The CLI wrapper for this module lives at:
`thomas/cli/commands/messages/p072_message_channel_specific_route_resolver.py`.

Note on naming
--------------
This is Thomas-native routing terminology. The module *accepts* several common
field spellings (snake_case and camelCase) to make integration easier, but the
public dataclasses use a consistent Thomas naming style.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteErrorPayload:
    """Machine-readable error details."""

    code: str
    message: str
    details: Mapping[str, Any]


class MessageRouteResolutionError(Exception):
    """Base error for deterministic routing failures."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.payload = RouteErrorPayload(code=code, message=message, details=details or {})
        super().__init__(f"{code}: {message}")

    @property
    def code(self) -> str:  # pragma: no cover
        return self.payload.code

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.payload.code,
                "message": self.payload.message,
                "details": dict(self.payload.details),
            },
        }


class InvalidRouteInputError(MessageRouteResolutionError):
    """The provided context is malformed or missing required fields."""


class InvalidRouteConfigError(MessageRouteResolutionError):
    """The routing config is missing required structure or refers to unknown assistants."""


class RouteNotFoundError(MessageRouteResolutionError):
    """No matching rule exists and no default assistant can be selected."""


class RouteExternalFailureError(MessageRouteResolutionError):
    """A file read / JSON parse failed."""


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MessagePeer:
    """A normalized identifier for a conversation endpoint."""

    kind: str
    id: str


@dataclass(frozen=True)
class MessageRouteContext:
    """Inputs used to select an assistant for an inbound message."""

    channel: str
    account_id: str | None = None
    peer: MessagePeer | None = None
    parent_peer: MessagePeer | None = None
    guild_id: str | None = None
    roles: tuple[str, ...] | None = None
    team_id: str | None = None


@dataclass(frozen=True)
class AssistantDefinition:
    """A routable assistant."""

    assistant_id: str
    is_default: bool = False


@dataclass(frozen=True)
class RouteMatch:
    """A rule match clause.

    All populated fields must match the inbound context (AND semantics).
    """

    channel: str
    account_id: str | None = None
    peer: MessagePeer | None = None
    guild_id: str | None = None
    roles: tuple[str, ...] | None = None
    team_id: str | None = None


@dataclass(frozen=True)
class RoutingRule:
    """A rule mapping a match clause to a destination assistant."""

    assistant_id: str
    match: RouteMatch


@dataclass(frozen=True)
class RoutingConfig:
    """Routing configuration."""

    assistants: tuple[AssistantDefinition, ...]
    rules: tuple[RoutingRule, ...]


@dataclass(frozen=True)
class MessageRouteResolution:
    """Successful route resolution output."""

    assistant_id: str
    tier: str
    rule_index: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "resolution": {
                "assistant_id": self.assistant_id,
                "tier": self.tier,
                "rule_index": self.rule_index,
            },
        }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _require_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRouteInputError(
            "invalid_input",
            f"Field '{field}' must be a non-empty string.",
            details={"field": field},
        )
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    return None


def _coerce_roles(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        roles: list[str] = []
        for i, v in enumerate(value):
            if not isinstance(v, str) or not v:
                raise InvalidRouteInputError(
                    "invalid_input",
                    "roles must be a list of non-empty strings.",
                    details={"index": i},
                )
            roles.append(v)
        return tuple(roles)
    raise InvalidRouteInputError(
        "invalid_input",
        "roles must be a list of strings.",
        details={"type": type(value).__name__},
    )


def _parse_peer(value: Any, *, field: str) -> MessagePeer | None:
    if value is None:
        return None
    if isinstance(value, MessagePeer):
        return value
    if isinstance(value, Mapping):
        kind = _require_str(value.get("kind"), field=f"{field}.kind")
        pid = _require_str(value.get("id"), field=f"{field}.id")
        return MessagePeer(kind=kind, id=pid)
    raise InvalidRouteInputError(
        "invalid_input",
        f"Field '{field}' must be an object with 'kind' and 'id'.",
        details={"field": field, "type": type(value).__name__},
    )


def _get(obj: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in obj:
            return obj[k]
    return None


def parse_routing_config(raw: Mapping[str, Any]) -> RoutingConfig:
    """Parse a routing config from a mapping.

    Supports multiple spellings to ease integration:

    Assistants:
      - {"assistants": [{"id": "main", "default": true}, ...]}
      - {"agents": {"list": [{"id": "main", "default": true}, ...]}}

    Rules:
      - {"routing_rules": [{"assistant_id": "main", "match": {...}}, ...]}
      - {"rules": [...]}  # alias
      - {"bindings": [{"agentId": "main", "match": {...}}, ...]}  # compatibility
    """

    if not isinstance(raw, Mapping):
        raise InvalidRouteConfigError(
            "invalid_config",
            "Config must be a mapping/object.",
            details={"type": type(raw).__name__},
        )

    # ---- assistants
    assistants_raw = _get(raw, "assistants")
    if assistants_raw is None:
        agents = _get(raw, "agents")
        if isinstance(agents, Mapping):
            assistants_raw = _get(agents, "list", "agents")

    if not isinstance(assistants_raw, list) or not assistants_raw:
        raise InvalidRouteConfigError(
            "invalid_config",
            "Config must include a non-empty assistants list.",
            details={"expected": "assistants: [..]"},
        )

    assistants: list[AssistantDefinition] = []
    for idx, a in enumerate(assistants_raw):
        if not isinstance(a, Mapping):
            raise InvalidRouteConfigError(
                "invalid_config",
                "Each assistant must be an object.",
                details={"index": idx},
            )
        assistant_id = _optional_str(_get(a, "assistant_id", "assistantId", "id"))
        if not assistant_id:
            raise InvalidRouteConfigError(
                "invalid_config",
                "Assistant is missing an id.",
                details={"index": idx},
            )
        is_default = bool(_get(a, "default", "is_default", "isDefault"))
        assistants.append(AssistantDefinition(assistant_id=assistant_id, is_default=is_default))

    assistant_ids = {a.assistant_id for a in assistants}

    # ---- rules
    rules_raw = _get(raw, "routing_rules", "rules")
    if rules_raw is None:
        rules_raw = _get(raw, "bindings")

    if rules_raw is None:
        # Allow empty rules (all messages go to default assistant)
        rules_raw = []

    if not isinstance(rules_raw, list):
        raise InvalidRouteConfigError(
            "invalid_config",
            "Rules must be a list.",
            details={"type": type(rules_raw).__name__},
        )

    rules: list[RoutingRule] = []
    for idx, r in enumerate(rules_raw):
        if not isinstance(r, Mapping):
            raise InvalidRouteConfigError(
                "invalid_config",
                "Each rule must be an object.",
                details={"index": idx},
            )

        # The destination assistant id can be spelled multiple ways.
        assistant_id = _optional_str(_get(r, "assistant_id", "assistantId", "agentId", "agent_id"))
        if not assistant_id:
            raise InvalidRouteConfigError(
                "invalid_config",
                "Rule is missing assistant_id.",
                details={"index": idx},
            )
        if assistant_id not in assistant_ids:
            raise InvalidRouteConfigError(
                "invalid_config",
                "Rule references an unknown assistant.",
                details={"index": idx, "assistant_id": assistant_id},
            )

        match_raw = _get(r, "match")
        if not isinstance(match_raw, Mapping):
            raise InvalidRouteConfigError(
                "invalid_config",
                "Rule.match must be an object.",
                details={"index": idx},
            )

        channel = _optional_str(_get(match_raw, "channel"))
        if not channel:
            raise InvalidRouteConfigError(
                "invalid_config",
                "Rule.match.channel is required.",
                details={"index": idx},
            )

        account_id = _optional_str(_get(match_raw, "account_id", "accountId"))
        peer = _parse_peer(_get(match_raw, "peer"), field="match.peer")
        guild_id = _optional_str(_get(match_raw, "guild_id", "guildId"))
        roles = _coerce_roles(_get(match_raw, "roles"))
        team_id = _optional_str(_get(match_raw, "team_id", "teamId"))

        rules.append(
            RoutingRule(
                assistant_id=assistant_id,
                match=RouteMatch(
                    channel=channel,
                    account_id=account_id,
                    peer=peer,
                    guild_id=guild_id,
                    roles=roles,
                    team_id=team_id,
                ),
            )
        )

    return RoutingConfig(assistants=tuple(assistants), rules=tuple(rules))


def load_routing_config(path: str | Path) -> RoutingConfig:
    """Load routing config from a JSON file."""

    try:
        raw_text = Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as e:
        raise RouteExternalFailureError(
            "config_read_failed",
            "Failed to read config file.",
            details={"path": str(path), "os_error": e.__class__.__name__},
        ) from e

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RouteExternalFailureError(
            "config_parse_failed",
            "Config file is not valid JSON.",
            details={"path": str(path), "line": e.lineno, "col": e.colno},
        ) from e

    return parse_routing_config(raw)


# ---------------------------------------------------------------------------
# Matching + resolution
# ---------------------------------------------------------------------------


def _roles_match(required: tuple[str, ...], available: tuple[str, ...] | None) -> bool:
    if available is None:
        return False
    # Require all specified roles to be present.
    available_set = set(available)
    return all(r in available_set for r in required)


def _match_clause(rule: RoutingRule, ctx: MessageRouteContext) -> bool:
    m = rule.match

    if m.channel != ctx.channel:
        return False

    if m.account_id is not None:
        if m.account_id == "*":
            # wildcard matches any account
            pass
        else:
            if ctx.account_id is None or ctx.account_id != m.account_id:
                return False

    if m.peer is not None:
        if ctx.peer is None:
            return False
        if m.peer.kind != ctx.peer.kind or m.peer.id != ctx.peer.id:
            return False

    if m.guild_id is not None:
        if ctx.guild_id is None or ctx.guild_id != m.guild_id:
            return False

    if m.roles is not None:
        if not _roles_match(m.roles, ctx.roles):
            return False

    if m.team_id is not None:
        if ctx.team_id is None or ctx.team_id != m.team_id:
            return False

    return True


def _default_assistant(config: RoutingConfig) -> str:
    if not config.assistants:
        raise InvalidRouteConfigError(
            "invalid_config",
            "No assistants are configured.",
            details={},
        )

    for a in config.assistants:
        if a.is_default:
            return a.assistant_id

    # Deterministic fallback: first assistant
    return config.assistants[0].assistant_id


def resolve_message_route(ctx: MessageRouteContext, config: RoutingConfig) -> MessageRouteResolution:
    """Resolve the destination assistant for an inbound message.

    The resolver walks the configured rules by precedence tiers. Within a tier,
    the first rule in configuration order wins.

    Precedence tiers:
      1. exact peer match
      2. parent peer match (thread inheritance)
      3. guild + roles match
      4. guild match
      5. team match
      6. account match
      7. channel-only match (account wildcard)
      8. default assistant
    """

    if not isinstance(ctx, MessageRouteContext):
        raise InvalidRouteInputError(
            "invalid_input",
            "ctx must be a MessageRouteContext.",
            details={"type": type(ctx).__name__},
        )

    if not ctx.channel or not isinstance(ctx.channel, str):
        raise InvalidRouteInputError(
            "invalid_input",
            "ctx.channel must be a non-empty string.",
            details={},
        )

    # --- Tier 1: exact peer match
    if ctx.peer is not None:
        for idx, rule in enumerate(config.rules):
            if rule.match.peer is None:
                continue
            if rule.match.peer.kind == ctx.peer.kind and rule.match.peer.id == ctx.peer.id:
                if _match_clause(rule, ctx):
                    return MessageRouteResolution(
                        assistant_id=rule.assistant_id,
                        tier="peer",
                        rule_index=idx,
                    )

    # --- Tier 2: parent peer match
    if ctx.parent_peer is not None:
        # Build a synthetic context where peer is the parent peer.
        parent_ctx = MessageRouteContext(
            channel=ctx.channel,
            account_id=ctx.account_id,
            peer=ctx.parent_peer,
            parent_peer=None,
            guild_id=ctx.guild_id,
            roles=ctx.roles,
            team_id=ctx.team_id,
        )
        for idx, rule in enumerate(config.rules):
            if rule.match.peer is None:
                continue
            if rule.match.peer.kind == ctx.parent_peer.kind and rule.match.peer.id == ctx.parent_peer.id:
                if _match_clause(rule, parent_ctx):
                    return MessageRouteResolution(
                        assistant_id=rule.assistant_id,
                        tier="parent_peer",
                        rule_index=idx,
                    )

    # --- Tier 3: guild + roles
    if ctx.guild_id is not None and ctx.roles is not None:
        for idx, rule in enumerate(config.rules):
            if rule.match.guild_id is None or rule.match.roles is None:
                continue
            if rule.match.guild_id == ctx.guild_id and _roles_match(rule.match.roles, ctx.roles):
                if _match_clause(rule, ctx):
                    return MessageRouteResolution(
                        assistant_id=rule.assistant_id,
                        tier="guild_roles",
                        rule_index=idx,
                    )

    # --- Tier 4: guild
    if ctx.guild_id is not None:
        for idx, rule in enumerate(config.rules):
            if rule.match.guild_id is None:
                continue
            if rule.match.guild_id == ctx.guild_id:
                if _match_clause(rule, ctx):
                    return MessageRouteResolution(
                        assistant_id=rule.assistant_id,
                        tier="guild",
                        rule_index=idx,
                    )

    # --- Tier 5: team
    if ctx.team_id is not None:
        for idx, rule in enumerate(config.rules):
            if rule.match.team_id is None:
                continue
            if rule.match.team_id == ctx.team_id:
                if _match_clause(rule, ctx):
                    return MessageRouteResolution(
                        assistant_id=rule.assistant_id,
                        tier="team",
                        rule_index=idx,
                    )

    # --- Tier 6: account
    if ctx.account_id is not None:
        for idx, rule in enumerate(config.rules):
            if rule.match.account_id is None:
                continue
            if rule.match.account_id == ctx.account_id:
                if _match_clause(rule, ctx):
                    return MessageRouteResolution(
                        assistant_id=rule.assistant_id,
                        tier="account",
                        rule_index=idx,
                    )

    # --- Tier 7: channel-only match (account wildcard or missing)
    for idx, rule in enumerate(config.rules):
        # A channel-only rule is any rule without peer/guild/team/roles and with
        # account_id either unset or wildcard.
        if rule.match.channel != ctx.channel:
            continue
        if (
            rule.match.peer is not None
            or rule.match.guild_id is not None
            or rule.match.roles is not None
            or rule.match.team_id is not None
        ):
            continue
        if rule.match.account_id not in (None, "*"):
            continue
        if _match_clause(rule, ctx):
            return MessageRouteResolution(
                assistant_id=rule.assistant_id,
                tier="channel",
                rule_index=idx,
            )

    # --- Tier 8: default
    default_id = _default_assistant(config)
    if default_id:
        return MessageRouteResolution(
            assistant_id=default_id,
            tier="default",
            rule_index=None,
        )

    raise RouteNotFoundError(
        "route_not_found",
        "No routing rule matched and no default assistant could be selected.",
        details={"channel": ctx.channel},
    )


# ---------------------------------------------------------------------------
# JSON schema helpers (for automation)
# ---------------------------------------------------------------------------


def route_resolution_json_schema() -> dict[str, Any]:
    """Return a JSON schema for the `--json` output payload."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Thomas message route resolution",
        "type": "object",
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "ok": {"const": True},
                    "resolution": {
                        "type": "object",
                        "properties": {
                            "assistant_id": {"type": "string"},
                            "tier": {"type": "string"},
                            "rule_index": {"type": ["integer", "null"]},
                        },
                        "required": ["assistant_id", "tier", "rule_index"],
                        "additionalProperties": False,
                    },
                },
                "required": ["ok", "resolution"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "ok": {"const": False},
                    "error": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string"},
                            "message": {"type": "string"},
                            "details": {"type": "object"},
                        },
                        "required": ["code", "message", "details"],
                        "additionalProperties": False,
                    },
                },
                "required": ["ok", "error"],
                "additionalProperties": False,
            },
        ],
    }


def context_from_mapping(raw: Mapping[str, Any]) -> MessageRouteContext:
    """Parse a MessageRouteContext from a mapping.

    Supports both snake_case and camelCase keys.
    """

    if not isinstance(raw, Mapping):
        raise InvalidRouteInputError(
            "invalid_input",
            "Context must be an object.",
            details={"type": type(raw).__name__},
        )

    channel = _optional_str(_get(raw, "channel"))
    if not channel:
        raise InvalidRouteInputError(
            "invalid_input",
            "Context.channel is required.",
            details={},
        )

    account_id = _optional_str(_get(raw, "account_id", "accountId"))
    peer = _parse_peer(_get(raw, "peer"), field="peer")
    parent_peer = _parse_peer(_get(raw, "parent_peer", "parentPeer"), field="parent_peer")
    guild_id = _optional_str(_get(raw, "guild_id", "guildId"))
    roles = _coerce_roles(_get(raw, "roles"))
    team_id = _optional_str(_get(raw, "team_id", "teamId"))

    return MessageRouteContext(
        channel=channel,
        account_id=account_id,
        peer=peer,
        parent_peer=parent_peer,
        guild_id=guild_id,
        roles=roles,
        team_id=team_id,
    )
