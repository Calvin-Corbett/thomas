"""Signal provider helpers for Thomas channel integrations."""

from __future__ import annotations

import shutil
import subprocess
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
    "relay": True,
    "cli": True,
    "groups": True,
}


def describe(config: Mapping[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    return {
        "provider_id": "signal",
        "name": "Signal",
        "capabilities": ["send", "health_check"],
        "required_config_keys": [],
        "optional_config_keys": ["http_url", "account", "target", "cli_path"],
        "native": CAPABILITIES,
    }


def get_capabilities(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return CAPABILITIES


def login(config: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    return {
        "message": "Signal channel credentials recorded.",
        "account": text_value(cfg.get("account"), cfg.get("token")),
    }


def logout(**_: Any) -> dict[str, Any]:
    return {"message": "Signal logout is local-state only; clear the stored relay or CLI credentials to disconnect."}


def health_check(
    config: Mapping[str, Any] | None = None,
    *,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    cfg = {**as_mapping(config), **as_mapping(kwargs)}
    cli_path = text_value(cfg.get("cli_path"))
    if cli_path:
        return _cli_health_check(cli_path, float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS))

    http_url = text_value(cfg.get("http_url"), cfg.get("webhook"))
    if not http_url:
        return {"ok": False, "details": {"reason": "missing http_url or cli_path"}}
    if not http_url.startswith(("http://", "https://")):
        return {"ok": False, "details": {"reason": "invalid http_url"}}

    response = http_json_request(
        "GET",
        http_url,
        timeout_seconds=float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
    )
    ok = bool(response.get("ok")) or int(response.get("status", 0)) in {401, 403, 404, 405}
    return {"ok": ok, "details": {"status": response.get("status", 0), "endpoint": http_url}}


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
    target = text_value(payload["recipient"], cfg.get("target"), cfg.get("recipient"), cfg.get("to"))
    body_text = build_message_text(payload["message"], subject=payload["subject"])
    if not body_text:
        raise ValueError("Signal message body is required.")
    if not target:
        raise ValueError("Signal recipient is required.")
    if payload["dry_run"]:
        return {"delivered": True, "message_id": "dry-run", "provider_response": {"mode": "dry_run"}}

    cli_path = text_value(cfg.get("cli_path"))
    if cli_path:
        account = text_value(cfg.get("account"), cfg.get("token"))
        if not account:
            raise ValueError("Signal CLI send requires account.")
        return _cli_send(cli_path, account, target, body_text, payload["timeout_seconds"])

    http_url = text_value(cfg.get("http_url"), cfg.get("webhook"))
    if not http_url:
        raise ValueError("Signal send requires http_url or cli_path.")
    response = http_json_request(
        "POST",
        http_url,
        payload={
            "account": text_value(cfg.get("account"), cfg.get("token")),
            "recipient": target,
            "text": body_text,
            "metadata": payload["metadata"],
        },
        timeout_seconds=payload["timeout_seconds"],
    )
    response_payload = as_mapping(response.get("payload"))
    message_id = text_value(
        response_payload.get("message_id"), response_payload.get("id"), response_payload.get("timestamp")
    )
    delivered = bool(response.get("ok"))
    return {
        "delivered": delivered,
        "message_id": message_id or "signal-delivered",
        "provider_response": response_payload,
    }


def _cli_health_check(cli_path: str, timeout_seconds: float) -> dict[str, Any]:
    resolved = shutil.which(cli_path) or cli_path
    try:
        result = subprocess.run(  # noqa: S603
            [resolved, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "details": {"reason": type(exc).__name__}}
    return {"ok": result.returncode == 0, "details": {"status": result.returncode}}


def _cli_send(cli_path: str, account: str, recipient: str, body_text: str, timeout_seconds: float) -> dict[str, Any]:
    resolved = shutil.which(cli_path) or cli_path
    try:
        result = subprocess.run(  # noqa: S603
            [resolved, "-a", account, "send", "-m", body_text, recipient],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"Signal CLI send failed: {type(exc).__name__}") from exc
    return {
        "delivered": result.returncode == 0,
        "message_id": "signal-cli-delivered" if result.returncode == 0 else "",
        "provider_response": {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "status": result.returncode,
        },
    }
