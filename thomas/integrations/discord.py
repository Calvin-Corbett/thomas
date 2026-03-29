"""Discord provider helpers for Thomas channel integrations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from thomas.integrations._channel_provider_runtime import (
    DEFAULT_TIMEOUT_SECONDS,
    as_mapping,
    build_message_text,
    http_json_request,
    resolve_request_payload,
    text_value,
)

CAPABILITIES = {
    "send_text": True,
    "webhook": True,
    "bot_api": True,
    "threads": False,
}


def describe(config: Mapping[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    return {
        "provider_id": "discord",
        "name": "Discord",
        "capabilities": ["send", "health_check"],
        "required_config_keys": [],
        "optional_config_keys": ["token", "webhook", "target"],
        "native": CAPABILITIES,
    }


def get_capabilities(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return CAPABILITIES


def login(config: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    mode = "webhook" if text_value(cfg.get("webhook"), cfg.get("webhook_url")) else "bot-token"
    return {"message": f"Discord channel ready for {mode} auth.", "mode": mode}


def logout(**_: Any) -> dict[str, Any]:
    return {"message": "Discord channel logout is local-state only; remove stored credentials to fully disconnect."}


def health_check(
    config: Mapping[str, Any] | None = None,
    *,
    token: str | None = None,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    token_value = text_value(token, cfg.get("token"), cfg.get("bot_token"))
    webhook_url = text_value(cfg.get("webhook"), cfg.get("webhook_url"))
    timeout_value = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)

    if token_value:
        response = http_json_request(
            "GET",
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {token_value}"},
            timeout_seconds=timeout_value,
        )
        payload = as_mapping(response.get("payload"))
        ok = bool(response.get("ok") and text_value(payload.get("id")))
        return {
            "ok": ok,
            "details": {
                "mode": "bot-token",
                "status": response.get("status", 0),
                "user_id": text_value(payload.get("id")),
            },
        }

    if webhook_url:
        ok = webhook_url.startswith("https://discord.com/api/webhooks/") or webhook_url.startswith(
            "https://ptb.discord.com/api/webhooks/"
        )
        return {"ok": ok, "details": {"mode": "webhook", "status": 0, "validated": ok}}

    return {"ok": False, "details": {"reason": "missing token or webhook"}}


def send_message(
    request: Any = None,
    *,
    config: Mapping[str, Any] | None = None,
    recipient: str | None = None,
    message: str | None = None,
    text: str | None = None,
    subject: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    timeout_seconds: float | None = None,
    token: str | None = None,
    webhook: str | None = None,
    channel_id: str | None = None,
    dry_run: bool | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    payload = resolve_request_payload(
        request,
        config=config,
        recipient=recipient,
        message=message,
        text=text,
        subject=subject,
        metadata=metadata,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
    )
    cfg = {**payload["config"], **as_mapping(kwargs)}
    token_value = text_value(token, cfg.get("token"), cfg.get("bot_token"))
    webhook_url = text_value(webhook, cfg.get("webhook"), cfg.get("webhook_url"))
    target = text_value(payload["recipient"], channel_id, cfg.get("target"), cfg.get("channel_id"), cfg.get("channel"))
    body_text = build_message_text(payload["message"], subject=payload["subject"])
    if not body_text:
        raise ValueError("Discord message body is required.")

    if payload["dry_run"]:
        return {"delivered": True, "message_id": "dry-run", "provider_response": {"mode": "dry_run"}}

    if webhook_url:
        url = (
            webhook_url if "wait=true" in webhook_url else f"{webhook_url}{'&' if '?' in webhook_url else '?'}wait=true"
        )
        response = http_json_request(
            "POST",
            url,
            payload={"content": body_text},
            timeout_seconds=payload["timeout_seconds"],
        )
        response_payload = as_mapping(response.get("payload"))
        delivered = bool(response.get("ok") and text_value(response_payload.get("id")))
        return {
            "delivered": delivered,
            "message_id": text_value(response_payload.get("id")),
            "provider_response": response_payload,
        }

    if token_value and target:
        response = http_json_request(
            "POST",
            f"https://discord.com/api/v10/channels/{target}/messages",
            payload={"content": body_text},
            headers={"Authorization": f"Bot {token_value}"},
            timeout_seconds=payload["timeout_seconds"],
        )
        response_payload = as_mapping(response.get("payload"))
        delivered = bool(response.get("ok") and text_value(response_payload.get("id")))
        return {
            "delivered": delivered,
            "message_id": text_value(response_payload.get("id")),
            "provider_response": response_payload,
        }

    raise ValueError("Discord send requires a webhook URL or token + target channel.")
