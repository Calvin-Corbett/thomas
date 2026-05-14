from __future__ import annotations

from typing import Any, Dict

PACK_ID = "pack-ops-webhook"
MODULE_NAME = "extension_ops_webhook"

def before_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault('extension_pack', PACK_ID)
    data.setdefault('validated', True)
    return data

def after_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault('extension_pack', PACK_ID)
    data.setdefault('post_processed', True)
    return data
