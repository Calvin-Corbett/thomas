from __future__ import annotations

from typing import Any, Dict

PACK_ID = "pack-ops-pagerduty-escalate"
MODULE_NAME = "extension_ops_pagerduty_escalate"
MODE = "escalate"

def before_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    data.setdefault('extension_pack', PACK_ID)
    data.setdefault('mode', MODE)
    data.setdefault('validated', True)
    return data

def after_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(payload or {})
    data.setdefault('extension_pack', PACK_ID)
    data.setdefault('mode', MODE)
    data.setdefault('post_processed', True)
    return data
