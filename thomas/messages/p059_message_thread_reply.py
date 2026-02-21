"""thomas.messages.p059_message_thread_reply

Thomas-native behavior for replying inside an existing message thread.

This module intentionally avoids any OpenClaw naming. It offers a small, explicit
contract used by the CLI (and usable from server routes).

Currently supported providers:
- Slack Incoming Webhook ("slack_webhook")
- Slack Web API chat.postMessage ("slack_web_api")

Provider selection order:
1) request.provider
2) explicit config passed to message_thread_reply(..., config=...)
3) Thomas-wide config (best-effort discovery)
4) environment variables

Environment variables:
- THOMAS_SLACK_WEBHOOK_URL / SLACK_WEBHOOK_URL
- THOMAS_SLACK_BOT_TOKEN / SLACK_BOT_TOKEN
- THOMAS_SLACK_API_URL / SLACK_API_URL (optional)

Deterministic failures raise subclasses of MessageThreadReplyError with
(code, message, details).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Literal
import importlib
import os


Provider = Literal["slack_webhook", "slack_web_api"]


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MessageThreadReplyRequest:
    """Input contract."""

    thread_id: str
    text: str
    channel_id: Optional[str] = None
    provider: Optional[Provider] = None

    # Provider-specific payload fields, merged into the outgoing provider request.
    # Only allow-listed keys are accepted (unknown keys raise invalid_input).
    provider_payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageThreadReplyResult:
    """Output contract."""

    ok: bool
    provider: Provider
    thread_id: str
    text: str
    channel_id: Optional[str] = None

    # Provider message identifier if available (e.g., Slack "ts").
    message_id: Optional[str] = None

    # Provider raw response body (parsed JSON for web API; basic details for webhook).
    raw: Mapping[str, Any] = field(default_factory=dict)

    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "ok": bool(self.ok),
            "provider": self.provider,
            "thread_id": self.thread_id,
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "text": self.text,
            "raw": dict(self.raw),
        }


class MessageThreadReplyError(Exception):
    """Base deterministic error."""

    def __init__(self, code: str, message: str, *, details: Optional[Mapping[str, Any]] = None):
        self.code = str(code)
        self.message = str(message)
        self.details: Dict[str, Any] = dict(details or {})
        super().__init__(f"{self.code}: {self.message}")

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


class MessageThreadReplyInputError(MessageThreadReplyError):
    pass


class MessageThreadReplyConfigError(MessageThreadReplyError):
    pass


class MessageThreadReplyExternalError(MessageThreadReplyError):
    pass


@dataclass(frozen=True)
class MessageThreadReplyConfig:
    slack_webhook_url: Optional[str] = None
    slack_bot_token: Optional[str] = None
    slack_api_url: str = "https://slack.com/api/chat.postMessage"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slack_webhook_url": self.slack_webhook_url,
            "slack_bot_token": "***" if self.slack_bot_token else None,
            "slack_api_url": self.slack_api_url,
        }


def _require_non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MessageThreadReplyInputError(
            "invalid_input",
            f"{field_name} must be a string",
            details={"field": field_name, "type": type(value).__name__},
        )
    if value.strip() == "":
        raise MessageThreadReplyInputError(
            "invalid_input",
            f"{field_name} must be non-empty",
            details={"field": field_name},
        )
    return value


def _normalize_optional_str(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v or None


def _env_config() -> Dict[str, str]:
    return {
        "slack_webhook_url": os.environ.get("THOMAS_SLACK_WEBHOOK_URL", "")
        or os.environ.get("SLACK_WEBHOOK_URL", ""),
        "slack_bot_token": os.environ.get("THOMAS_SLACK_BOT_TOKEN", "") or os.environ.get("SLACK_BOT_TOKEN", ""),
        "slack_api_url": os.environ.get("THOMAS_SLACK_API_URL", "") or os.environ.get("SLACK_API_URL", ""),
    }


def _dig(obj: Any, path: Sequence[str]) -> Any:
    cur = obj
    for part in path:
        if cur is None:
            return None
        if isinstance(cur, Mapping):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur


def _extract_config_from_object(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}

    webhook_paths = [
        ("slack_webhook_url",),
        ("slack_incoming_webhook_url",),
        ("slack", "webhook_url"),
        ("slack", "incoming_webhook_url"),
        ("messages", "slack_webhook_url"),
        ("messages", "slack_incoming_webhook_url"),
        ("messages", "slack", "webhook_url"),
        ("messages", "slack", "incoming_webhook_url"),
    ]
    token_paths = [
        ("slack_bot_token",),
        ("slack_token",),
        ("slack", "bot_token"),
        ("slack", "token"),
        ("messages", "slack_bot_token"),
        ("messages", "slack_token"),
        ("messages", "slack", "bot_token"),
        ("messages", "slack", "token"),
    ]
    api_url_paths = [
        ("slack_api_url",),
        ("slack", "api_url"),
        ("messages", "slack_api_url"),
        ("messages", "slack", "api_url"),
    ]

    out: Dict[str, Any] = {}

    for p in webhook_paths:
        v = _dig(obj, p)
        if isinstance(v, str) and v.strip():
            out["slack_webhook_url"] = v.strip()
            break

    for p in token_paths:
        v = _dig(obj, p)
        if isinstance(v, str) and v.strip():
            out["slack_bot_token"] = v.strip()
            break

    for p in api_url_paths:
        v = _dig(obj, p)
        if isinstance(v, str) and v.strip():
            out["slack_api_url"] = v.strip()
            break

    return out


def _resolve_thomas_config() -> Dict[str, Any]:
    """Best-effort discovery of a Thomas settings/config object.

    This is intentionally defensive: if modules don't exist (or importing them
    fails due to optional deps), we silently fall back to env/explicit config.
    """

    candidates: list[Any] = []

    # Context files hint these modules exist in-repo.
    for mod_name in (
        "thomas.cli.parity_compat",
        "thomas.config",
        "thomas.settings",
        "thomas.server.config",
        "thomas.server.settings",
    ):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue

        # Common settings holders.
        for attr in ("settings", "config", "CONFIG"):
            cand = getattr(mod, attr, None)
            if cand is not None:
                candidates.append(cand)

        # Common settings factories.
        for fn in ("get_settings", "get_config", "load_config"):
            f = getattr(mod, fn, None)
            if callable(f):
                try:
                    candidates.append(f())
                except Exception:
                    continue

    merged: Dict[str, Any] = {}
    for cand in candidates:
        extracted = _extract_config_from_object(cand)
        for k, v in extracted.items():
            if v not in (None, ""):
                merged[k] = v

    return merged


def _merge_config_layers(*layers: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for layer in layers:
        if not layer:
            continue
        for k, v in layer.items():
            if v in (None, ""):
                continue
            merged[k] = v
    return merged


def _parse_config(merged: Mapping[str, Any]) -> MessageThreadReplyConfig:
    webhook = _normalize_optional_str(merged.get("slack_webhook_url"))
    token = _normalize_optional_str(merged.get("slack_bot_token"))
    api_url = _normalize_optional_str(merged.get("slack_api_url")) or MessageThreadReplyConfig.slack_api_url

    return MessageThreadReplyConfig(slack_webhook_url=webhook, slack_bot_token=token, slack_api_url=api_url)


def _validate_provider_payload(provider: Provider, payload: Mapping[str, Any]) -> Dict[str, Any]:
    if not payload:
        return {}

    if not isinstance(payload, Mapping):
        raise MessageThreadReplyInputError(
            "invalid_input",
            "provider_payload must be a mapping/object",
            details={"type": type(payload).__name__},
        )

    # Prevent overriding core fields.
    forbidden = {"text", "channel", "thread_ts"}

    if provider == "slack_webhook":
        allowed = {
            "username",
            "icon_emoji",
            "icon_url",
            "attachments",
            "blocks",
            "link_names",
            "unfurl_links",
            "unfurl_media",
            "reply_broadcast",
        }
    else:
        allowed = {
            "attachments",
            "blocks",
            "link_names",
            "mrkdwn",
            "parse",
            "reply_broadcast",
            "unfurl_links",
            "unfurl_media",
            "metadata",
        }

    unknown = sorted([k for k in payload.keys() if k not in allowed])
    bad_forbidden = sorted([k for k in payload.keys() if k in forbidden])

    if bad_forbidden:
        raise MessageThreadReplyInputError(
            "invalid_input",
            "provider_payload may not override core fields",
            details={"forbidden": bad_forbidden},
        )

    if unknown:
        raise MessageThreadReplyInputError(
            "invalid_input",
            "provider_payload contains unsupported keys",
            details={"unknown_keys": unknown, "allowed_keys": sorted(list(allowed))},
        )

    return dict(payload)


def _select_provider(req: MessageThreadReplyRequest, cfg: MessageThreadReplyConfig) -> Provider:
    if req.provider is not None:
        if req.provider not in ("slack_webhook", "slack_web_api"):
            raise MessageThreadReplyInputError(
                "invalid_input",
                "provider must be one of: slack_webhook, slack_web_api",
                details={"provider": req.provider},
            )
        return req.provider

    # Prefer webhook if available (no channel_id required).
    if cfg.slack_webhook_url:
        return "slack_webhook"
    if cfg.slack_bot_token:
        return "slack_web_api"

    raise MessageThreadReplyConfigError(
        "missing_config",
        "No messaging credentials configured for thread reply",
        details={
            "required_any_of": ["slack_webhook_url", "slack_bot_token"],
            "env_fallbacks": [
                "THOMAS_SLACK_WEBHOOK_URL",
                "SLACK_WEBHOOK_URL",
                "THOMAS_SLACK_BOT_TOKEN",
                "SLACK_BOT_TOKEN",
            ],
        },
    )


def _http_post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Optional[Mapping[str, str]] = None,
    timeout_s: float = 10.0,
    http_post: Optional[Callable[..., Any]] = None,
) -> Any:
    if http_post is None:
        try:
            import requests  # type: ignore
        except Exception as e:  # pragma: no cover
            raise MessageThreadReplyExternalError(
                "missing_dependency",
                "requests is required for HTTP messaging operations",
                details={"error": type(e).__name__},
            ) from e

        http_post = requests.post  # type: ignore[assignment]

    try:
        return http_post(url, json=dict(payload), headers=dict(headers or {}), timeout=timeout_s)
    except MessageThreadReplyError:
        raise
    except Exception as e:
        raise MessageThreadReplyExternalError(
            "http_error",
            "Failed to contact messaging endpoint",
            details={"url": url, "error": type(e).__name__},
        ) from e


def message_thread_reply(
    request: MessageThreadReplyRequest,
    *,
    config: Optional[Mapping[str, Any]] = None,
    timeout_s: float = 10.0,
    http_post: Optional[Callable[..., Any]] = None,
) -> MessageThreadReplyResult:
    """Reply within an existing message thread."""

    thread_id = _require_non_empty_str(request.thread_id, "thread_id")
    text = _require_non_empty_str(request.text, "text")
    channel_id = _normalize_optional_str(request.channel_id)

    merged_cfg_dict = _merge_config_layers(_env_config(), _resolve_thomas_config(), config)
    cfg = _parse_config(merged_cfg_dict)

    provider = _select_provider(request, cfg)
    provider_payload = _validate_provider_payload(provider, request.provider_payload)

    if provider == "slack_webhook":
        if not cfg.slack_webhook_url:
            raise MessageThreadReplyConfigError(
                "missing_config",
                "slack_webhook_url is required for slack_webhook provider",
            )

        payload: Dict[str, Any] = {"text": text, "thread_ts": thread_id}
        if channel_id:
            payload["channel"] = channel_id
        payload.update(provider_payload)

        resp = _http_post_json(cfg.slack_webhook_url, payload, timeout_s=timeout_s, http_post=http_post)
        status = getattr(resp, "status_code", None)
        body_text = getattr(resp, "text", "")

        if status != 200:
            raise MessageThreadReplyExternalError(
                "provider_error",
                "Slack webhook returned non-200 response",
                details={"status_code": status, "body": body_text},
            )

        if isinstance(body_text, str) and body_text.strip() and body_text.strip().lower() != "ok":
            raise MessageThreadReplyExternalError(
                "provider_error",
                "Slack webhook returned an unexpected response body",
                details={"status_code": status, "body": body_text},
            )

        return MessageThreadReplyResult(
            ok=True,
            provider=provider,
            thread_id=thread_id,
            channel_id=channel_id,
            message_id=None,
            text=text,
            raw={"status_code": status, "body": body_text},
        )

    # slack_web_api
    if not cfg.slack_bot_token:
        raise MessageThreadReplyConfigError(
            "missing_config",
            "slack_bot_token is required for slack_web_api provider",
        )
    if not channel_id:
        raise MessageThreadReplyConfigError(
            "missing_config",
            "channel_id is required for slack_web_api provider",
        )

    headers = {
        "Authorization": f"Bearer {cfg.slack_bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {"channel": channel_id, "text": text, "thread_ts": thread_id}
    payload.update(provider_payload)

    resp = _http_post_json(cfg.slack_api_url, payload, headers=headers, timeout_s=timeout_s, http_post=http_post)
    status = getattr(resp, "status_code", None)

    try:
        data = resp.json()  # type: ignore[attr-defined]
    except Exception:
        data = {"raw_text": getattr(resp, "text", "")}

    if status != 200:
        raise MessageThreadReplyExternalError(
            "provider_error",
            "Slack Web API returned non-200 response",
            details={"status_code": status, "body": data},
        )

    if not isinstance(data, dict) or not data.get("ok", False):
        raise MessageThreadReplyExternalError(
            "provider_error",
            "Slack Web API indicated failure",
            details={"status_code": status, "body": data},
        )

    return MessageThreadReplyResult(
        ok=True,
        provider=provider,
        thread_id=thread_id,
        channel_id=data.get("channel") or channel_id,
        message_id=data.get("ts"),
        text=text,
        raw=data,
    )


# ---- Minimal Thomas-native aliases (avoid OpenClaw naming) ----
reply_in_thread = message_thread_reply
thread_reply = message_thread_reply


__all__ = [
    "Provider",
    "SCHEMA_VERSION",
    "MessageThreadReplyRequest",
    "MessageThreadReplyResult",
    "MessageThreadReplyConfig",
    "MessageThreadReplyError",
    "MessageThreadReplyInputError",
    "MessageThreadReplyConfigError",
    "MessageThreadReplyExternalError",
    "message_thread_reply",
    "reply_in_thread",
    "thread_reply",
]
