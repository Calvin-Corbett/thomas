from __future__ import annotations

from typing import Any, Dict

PACK_ID = "pack-security-discord-prevent"
MODULE_NAME = "extension_security_discord_prevent"
MODE = "prevent"

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
