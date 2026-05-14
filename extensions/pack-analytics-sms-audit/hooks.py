from __future__ import annotations

from typing import Any, Dict

PACK_ID = "pack-analytics-sms-audit"
MODULE_NAME = "extension_analytics_sms_audit"
MODE = "audit"

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
