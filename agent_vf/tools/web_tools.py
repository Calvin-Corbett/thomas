from __future__ import annotations

import urllib.request
from typing import Any

from agent_vf.tools.base import Tool, ToolRegistry


def register(reg: ToolRegistry, deny_network: bool = False) -> None:
    def open_url(args: dict[str, Any]) -> dict[str, Any]:
        if deny_network:
            return {"ok": False, "error": "network_denied"}
        url = args["url"]
        req = urllib.request.Request(url, headers={"User-Agent":"agent_vf/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read(2_000_000).decode("utf-8", errors="replace")
        return {"ok": True, "text": data}

    reg.register(Tool(
        name="web.open",
        description="Fetch a URL and return text (HTML).",
        schema={"type":"object","properties":{"url":{"type":"string"}}, "required":["url"]},
        handler=open_url
    ))
