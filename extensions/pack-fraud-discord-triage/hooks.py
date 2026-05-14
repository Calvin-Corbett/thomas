from __future__ import annotations

from typing import Any

PACK_ID = "pack-fraud-discord-triage"
MODULE_NAME = "extension_fraud_discord_triage"
MODE = "triage"

def before_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault('extension_pack', PACK_ID)
    data.setdefault('mode', MODE)
    data.setdefault('validated', True)
    return data

def after_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault('extension_pack', PACK_ID)
    data.setdefault('mode', MODE)
    data.setdefault('post_processed', True)
    return data
