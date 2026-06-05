"""Notion integration for Thomas.

Provides asynchronous Notion workspace interactions using the Notion API.
Includes database queries, page operations, block management, and rich text support.

Also exposes the module-level channel-provider contract
(``describe``/``health_check``/``send_message``) so Notion can be driven through
the dynamic channel-provider loader like the other adapters. For Notion, a
"send" appends the message as a paragraph block to the page identified by the
recipient (a Notion page id).
"""

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

from .integration import NotionIntegration

_NOTION_API_VERSION = "2022-06-28"
_NOTION_BASE_URL = "https://api.notion.com/v1"

CAPABILITIES = {
    "send_text": True,
    "append_block": True,
    "pages": True,
}


def describe(config: Mapping[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    return {
        "provider_id": "notion",
        "name": "Notion",
        "capabilities": ["send", "health_check"],
        "required_config_keys": ["token"],
        "optional_config_keys": ["api_key", "page_id", "target"],
        "native": CAPABILITIES,
    }


def get_capabilities(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return CAPABILITIES


def login(config: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    page_target = text_value(cfg.get("page_id"), cfg.get("target"))
    return {"message": "Notion integration token recorded.", "page_id": page_target}


def logout(**_: Any) -> dict[str, Any]:
    return {"message": "Notion logout is local-state only; remove the stored integration token to disconnect."}


def _notion_token(cfg: Mapping[str, Any]) -> str:
    return text_value(cfg.get("token"), cfg.get("api_key"), cfg.get("bot_token"))


def _notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_API_VERSION,
    }


def health_check(
    config: Mapping[str, Any] | None = None,
    *,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    token = _notion_token(cfg)
    if not token:
        return {"ok": False, "details": {"reason": "missing token"}}
    timeout_value = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)
    response = http_json_request(
        "GET",
        f"{_NOTION_BASE_URL}/users",
        headers=_notion_headers(token),
        timeout_seconds=timeout_value,
    )
    return {
        "ok": bool(response.get("ok")),
        "details": {"status": int(response.get("status", 0) or 0), "mode": "token"},
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
    token = _notion_token(cfg)
    if not token:
        raise ValueError("Notion token is required.")
    page_id = text_value(payload["recipient"], cfg.get("page_id"), cfg.get("target"), cfg.get("block_id"))
    if not page_id:
        raise ValueError("Notion page id is required.")
    body_text = build_message_text(payload["message"], subject=payload["subject"])
    if not body_text:
        raise ValueError("Notion message body is required.")
    if payload["dry_run"]:
        return {"delivered": True, "message_id": "dry-run", "provider_response": {"mode": "dry_run"}}

    block_payload = {
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": body_text}}]},
            }
        ]
    }
    response = http_json_request(
        "PATCH",
        f"{_NOTION_BASE_URL}/blocks/{page_id}/children",
        payload=block_payload,
        headers=_notion_headers(token),
        timeout_seconds=payload["timeout_seconds"],
    )
    response_payload = as_mapping(response.get("payload"))
    results = response_payload.get("results")
    first = as_mapping(results[0]) if isinstance(results, list) and results else {}
    return {
        "delivered": bool(response.get("ok")),
        "message_id": text_value(first.get("id")),
        "provider_response": response_payload,
    }


__all__ = [
    "NotionIntegration",
    "describe",
    "get_capabilities",
    "health_check",
    "send_message",
    "login",
    "logout",
]
