"""WhatsApp Cloud API provider helpers for Thomas channel integrations."""

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

_DEFAULT_API_BASE = "https://graph.facebook.com/v19.0"

CAPABILITIES = {
    "send_text": True,
    "cloud_api": True,
    "pairing": False,
    "threads": False,
}


def describe(config: Mapping[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    return {
        "provider_id": "whatsapp",
        "name": "WhatsApp",
        "capabilities": ["send", "health_check"],
        "required_config_keys": [],
        "optional_config_keys": ["token", "target", "api_base"],
        "native": CAPABILITIES,
    }


def get_capabilities(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return CAPABILITIES


def login(config: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    sender = text_value(cfg.get("target"), cfg.get("phone_number_id"))
    return {
        "message": "WhatsApp Cloud API credentials recorded.",
        "mode": "cloud-api",
        "sender": sender,
    }


def logout(**_: Any) -> dict[str, Any]:
    return {"message": "WhatsApp logout is local-state only; clear stored Cloud API credentials to disconnect."}


def health_check(
    config: Mapping[str, Any] | None = None,
    *,
    token: str | None = None,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    token_value = text_value(token, cfg.get("token"), cfg.get("access_token"))
    sender = text_value(cfg.get("target"), cfg.get("phone_number_id"))
    api_base = text_value(cfg.get("api_base"), _DEFAULT_API_BASE).rstrip("/")
    if not token_value or not sender:
        return {"ok": False, "details": {"reason": "missing token or sender id"}}

    response = http_json_request(
        "GET",
        f"{api_base}/{sender}",
        headers={"Authorization": f"Bearer {token_value}"},
        timeout_seconds=float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
    )
    payload = as_mapping(response.get("payload"))
    ok = bool(response.get("ok") and text_value(payload.get("id"), sender))
    return {
        "ok": ok,
        "details": {
            "mode": "cloud-api",
            "status": response.get("status", 0),
            "sender": text_value(payload.get("id"), sender),
        },
    }


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
    phone_number_id: str | None = None,
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
    token_value = text_value(token, cfg.get("token"), cfg.get("access_token"))
    sender = text_value(phone_number_id, cfg.get("target"), cfg.get("phone_number_id"))
    target = text_value(payload["recipient"], cfg.get("recipient"), cfg.get("to"))
    api_base = text_value(cfg.get("api_base"), _DEFAULT_API_BASE).rstrip("/")
    body_text = build_message_text(payload["message"], subject=payload["subject"])
    if not body_text:
        raise ValueError("WhatsApp message body is required.")
    if not token_value or not sender or not target:
        raise ValueError("WhatsApp send requires token, target sender id, and recipient.")
    if payload["dry_run"]:
        return {"delivered": True, "message_id": "dry-run", "provider_response": {"mode": "dry_run"}}

    response = http_json_request(
        "POST",
        f"{api_base}/{sender}/messages",
        payload={
            "messaging_product": "whatsapp",
            "to": target,
            "type": "text",
            "text": {"body": body_text},
        },
        headers={"Authorization": f"Bearer {token_value}"},
        timeout_seconds=payload["timeout_seconds"],
    )
    response_payload = as_mapping(response.get("payload"))
    messages = response_payload.get("messages")
    message_id = ""
    if isinstance(messages, list) and messages:
        message_id = text_value(as_mapping(messages[0]).get("id"))
    delivered = bool(response.get("ok") and message_id)
    return {
        "delivered": delivered,
        "message_id": message_id,
        "provider_response": response_payload,
    }
