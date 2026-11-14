"""The browser tools, as a row: it lends Thomas's browser tools to the runs built while it is on, and closes the browser
when it is turned off.

On, a run built from then on has ``browser.open``, ``click``, ``type``, ``screenshot``, ``extract``, ``close``,
``console`` and ``network``. Off, a run built later has none, and a run that already holds one is refused on its next call
so it never waits. A Build run is told the browser is turned off. Chat calls tools by name from the server's own set, which
the row empties of them, so Chat is told the tool is unknown. The Chromium that Playwright launched is closed with every
page in it, and turning the row on again starts with no session and no recorded console or network rows. Nothing is
launched until a run first opens a page.

This is a different thing from the setting Allow Browser Tools. That one is your permission, and it decides whether a
run may use browser tools it has: chat and Build refuse a call while it is off. This row decides whether Thomas has the
tools at all. Thomas can browse only while both are on. The Plugins page says so in its words.

``browser.open`` may read a ``file://`` page inside the folder a run works in, so each run's copy of it is rebound to that
run's folder when the run is built (see ``app_helpers._build_tools``). The folder the row was applied with is only the
server's own. The command line has its own copy of the tools in ``thomas.cli.cli_browser_tools`` and is not affected.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any


class _Browser:
    name = "browser"
    inject = ("web",)
    imports = ("thomas.tools.browser", "thomas.tools.browser_parity")

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.agent.kernel_wiring import contribute_tools, contributed_tools
        from thomas.server.app_keys import APP_TOOLS
        from thomas.tools import browser, browser_parity
        from thomas.tools.registry import ToolRegistry

        service = ctx["web"]
        built = ToolRegistry()
        browser.register_browser_tools(built, service.config.tools.sandbox_path)  # adds none without Playwright
        browser_parity.install_browser_parity(built)
        end_loan = contribute_tools(ctx, built.list_tools(), owner=self.name)
        browser.start_browser()

        # Chat does not build its tools per run: it reads the one set made when the server was created, which is before
        # any row is applied. So the loan is also put into that set, and taken out again when this stops.
        shared = service.app.get(APP_TOOLS)
        placed = []
        for lent in contributed_tools(ctx):
            if lent.lending.owner == self.name and shared is not None and shared.get(lent.name) is None:
                shared.register(lent)
                placed.append(lent)

        async def refuse_new_calls() -> None:
            # Before the wait for running work: a call now gets a refusal, and cannot launch the browser again.
            end_loan()
            for lent in placed:
                if shared.get(lent.name) is lent:
                    shared.unregister(lent.name)

        async def close_the_browser() -> None:
            await browser.stop_browser()
            browser_parity.forget_telemetry()

        ctx.on_drain(refuse_new_calls)
        ctx.on_stopped(close_the_browser)


plugin = _Browser()
