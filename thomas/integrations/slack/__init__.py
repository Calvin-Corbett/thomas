"""Slack integration for Thomas.

Provides asynchronous Slack workspace interactions using the Slack Web API.
Includes OAuth2 flow, message operations, channel management, user lookup,
and file operations.
"""

from __future__ import annotations

import asyncio
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

from .integration import SlackIntegration
from .messaging import SlackMessaging

CAPABILITIES = {
    "send_text": True,
    "webhook": True,
    "bot_api": True,
    "threads": True,
}


def describe(config: Mapping[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    return {
        "provider_id": "slack",
        "name": "Slack",
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
    return {"message": f"Slack channel ready for {mode} auth.", "mode": mode}


def logout(**_: Any) -> dict[str, Any]:
    return {"message": "Slack logout is local-state only; remove stored credentials to fully disconnect."}


def health_check(
    config: Mapping[str, Any] | None = None,
    *,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    token = text_value(cfg.get("token"), cfg.get("bot_token"))
    webhook_url = text_value(cfg.get("webhook"), cfg.get("webhook_url"))
    timeout_value = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)

    if token:
        ok = asyncio.run(_slack_health_check(token=token, timeout_seconds=timeout_value))
        return {"ok": ok, "details": {"mode": "bot-token"}}

    if webhook_url:
        ok = webhook_url.startswith("https://hooks.slack.com/")
        return {"ok": ok, "details": {"mode": "webhook", "validated": ok}}

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
    token = text_value(cfg.get("token"), cfg.get("bot_token"))
    webhook_url = text_value(cfg.get("webhook"), cfg.get("webhook_url"))
    target = text_value(payload["recipient"], cfg.get("target"), cfg.get("channel_id"), cfg.get("channel"))
    body_text = build_message_text(payload["message"], subject=payload["subject"])
    if not body_text:
        raise ValueError("Slack message body is required.")
    if payload["dry_run"]:
        return {"delivered": True, "message_id": "dry-run", "provider_response": {"mode": "dry_run"}}

    if webhook_url:
        response = http_json_request(
            "POST",
            webhook_url,
            payload={"text": body_text},
            timeout_seconds=payload["timeout_seconds"],
        )
        return {
            "delivered": bool(response.get("ok")),
            "message_id": text_value(as_mapping(response.get("payload")).get("ts"), "webhook-delivered"),
            "provider_response": as_mapping(response.get("payload")),
        }

    if token and target:
        return asyncio.run(
            _slack_send_via_bot(
                token=token,
                channel=target,
                text=body_text,
                timeout_seconds=payload["timeout_seconds"],
            )
        )

    raise ValueError("Slack send requires a webhook URL or token + target channel.")


async def _slack_health_check(*, token: str, timeout_seconds: float) -> bool:
    integration = SlackIntegration(client_id="", client_secret="", bot_token=token, timeout_s=int(timeout_seconds))
    try:
        await integration.connect()
        return bool(await integration.health_check())
    finally:
        await integration.disconnect()


async def _slack_send_via_bot(*, token: str, channel: str, text: str, timeout_seconds: float) -> dict[str, Any]:
    integration = SlackIntegration(client_id="", client_secret="", bot_token=token, timeout_s=int(timeout_seconds))
    try:
        await integration.connect()
        messaging = SlackMessaging(integration)
        response = await messaging.send_message(channel=channel, text=text)
        return {
            "delivered": bool(text_value(as_mapping(response).get("ts"))),
            "message_id": text_value(as_mapping(response).get("ts")),
            "provider_response": as_mapping(response),
        }
    finally:
        await integration.disconnect()


__all__ = ["SlackIntegration", "describe", "get_capabilities", "health_check", "send_message", "login", "logout"]
