from __future__ import annotations

from typing import Any

from agent_vf.tools.base import Tool, ToolRegistry


def register(reg: ToolRegistry) -> None:
    def run(args: dict[str, Any]) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            return {"ok": False, "error": "playwright_not_installed", "detail": str(e)}

        steps = args.get("steps", [])
        headless = bool(args.get("headless", False))
        url = args.get("url")
        if not url:
            return {"ok": False, "error": "missing_url"}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded")
            for st in steps:
                t = st.get("type")
                if t == "click":
                    page.click(st["selector"])
                elif t == "fill":
                    page.fill(st["selector"], st.get("text",""))
                elif t == "press":
                    page.press(st["selector"], st.get("key","Enter"))
                elif t == "wait":
                    page.wait_for_timeout(int(st.get("ms", 500)))
                elif t == "screenshot":
                    page.screenshot(path=st.get("path","screenshot.png"), full_page=True)
            html = page.content()
            browser.close()
        return {"ok": True, "html": html[:400000]}

    reg.register(Tool(
        name="browser.playwright",
        description="Automate a browser with Playwright steps (requires Playwright installed).",
        schema={
            "type":"object",
            "properties":{
                "url":{"type":"string"},
                "headless":{"type":"boolean"},
                "steps":{"type":"array","items":{"type":"object"}}
            },
            "required":["url"]
        },
        handler=run
    ))
