"""Gate 7 driver: Thomas's Python side driving an Electron tab over the bridge.

Connects to the loopback WebSocket the Electron main process opens in
--bridge mode (desktop/bridge.json carries {port, token}), then performs the
full loop the gate demands: navigate -> read DOM -> click -> observe, all
executed in the main process via CDP (webContents.debugger). Prints one JSON
line per step as evidence and tells Electron to quit when done.

Run:  .venv\\Scripts\\python.exe desktop\\spike_bridge.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

BRIDGE_INFO = Path(__file__).parent / "bridge.json"


async def main() -> int:
    info = json.loads(BRIDGE_INFO.read_text(encoding="utf-8"))
    url = f"ws://127.0.0.1:{info['port']}/?token={info['token']}"
    evidence: list[dict] = []

    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(url) as ws:
            seq = 0

            async def call(cmd: str, **params):
                nonlocal seq
                seq += 1
                await ws.send_json({"id": seq, "cmd": cmd, "params": params})
                raw = await asyncio.wait_for(ws.receive(), timeout=60)
                msg = json.loads(raw.data)
                step = {"step": cmd, **({"params": params} if params else {}), "reply": msg}
                evidence.append(step)
                print(json.dumps(step))
                if not msg.get("ok"):
                    raise RuntimeError(f"{cmd} failed: {msg.get('error')}")
                return msg["result"]

            await call("navigate", url="https://example.com")
            dom = await call("read_dom")
            clicked = await call("click", selector="a")
            final = await call("url")
            await call("quit")

    ok = (
        dom.get("title") == "Example Domain"
        and (dom.get("htmlChars") or 0) > 200
        and final.get("url", "").startswith("https://www.iana.org")
    )
    print(json.dumps({"gate7_verdict": "PASS" if ok else "FAIL",
                      "dom_title": dom.get("title"),
                      "clicked": clicked, "final_url": final.get("url")}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
