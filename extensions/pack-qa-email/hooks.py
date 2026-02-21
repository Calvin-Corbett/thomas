from __future__ import annotations

from typing import Any, Dict

PACK_ID = "pack-qa-email"
MODULE_NAME = "extension_qa_email"

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
