"""Matrix client-server provider helpers for Thomas channel integrations."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

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
    "rooms": True,
    "threads": False,
    "bot_api": True,
}


def describe(config: Mapping[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    return {
        "provider_id": "matrix",
        "name": "Matrix",
        "capabilities": ["send", "health_check"],
        "required_config_keys": ["homeserver"],
        "optional_config_keys": ["token", "target", "user_id", "password"],
        "native": CAPABILITIES,
    }


def get_capabilities(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return CAPABILITIES


def login(config: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    return {
        "message": "Matrix channel credentials recorded.",
        "homeserver": text_value(cfg.get("homeserver"), cfg.get("webhook")),
    }


def logout(**_: Any) -> dict[str, Any]:
    return {"message": "Matrix logout is local-state only; clear the stored token or password to disconnect."}


def health_check(
    config: Mapping[str, Any] | None = None,
    *,
    token: str | None = None,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    homeserver = _homeserver_from_config(cfg)
    if not homeserver:
        return {"ok": False, "details": {"reason": "missing homeserver"}}

    access_token = _resolve_access_token(
        cfg,
        override_token=token,
        timeout_seconds=float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
    )
    if not access_token:
        return {"ok": False, "details": {"reason": "missing token or login credentials"}}

    response = http_json_request(
        "GET",
        f"{homeserver}/_matrix/client/v3/account/whoami",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout_seconds=float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
    )
    payload = as_mapping(response.get("payload"))
    ok = bool(response.get("ok") and text_value(payload.get("user_id")))
    return {
        "ok": ok,
        "details": {
            "status": response.get("status", 0),
            "user_id": text_value(payload.get("user_id")),
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
    room_id: str | None = None,
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
    homeserver = _homeserver_from_config(cfg)
    access_token = _resolve_access_token(
        cfg,
        override_token=token,
        timeout_seconds=payload["timeout_seconds"],
    )
    target = text_value(payload["recipient"], room_id, cfg.get("target"), cfg.get("room_id"))
    body_text = build_message_text(payload["message"], subject=payload["subject"])
    if not homeserver or not access_token or not target:
        raise ValueError("Matrix send requires homeserver, token, and target room.")
    if not body_text:
        raise ValueError("Matrix message body is required.")
    if payload["dry_run"]:
        return {"delivered": True, "message_id": "dry-run", "provider_response": {"mode": "dry_run"}}

    txn_id = uuid.uuid4().hex
    response = http_json_request(
        "PUT",
        f"{homeserver}/_matrix/client/v3/rooms/{quote(target, safe='')}/send/m.room.message/{txn_id}",
        payload={"msgtype": "m.text", "body": body_text},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout_seconds=payload["timeout_seconds"],
    )
    response_payload = as_mapping(response.get("payload"))
    message_id = text_value(response_payload.get("event_id"))
    delivered = bool(response.get("ok") and message_id)
    return {
        "delivered": delivered,
        "message_id": message_id,
        "provider_response": response_payload,
    }


def _homeserver_from_config(config: Mapping[str, Any]) -> str:
    return text_value(config.get("homeserver"), config.get("webhook"), config.get("base_url")).rstrip("/")


def _resolve_access_token(
    config: Mapping[str, Any],
    *,
    override_token: str | None = None,
    timeout_seconds: float,
) -> str:
    access_token = text_value(override_token, config.get("token"), config.get("access_token"))
    if access_token:
        return access_token

    homeserver = _homeserver_from_config(config)
    user_id = text_value(config.get("user_id"), config.get("username"))
    password = text_value(config.get("password"))
    if not homeserver or not user_id or not password:
        return ""

    response = http_json_request(
        "POST",
        f"{homeserver}/_matrix/client/v3/login",
        payload={
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": user_id},
            "password": password,
        },
        timeout_seconds=timeout_seconds,
    )
    payload = as_mapping(response.get("payload"))
    return text_value(payload.get("access_token"))
