"""WebChat webhook provider helpers for Thomas channel integrations."""

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
    "websocket_ready": False,
}


def describe(config: Mapping[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    return {
        "provider_id": "webchat",
        "name": "WebChat",
        "capabilities": ["send", "health_check"],
        "required_config_keys": ["webhook_url"],
        "optional_config_keys": ["token", "target"],
        "native": CAPABILITIES,
    }


def get_capabilities(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return CAPABILITIES


def login(config: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    endpoint = text_value(cfg.get("webhook_url"), cfg.get("endpoint_url"))
    return {"message": "WebChat delivery bridge configured.", "endpoint": endpoint}


def logout(**_: Any) -> dict[str, Any]:
    return {"message": "WebChat logout is local-state only; clear the configured webhook endpoint to disconnect."}


def health_check(
    config: Mapping[str, Any] | None = None,
    *,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    webhook_url = text_value(cfg.get("webhook_url"), cfg.get("endpoint_url"))
    if not webhook_url:
        return {"ok": False, "details": {"reason": "missing webhook_url"}}
    if not webhook_url.startswith(("http://", "https://")):
        return {"ok": False, "details": {"reason": "invalid webhook_url"}}
    response = http_json_request(
        "GET",
        webhook_url,
        timeout_seconds=float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
    )
    ok = bool(response.get("ok")) or int(response.get("status", 0)) in {401, 403, 405}
    return {
        "ok": ok,
        "details": {"status": response.get("status", 0), "endpoint": webhook_url},
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
    webhook_url: str | None = None,
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
    endpoint = text_value(webhook_url, cfg.get("webhook_url"), cfg.get("endpoint_url"))
    target = text_value(payload["recipient"], cfg.get("target"), "broadcast")
    body_text = build_message_text(payload["message"], subject=payload["subject"])
    if not endpoint:
        raise ValueError("WebChat send requires webhook_url.")
    if not body_text:
        raise ValueError("WebChat message body is required.")
    if payload["dry_run"]:
        return {"delivered": True, "message_id": "dry-run", "provider_response": {"mode": "dry_run"}}

    response = http_json_request(
        "POST",
        endpoint,
        payload={
            "recipient": target,
            "text": body_text,
            "metadata": payload["metadata"],
        },
        timeout_seconds=payload["timeout_seconds"],
    )
    response_payload = as_mapping(response.get("payload"))
    message_id = text_value(response_payload.get("message_id"), response_payload.get("id"))
    delivered = bool(response.get("ok"))
    return {
        "delivered": delivered,
        "message_id": message_id or "webchat-delivered",
        "provider_response": response_payload,
    }
