"""Attention cards, as a row: three routes, two tools lent to the runs Thomas builds, and a watch on this PC's load.

A card is a small thing Thomas puts in the empty space left of the conversation: a notice, a question with buttons, a
reply box, a picture, a preview of a page he built, or a layout he wrote himself. The page that is on screen asks the
routes for the open cards and draws them, so a card reaches you whatever you are looking at. The cards are kept in
memory and nothing is written to disk.

Off takes the routes away, ends the loan of the tools and stops the watch. A page that is open gets 404 and asks again
once a minute. A run built before then keeps its tools, and each one answers that it is turned off and does nothing.

The tools are lent the way the notifications row lends its own, to the process-wide ledger a worker builds from and to
the registry Chat was given when the app was made; ``thomas/server/rows/notifications.py`` says why both.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from typing import Any

OWNER = "attention"


class _Attention:
    name = OWNER
    inject = ("web",)
    imports = (
        "thomas.core.attention_cards",
        "thomas.core.attention_blocks",
        "thomas.server.attention_tools",
        "thomas.server.attention_widgets",
        "thomas.server.routes.attention_routes",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from pathlib import Path

        from thomas.agent.kernel_wiring import LENT_TOOLS, LentTool, contribute_tools, contributed_tools, get_kernel
        from thomas.core.attention_cards import STORE, watch_load
        from thomas.server.app_keys import APP_TOOLS
        from thomas.server.attention_tools import build_attention_tools
        from thomas.server.attention_widgets import Widgets
        from thomas.server.routes.attention_routes import register_attention_routes

        service = ctx["web"]
        widgets = Widgets(service.app, Path(service.config.memory.root_path) / "attention" / "widgets")
        STORE.resolver = widgets.resolve
        register_attention_routes(
            service.view(ctx), require_api_access=service.require_api_access, store=STORE, widgets=widgets
        )
        root = get_kernel().root
        for left_over in contributed_tools(root):
            if left_over.lending.owner == OWNER:
                root.get(LENT_TOOLS).withdraw(left_over.lending)
        ctx.effect(contribute_tools(root, build_attention_tools(STORE, widgets), owner=OWNER))
        chat_tools = service.app.get(APP_TOOLS)
        if chat_tools is not None:

            def free(name: str) -> bool:
                """A name no built-in holds. One held by a loan of this row that has ended is ours to replace."""
                held = chat_tools.get(name)
                return held is None or (isinstance(held, LentTool) and held.lending.owner == OWNER)

            added = [tool for tool in contributed_tools(root) if tool.lending.owner == OWNER and free(tool.name)]
            for tool in added:
                chat_tools.register(tool)

            def take_out() -> None:
                for tool in added:
                    if chat_tools.get(tool.name) is tool:
                        chat_tools.unregister(tool.name)

            ctx.effect(take_out)
        ctx.on_ready(lambda: ctx.task(lambda: watch_load(STORE), name="attention load watch"))
        ctx.on_ready(lambda: ctx.task(lambda: widgets.watch(STORE), name="attention widget refresh"))


plugin = _Attention()
