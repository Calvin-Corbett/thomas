from __future__ import annotations

from typing import Any, Dict

PACK_ID = "pack-analytics-sms"
MODULE_NAME = "extension_analytics_sms"

def before_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    data.setdefault('extension_pack', PACK_ID)
    data.setdefault('validated', True)
    return data

def after_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    data.setdefault('extension_pack', PACK_ID)
    data.setdefault('post_processed', True)
    return data
