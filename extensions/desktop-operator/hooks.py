from __future__ import annotations

from typing import Any

PACK_ID = "desktop-operator"
MODULE_NAME = "desktop_operator"
MODE = "desktop_operator"


def before_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault("extension_pack", PACK_ID)
    data.setdefault("mode", MODE)
    data.setdefault("desktop_operator", True)
    return data


def after_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault("extension_pack", PACK_ID)
    data.setdefault("mode", MODE)
    data.setdefault("desktop_operator", True)
    return data
