"""Shared catalog and config helpers for Thomas channel providers."""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig

PROVIDER_SPECS: dict[str, dict[str, Any]] = {
    "discord": {
        "env": {
            "token": "THOMAS_DISCORD_BOT_TOKEN",
            "webhook": "THOMAS_DISCORD_WEBHOOK_URL",
            "target": "THOMAS_DISCORD_CHANNEL_ID",
        },
        "entrypoint": "thomas channels login --channel discord",
        "notes": "Use a Discord webhook URL or a bot token plus a default channel id.",
    },
    "telegram": {
        "env": {
            "token": "THOMAS_TELEGRAM_BOT_TOKEN",
            "target": "THOMAS_TELEGRAM_CHAT_ID",
        },
        "entrypoint": "thomas telegram run",
        "notes": "Provide a bot token and a default chat id for outbound sends.",
    },
    "webchat": {
        "env": {
            "webhook": "THOMAS_WEBCHAT_WEBHOOK_URL",
            "target": "THOMAS_WEBCHAT_TARGET",
        },
        "entrypoint": "thomas channels login --channel webchat",
        "notes": "Bridge Thomas web chat deliveries to an HTTP endpoint/webhook.",
    },
    "whatsapp": {
        "env": {
            "token": "THOMAS_WHATSAPP_ACCESS_TOKEN",
            "target": "THOMAS_WHATSAPP_PHONE_NUMBER_ID",
        },
        "entrypoint": "thomas channels login --channel whatsapp",
        "notes": "Uses WhatsApp Cloud API credentials: access token plus phone number id.",
    },
    "slack": {
        "env": {
            "token": "THOMAS_SLACK_BOT_TOKEN",
            "webhook": "THOMAS_SLACK_WEBHOOK_URL",
            "target": "THOMAS_SLACK_CHANNEL_ID",
        },
        "entrypoint": "thomas channels login --channel slack",
        "notes": "Use a Slack webhook URL or a bot token plus a default channel id.",
    },
    "googlechat": {
        "env": {
            "webhook": "THOMAS_GOOGLECHAT_WEBHOOK_URL",
            "target": "THOMAS_GOOGLECHAT_THREAD_KEY",
        },
        "entrypoint": "thomas channels login --channel googlechat",
        "notes": "Use a Google Chat webhook URL and optionally a default thread key/space target.",
    },
    "msteams": {
        "env": {
            "webhook": "THOMAS_MSTEAMS_WEBHOOK_URL",
            "target": "THOMAS_MSTEAMS_TARGET",
        },
        "entrypoint": "thomas channels login --channel msteams",
        "notes": "Use a Teams webhook or workflow URL and an optional default conversation target.",
    },
    "matrix": {
        "env": {
            "token": "THOMAS_MATRIX_ACCESS_TOKEN",
            "webhook": "THOMAS_MATRIX_HOMESERVER_URL",
            "target": "THOMAS_MATRIX_ROOM_ID",
        },
        "entrypoint": "thomas channels login --channel matrix",
        "notes": "Uses Matrix homeserver URL, access token, and default room id for outbound sends.",
    },
    "signal": {
        "env": {
            "token": "THOMAS_SIGNAL_ACCOUNT",
            "webhook": "THOMAS_SIGNAL_HTTP_URL",
            "target": "THOMAS_SIGNAL_RECIPIENT",
        },
        "entrypoint": "thomas channels login --channel signal",
        "notes": "Uses a Signal relay/daemon URL, optional account identifier, and a default recipient.",
    },
    "imessage": {
        "env": {
            "webhook": "THOMAS_IMESSAGE_RELAY_URL",
            "target": "THOMAS_IMESSAGE_HANDLE",
        },
        "entrypoint": "thomas channels login --channel imessage",
        "notes": "Uses an iMessage relay endpoint or bridge plus a default handle/chat target.",
    },
}
CHANNEL_PROVIDER_NAMES = tuple(PROVIDER_SPECS.keys())


@dataclass(frozen=True)
class ProviderVerificationFixture:
    config: dict[str, str]
    recipient: str
    message: str = "Thomas channel verification probe"


_VERIFICATION_FIXTURES: dict[str, ProviderVerificationFixture] = {
    "discord": ProviderVerificationFixture(
        config={"webhook": "https://discord.com/api/webhooks/1/abc"},
        recipient="channel-1",
    ),
    "telegram": ProviderVerificationFixture(
        config={"token": "123:ABC", "chat_id": "42"},
        recipient="42",
    ),
    "webchat": ProviderVerificationFixture(
        config={"webhook_url": "https://webchat.example.test/hook"},
        recipient="dest-1",
    ),
    "whatsapp": ProviderVerificationFixture(
        config={"token": "wa-token", "target": "123456789"},
        recipient="+15551234567",
    ),
    "slack": ProviderVerificationFixture(
        config={"webhook": "https://hooks.slack.com/services/T/B/C"},
        recipient="C123456",
    ),
    "googlechat": ProviderVerificationFixture(
        config={"webhook": "https://chat.googleapis.com/v1/spaces/AAAA/messages?key=x&token=y"},
        recipient="thread-1",
    ),
    "msteams": ProviderVerificationFixture(
        config={"webhook": "https://outlook.office.com/webhook/T/B/C"},
        recipient="conversation-1",
    ),
    "matrix": ProviderVerificationFixture(
        config={"homeserver": "https://matrix.example.test", "token": "matrix-token"},
        recipient="!room:example.test",
    ),
    "signal": ProviderVerificationFixture(
        config={"http_url": "https://signal.example.test/send", "target": "+15551234567"},
        recipient="+15551234567",
    ),
    "imessage": ProviderVerificationFixture(
        config={"relay_url": "https://imessage.example.test/send", "target": "chat:+15557654321"},
        recipient="chat:+15557654321",
    ),
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def channels_config_path(config: AppConfig) -> Path:
    path = config.memory.root_path / ".thomas" / "channels.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_channels_store(config: AppConfig) -> dict[str, Any]:
    path = channels_config_path(config)
    if not path.exists():
        return {"providers": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"providers": {}}
    if not isinstance(payload, dict):
        return {"providers": {}}
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        payload["providers"] = {}
    return payload


def save_channels_store(config: AppConfig, payload: dict[str, Any]) -> None:
    path = channels_config_path(config)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def mask_secret(value: str, *, keep: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= keep:
        return "*" * len(text)
    return ("*" * (len(text) - keep)) + text[-keep:]


def resolve_provider_settings(config: AppConfig, name: str) -> dict[str, str]:
    spec = PROVIDER_SPECS[name]
    env_map = spec["env"]
    store = load_channels_store(config)
    providers = store.get("providers", {})
    row = providers.get(name, {}) if isinstance(providers, dict) else {}
    if not isinstance(row, dict):
        row = {}

    resolved: dict[str, str] = {}
    for field, env_key in env_map.items():
        env_val = str(os.environ.get(env_key) or "").strip()
        if env_val:
            resolved[field] = env_val
            continue
        resolved[field] = str(row.get(field) or "").strip()
    return resolved


def provider_configured(name: str, settings: dict[str, str]) -> bool:
    token = settings.get("token", "")
    webhook = settings.get("webhook", "")
    target = settings.get("target", "")
    if name == "discord":
        return bool(webhook or (token and target))
    if name == "telegram":
        return bool(token and target)
    if name == "webchat":
        return bool(webhook)
    if name == "whatsapp":
        return bool(token and target)
    if name == "slack":
        return bool(webhook or (token and target))
    if name == "googlechat":
        return bool(webhook)
    if name == "msteams":
        return bool(webhook)
    if name == "matrix":
        return bool(webhook and token and target)
    if name == "signal":
        return bool(webhook and target)
    if name == "imessage":
        return bool(webhook and target)
    return False


def provider_module(name: str) -> Any:
    return importlib.import_module(f"thomas.integrations.{name}")


def provider_online_probe(name: str, settings: dict[str, str], timeout_s: float) -> dict[str, Any]:
    module = provider_module(name)
    checker = getattr(module, "health_check", None)
    if not callable(checker):
        return {"ok": False, "status": 0, "error": "provider health_check not implemented"}
    result = checker(config=settings, timeout_seconds=timeout_s)
    if isinstance(result, dict):
        details = result.get("details")
        status = 0
        if isinstance(details, dict):
            status = int(details.get("status", 0) or 0)
        return {"ok": bool(result.get("ok", False)), "status": status, "payload": result}
    return {"ok": bool(result), "status": 0, "payload": {"raw": result}}


def local_validation_checks(name: str, settings: dict[str, str]) -> list[dict[str, Any]]:
    token = settings.get("token", "")
    webhook = settings.get("webhook", "")
    target = settings.get("target", "")
    checks: list[dict[str, Any]] = [
        {"check": "configured", "ok": provider_configured(name, settings), "detail": "provider requirements satisfied"}
    ]
    if name == "discord":
        if token:
            checks.append({"check": "discord_token_length", "ok": len(token) >= 20, "detail": "expected >= 20 chars"})
        if webhook:
            checks.append(
                {
                    "check": "discord_webhook_scheme",
                    "ok": webhook.startswith("https://"),
                    "detail": "expected https:// webhook",
                }
            )
    elif name == "telegram":
        checks.append({"check": "telegram_token_format", "ok": ":" in token, "detail": "must contain ':'"})
        checks.append({"check": "telegram_chat_id", "ok": bool(target), "detail": "default chat id required"})
    elif name == "webchat":
        checks.append(
            {
                "check": "webchat_webhook",
                "ok": webhook.startswith(("http://", "https://")),
                "detail": "expected HTTP(S) endpoint",
            }
        )
    elif name == "whatsapp":
        checks.append({"check": "whatsapp_access_token", "ok": bool(token), "detail": "cloud access token required"})
        checks.append({"check": "whatsapp_phone_number_id", "ok": bool(target), "detail": "phone number id required"})
    elif name == "slack":
        if token:
            checks.append(
                {"check": "slack_token_prefix", "ok": token.startswith("xox"), "detail": "expected xox* token"}
            )
        if webhook:
            checks.append(
                {
                    "check": "slack_webhook_scheme",
                    "ok": webhook.startswith("https://"),
                    "detail": "expected https:// webhook",
                }
            )
    elif name == "googlechat":
        checks.append(
            {
                "check": "googlechat_webhook",
                "ok": webhook.startswith("https://chat.googleapis.com/"),
                "detail": "expected Google Chat webhook URL",
            }
        )
    elif name == "msteams":
        checks.append(
            {
                "check": "msteams_webhook",
                "ok": webhook.startswith("https://")
                and any(
                    host in webhook for host in ("office.com", "office365.com", "logic.azure.com", "powerautomate.com")
                ),
                "detail": "expected Microsoft Teams webhook/workflow URL",
            }
        )
    elif name == "matrix":
        checks.append(
            {
                "check": "matrix_homeserver",
                "ok": webhook.startswith(("http://", "https://")),
                "detail": "expected homeserver URL in webhook slot",
            }
        )
        checks.append({"check": "matrix_access_token", "ok": bool(token), "detail": "access token required"})
        checks.append(
            {
                "check": "matrix_room_id",
                "ok": target.startswith(("!", "#")),
                "detail": "expected room id/alias in target",
            }
        )
    elif name == "signal":
        checks.append(
            {
                "check": "signal_http_url",
                "ok": webhook.startswith(("http://", "https://")),
                "detail": "expected Signal relay/daemon URL",
            }
        )
        checks.append({"check": "signal_recipient", "ok": bool(target), "detail": "default recipient required"})
    elif name == "imessage":
        checks.append(
            {
                "check": "imessage_relay_url",
                "ok": webhook.startswith(("http://", "https://")),
                "detail": "expected iMessage relay endpoint",
            }
        )
        checks.append({"check": "imessage_target", "ok": bool(target), "detail": "default handle/chat target required"})
    return checks


def build_provider_contract_config(name: str, settings: dict[str, str]) -> dict[str, str]:
    token = str(settings.get("token") or "").strip()
    webhook = str(settings.get("webhook") or "").strip()
    target = str(settings.get("target") or "").strip()
    config: dict[str, str] = {}

    if name == "telegram":
        if token:
            config["token"] = token
        if target:
            config["chat_id"] = target
        return config
    if name == "webchat":
        if webhook:
            config["webhook_url"] = webhook
        if target:
            config["target"] = target
        return config
    if name == "matrix":
        if webhook:
            config["homeserver"] = webhook
        if token:
            config["token"] = token
        if target:
            config["target"] = target
        return config
    if name == "signal":
        if token:
            config["account"] = token
        if webhook:
            config["http_url"] = webhook
        if target:
            config["target"] = target
        return config
    if name == "imessage":
        if webhook:
            config["relay_url"] = webhook
        if target:
            config["target"] = target
        return config

    if token:
        config["token"] = token
    if webhook:
        config["webhook"] = webhook
    if target:
        config["target"] = target
    return config


def verification_fixture(name: str) -> ProviderVerificationFixture:
    return _VERIFICATION_FIXTURES[name]
