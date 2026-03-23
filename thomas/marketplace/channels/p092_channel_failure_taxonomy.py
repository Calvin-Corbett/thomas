from __future__ import annotations

"""Channel failure taxonomy (P092).

This module defines a small, stable set of failure categories for outbound
messaging channels (Telegram, etc.) and a deterministic classifier that maps a
structured failure event to one of those categories.

The intent is provider-agnostic automation: retries, fallbacks, alert routing,
and dashboards should not need to parse raw provider error strings.

Notes:
- The classifier is *best effort* but deterministic.
- The taxonomy is stable; channel-specific guidance may adjust remediation text
  but does not introduce new categories.
"""

import json
import re
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypedDict

__all__ = [
    "FailureCategory",
    "FailureSeverity",
    "FailureEvent",
    "FailureTaxonomyRequest",
    "FailureCategoryInfo",
    "FailureClassification",
    "FailureTaxonomyReport",
    "ChannelFailureTaxonomyError",
    "InvalidTaxonomyInputError",
    "MissingChannelConfigError",
    "ChannelExternalFailureError",
    "taxonomy_schema",
    "build_failure_taxonomy_report",
    "classify_failure_event",
    "parse_event_json",
]


class FailureCategory(str, Enum):
    """Canonical channel failure categories.

    Keep this list small and stable; automation depends on it.
    """

    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    DESTINATION_NOT_FOUND = "destination_not_found"
    INVALID_PAYLOAD = "invalid_payload"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NETWORK = "network"
    REMOTE_SERVICE = "remote_service"
    UNKNOWN = "unknown"


class FailureSeverity(str, Enum):
    """Severity indicates whether a failure is likely transient or permanent."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class FailureEvent(TypedDict, total=False):
    """A structured description of a channel failure.

    Producers may include arbitrary keys; the classifier looks at a few common
    ones. Extra keys are preserved in `details` and ignored by default.
    """

    message: str
    error: str
    exception_type: str
    exception: str
    http_status: int
    status_code: int
    retry_after: int
    retry_after_seconds: int
    details: Mapping[str, Any]


@dataclass(frozen=True)
class FailureTaxonomyRequest:
    """Input contract for generating a taxonomy report."""

    channel: str | None = None
    event: Mapping[str, Any] | None = None
    probe: bool = False
    config: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class FailureCategoryInfo:
    """A single category entry in the taxonomy."""

    category: FailureCategory
    title: str
    description: str
    severity: FailureSeverity
    retryable: bool
    remediation: str


@dataclass(frozen=True)
class FailureClassification:
    """Output contract describing how an event was classified."""

    category: FailureCategory
    severity: FailureSeverity
    retryable: bool
    rationale: str
    signals: Mapping[str, Any]


@dataclass(frozen=True)
class FailureTaxonomyReport:
    """Output contract for the channel failure taxonomy operation."""

    ok: bool
    channel: str | None
    taxonomy: Sequence[FailureCategoryInfo]
    classification: FailureClassification | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "channel": self.channel,
            "taxonomy": [
                {
                    "category": entry.category.value,
                    "title": entry.title,
                    "description": entry.description,
                    "severity": entry.severity.value,
                    "retryable": entry.retryable,
                    "remediation": entry.remediation,
                }
                for entry in self.taxonomy
            ],
            "classification": None
            if self.classification is None
            else {
                "category": self.classification.category.value,
                "severity": self.classification.severity.value,
                "retryable": self.classification.retryable,
                "rationale": self.classification.rationale,
                "signals": dict(self.classification.signals),
            },
        }


class ChannelFailureTaxonomyError(RuntimeError):
    """Deterministic, machine-friendly error for taxonomy operations."""

    error_code: str = "channel_failure_taxonomy_error"
    exit_code: int = 1

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.error_code,
                "message": str(self),
                "details": self.details,
            },
        }


class InvalidTaxonomyInputError(ChannelFailureTaxonomyError):
    error_code = "invalid_input"
    exit_code = 2


class MissingChannelConfigError(ChannelFailureTaxonomyError):
    error_code = "missing_config"
    exit_code = 3


class ChannelExternalFailureError(ChannelFailureTaxonomyError):
    error_code = "external_failure"
    exit_code = 4


def taxonomy_schema() -> Mapping[str, Any]:
    """Return a JSON schema for the operation result.

    The operation emits either a success payload (ok=true) or an error payload
    (ok=false). This schema models both.
    """

    categories = [c.value for c in FailureCategory]
    severities = [s.value for s in FailureSeverity]

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ChannelFailureTaxonomyResult",
        "oneOf": [
            {
                "type": "object",
                "required": ["ok", "channel", "taxonomy", "classification"],
                "properties": {
                    "ok": {"const": True},
                    "channel": {"type": ["string", "null"]},
                    "taxonomy": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "category",
                                "title",
                                "description",
                                "severity",
                                "retryable",
                                "remediation",
                            ],
                            "properties": {
                                "category": {"type": "string", "enum": categories},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "severity": {"type": "string", "enum": severities},
                                "retryable": {"type": "boolean"},
                                "remediation": {"type": "string"},
                            },
                        },
                    },
                    "classification": {
                        "type": ["object", "null"],
                        "required": ["category", "severity", "retryable", "rationale", "signals"],
                        "properties": {
                            "category": {"type": "string", "enum": categories},
                            "severity": {"type": "string", "enum": severities},
                            "retryable": {"type": "boolean"},
                            "rationale": {"type": "string"},
                            "signals": {"type": "object"},
                        },
                    },
                },
            },
            {
                "type": "object",
                "required": ["ok", "error"],
                "properties": {
                    "ok": {"const": False},
                    "error": {
                        "type": "object",
                        "required": ["code", "message", "details"],
                        "properties": {
                            "code": {"type": "string"},
                            "message": {"type": "string"},
                            "details": {"type": "object"},
                        },
                    },
                },
            },
        ],
    }


def build_failure_taxonomy_report(request: FailureTaxonomyRequest) -> FailureTaxonomyReport:
    """Generate a taxonomy report and optionally classify an event.

    If `probe=True`, performs an offline-safe config validation for supported
    channels. Probing never performs network calls.
    """

    channel = _normalize_channel(request.channel)

    if request.probe:
        _validate_probe_inputs(channel=channel, config=request.config)
        _probe_channel(channel=channel or "", config=request.config or {})

    taxonomy = _taxonomy_for_channel(channel)

    classification: FailureClassification | None = None
    if request.event is not None:
        classification = classify_failure_event(channel=channel, event=request.event)

    return FailureTaxonomyReport(
        ok=True,
        channel=channel,
        taxonomy=taxonomy,
        classification=classification,
    )


def classify_failure_event(*, channel: str | None, event: Mapping[str, Any]) -> FailureClassification:
    """Classify a structured failure event into a canonical category."""

    if not isinstance(event, Mapping):
        raise InvalidTaxonomyInputError(
            "Failure event must be a JSON object (mapping).",
            details={"received_type": type(event).__name__},
        )

    details = event.get("details")
    details_map: Mapping[str, Any] = details if isinstance(details, Mapping) else {}

    message = _first_str(
        event.get("message"),
        event.get("error"),
        details_map.get("message"),
        details_map.get("error"),
        event.get("exception"),
        details_map.get("exception"),
    )
    message_l = message.lower()

    exception_type = _first_str(
        event.get("exception_type"),
        details_map.get("exception_type"),
        event.get("exception"),
        details_map.get("exception"),
    )
    exception_l = exception_type.lower()

    http_status = _coerce_int(
        _first_not_none(
            event.get("http_status"),
            event.get("status_code"),
            details_map.get("http_status"),
            details_map.get("status_code"),
        )
    )

    retry_after = _coerce_int(
        _first_not_none(
            event.get("retry_after"),
            event.get("retry_after_seconds"),
            details_map.get("retry_after"),
            details_map.get("retry_after_seconds"),
        )
    )
    if retry_after is None:
        retry_after = _extract_retry_after_from_message(message_l)

    signals: MutableMapping[str, Any] = {}
    if channel:
        signals["channel"] = channel
    if http_status is not None:
        signals["http_status"] = http_status
    if exception_type:
        signals["exception_type"] = exception_type
    if retry_after is not None:
        signals["retry_after_seconds"] = retry_after

    # ---- Rules (ordered by specificity) ------------------------------------

    # Rate limiting
    if http_status == 429 or _contains_any(message_l, ("rate limit", "too many requests", "retry after")):
        signals["rule_id"] = "rate_limited"
        rationale = "Provider indicated rate limiting."
        if retry_after is not None:
            rationale += f" Retry after ~{retry_after}s."
        return FailureClassification(
            category=FailureCategory.RATE_LIMITED,
            severity=FailureSeverity.TRANSIENT,
            retryable=True,
            rationale=rationale,
            signals=signals,
        )

    # Provider-side errors
    if http_status is not None and http_status >= 500:
        signals["rule_id"] = "remote_service_http_5xx"
        return FailureClassification(
            category=FailureCategory.REMOTE_SERVICE,
            severity=FailureSeverity.TRANSIENT,
            retryable=True,
            rationale="Provider returned a server-side error (5xx).",
            signals=signals,
        )

    # Authentication / permission / destination
    if http_status == 401 or _contains_any(
        message_l, ("unauthorized", "authentication", "invalid token", "wrong token")
    ):
        signals["rule_id"] = "authentication"
        return FailureClassification(
            category=FailureCategory.AUTHENTICATION,
            severity=FailureSeverity.PERMANENT,
            retryable=False,
            rationale="Provider rejected credentials.",
            signals=signals,
        )

    if http_status == 403 or _contains_any(
        message_l,
        (
            "forbidden",
            "permission denied",
            "not enough rights",
            "bot was blocked",
            "blocked by the user",
        ),
    ):
        signals["rule_id"] = "permission"
        return FailureClassification(
            category=FailureCategory.PERMISSION,
            severity=FailureSeverity.PERMANENT,
            retryable=False,
            rationale="Provider denied access or the destination blocked the sender.",
            signals=signals,
        )

    if http_status == 404 or _contains_any(
        message_l, ("chat not found", "not found", "peer id invalid", "user not found")
    ):
        signals["rule_id"] = "destination_not_found"
        return FailureClassification(
            category=FailureCategory.DESTINATION_NOT_FOUND,
            severity=FailureSeverity.PERMANENT,
            retryable=False,
            rationale="Destination was not found or is not reachable.",
            signals=signals,
        )

    # Invalid payload / request
    if http_status in (400, 413, 415, 422) or _contains_any(
        message_l,
        (
            "bad request",
            "invalid payload",
            "invalid request",
            "can't parse entities",
            "cannot parse entities",
            "message is too long",
            "text is empty",
            "parse_mode",
            "markdown",
            "html",
        ),
    ):
        signals["rule_id"] = "invalid_payload"
        return FailureClassification(
            category=FailureCategory.INVALID_PAYLOAD,
            severity=FailureSeverity.PERMANENT,
            retryable=False,
            rationale="Provider rejected the request payload/formatting.",
            signals=signals,
        )

    # Timeout
    if _contains_any(message_l, ("timed out", "timeout")) or _contains_any(
        exception_l,
        (
            "timeout",
            "readtimeout",
            "connecttimeout",
            "timeouterror",
            "timedout",
        ),
    ):
        signals["rule_id"] = "timeout"
        return FailureClassification(
            category=FailureCategory.TIMEOUT,
            severity=FailureSeverity.TRANSIENT,
            retryable=True,
            rationale="Operation timed out.",
            signals=signals,
        )

    # Network / transport
    if _contains_any(
        message_l,
        (
            "connection reset",
            "connection aborted",
            "connection refused",
            "network is unreachable",
            "temporary failure in name resolution",
            "dns",
            "ssl",
            "tls",
        ),
    ) or _contains_any(
        exception_l,
        (
            "connectionerror",
            "sslerror",
            "sslerror",
            "dnserror",
            "name resolution",
        ),
    ):
        signals["rule_id"] = "network"
        return FailureClassification(
            category=FailureCategory.NETWORK,
            severity=FailureSeverity.TRANSIENT,
            retryable=True,
            rationale="Network-level failure occurred.",
            signals=signals,
        )

    # Channel-specific nudges (no new categories; only improve rationale)
    if channel == "telegram":
        if _contains_any(message_l, ("bot can't initiate conversation", "bot can't initiate")):
            signals["rule_id"] = "permission_telegram_initiation"
            return FailureClassification(
                category=FailureCategory.PERMISSION,
                severity=FailureSeverity.PERMANENT,
                retryable=False,
                rationale="Telegram disallows the bot from initiating a chat with that user.",
                signals=signals,
            )

    signals["rule_id"] = "unknown"
    return FailureClassification(
        category=FailureCategory.UNKNOWN,
        severity=FailureSeverity.UNKNOWN,
        retryable=False,
        rationale="No rule matched; unknown failure.",
        signals=signals,
    )


def parse_event_json(raw: str) -> Mapping[str, Any]:
    """Parse a JSON string into a failure event mapping."""

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise InvalidTaxonomyInputError(
            "Invalid event JSON.",
            details={"error": str(e)},
        ) from e

    if not isinstance(data, Mapping):
        raise InvalidTaxonomyInputError(
            "Event JSON must be a JSON object (mapping).",
            details={"received_type": type(data).__name__},
        )
    return data


def _normalize_channel(channel: str | None) -> str | None:
    if channel is None:
        return None
    if not isinstance(channel, str):
        raise InvalidTaxonomyInputError(
            "Channel must be a string.",
            details={"received_type": type(channel).__name__},
        )
    trimmed = channel.strip()
    if not trimmed:
        raise InvalidTaxonomyInputError("Channel must not be empty.")
    return trimmed.lower()


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):  # bool is a subclass of int
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _first_str(*values: Any) -> str:
    for v in values:
        if v is None:
            continue
        if isinstance(v, str):
            if v.strip():
                return v
            continue
        # Keep non-str values in their repr form for classifier hints.
        s = str(v).strip()
        if s:
            return s
    return ""


def _first_not_none(*values: Any) -> Any:
    for v in values:
        if v is not None:
            return v
    return None


def _contains_any(haystack: str, needles: Sequence[str]) -> bool:
    return any(n in haystack for n in needles)


_RE_RETRY_AFTER = re.compile(r"retry\s+after\s+(?P<sec>\d+)")


def _extract_retry_after_from_message(message_l: str) -> int | None:
    """Extract retry-after seconds from common provider phrases."""
    m = _RE_RETRY_AFTER.search(message_l)
    if not m:
        return None
    try:
        return int(m.group("sec"))
    except ValueError:
        return None


def _taxonomy_for_channel(channel: str | None) -> Sequence[FailureCategoryInfo]:
    base: list[FailureCategoryInfo] = [
        FailureCategoryInfo(
            category=FailureCategory.AUTHENTICATION,
            title="Authentication failed",
            description="Credentials are missing, expired, or rejected by the provider.",
            severity=FailureSeverity.PERMANENT,
            retryable=False,
            remediation="Verify API token/credentials and rotate if needed.",
        ),
        FailureCategoryInfo(
            category=FailureCategory.PERMISSION,
            title="Permission denied",
            description="The provider refused the operation due to permissions, bans, or blocks.",
            severity=FailureSeverity.PERMANENT,
            retryable=False,
            remediation="Confirm the sender has access to the destination and required scopes.",
        ),
        FailureCategoryInfo(
            category=FailureCategory.DESTINATION_NOT_FOUND,
            title="Destination not found",
            description="The target chat/channel/user does not exist or is not reachable.",
            severity=FailureSeverity.PERMANENT,
            retryable=False,
            remediation="Verify destination identifiers (chat_id, channel name, etc.).",
        ),
        FailureCategoryInfo(
            category=FailureCategory.INVALID_PAYLOAD,
            title="Invalid payload",
            description="The provider rejected the request content (formatting, size, schema).",
            severity=FailureSeverity.PERMANENT,
            retryable=False,
            remediation="Validate the payload; trim message size; fix formatting/encoding.",
        ),
        FailureCategoryInfo(
            category=FailureCategory.RATE_LIMITED,
            title="Rate limited",
            description="The provider asked us to slow down (429 / too many requests).",
            severity=FailureSeverity.TRANSIENT,
            retryable=True,
            remediation="Backoff and retry after the provider's suggested delay.",
        ),
        FailureCategoryInfo(
            category=FailureCategory.TIMEOUT,
            title="Timeout",
            description="The request exceeded a time limit waiting for the provider or network.",
            severity=FailureSeverity.TRANSIENT,
            retryable=True,
            remediation="Retry with exponential backoff; consider increasing timeouts.",
        ),
        FailureCategoryInfo(
            category=FailureCategory.NETWORK,
            title="Network failure",
            description="Connectivity, DNS, TLS, or other network-level errors occurred.",
            severity=FailureSeverity.TRANSIENT,
            retryable=True,
            remediation="Retry; verify outbound connectivity and DNS/TLS configuration.",
        ),
        FailureCategoryInfo(
            category=FailureCategory.REMOTE_SERVICE,
            title="Provider service error",
            description="The provider returned a server-side error (5xx).",
            severity=FailureSeverity.TRANSIENT,
            retryable=True,
            remediation="Retry; if persistent, check provider status and incident channels.",
        ),
        FailureCategoryInfo(
            category=FailureCategory.UNKNOWN,
            title="Unknown failure",
            description="The failure did not match known rules.",
            severity=FailureSeverity.UNKNOWN,
            retryable=False,
            remediation="Inspect raw error details; consider adding a new rule.",
        ),
    ]
    if channel != "telegram":
        return base

    # Telegram-specific guidance without changing the stable categories.
    out: list[FailureCategoryInfo] = []
    for entry in base:
        if entry.category == FailureCategory.DESTINATION_NOT_FOUND:
            out.append(
                FailureCategoryInfo(
                    category=entry.category,
                    title=entry.title,
                    description=entry.description,
                    severity=entry.severity,
                    retryable=entry.retryable,
                    remediation="Verify chat_id/user/channel; ensure the bot has been added to the chat.",
                )
            )
        elif entry.category == FailureCategory.PERMISSION:
            out.append(
                FailureCategoryInfo(
                    category=entry.category,
                    title=entry.title,
                    description=entry.description,
                    severity=entry.severity,
                    retryable=entry.retryable,
                    remediation="Ensure the bot isn't blocked and has permission to post in the chat/channel.",
                )
            )
        elif entry.category == FailureCategory.INVALID_PAYLOAD:
            out.append(
                FailureCategoryInfo(
                    category=entry.category,
                    title=entry.title,
                    description=entry.description,
                    severity=entry.severity,
                    retryable=entry.retryable,
                    remediation="Check message length and parse_mode (Markdown/HTML) entity parsing.",
                )
            )
        else:
            out.append(entry)
    return out


def _validate_probe_inputs(*, channel: str | None, config: Mapping[str, Any] | None) -> None:
    if channel is None:
        raise InvalidTaxonomyInputError("Probe requires a specific channel (e.g., --channel telegram).")
    if config is None:
        raise MissingChannelConfigError(
            "Probe requires channel configuration.",
            details={"channel": channel},
        )


def _probe_channel(*, channel: str, config: Mapping[str, Any]) -> None:
    """Offline-safe configuration validation for supported channels.

    This function intentionally does *not* perform network calls.
    """

    if channel == "telegram":
        token = config.get("token") or config.get("bot_token")
        if token is None or (isinstance(token, str) and not token.strip()):
            raise MissingChannelConfigError(
                "Telegram probe requires a bot token.",
                details={"required_keys": ["token", "bot_token"]},
            )
        if not isinstance(token, str):
            raise InvalidTaxonomyInputError(
                "Telegram token must be a string.",
                details={"received_type": type(token).__name__},
            )
        # Telegram bot tokens conventionally contain a ':' separator (e.g. 123:ABC...).
        if ":" not in token:
            raise InvalidTaxonomyInputError(
                "Telegram token looks invalid (expected a ':' separator).",
                details={"hint": "Telegram bot tokens typically look like '123456:ABCDEF...'"},
            )
        return

    raise ChannelExternalFailureError(
        "No probe implementation is available for this channel.",
        details={"channel": channel},
    )
