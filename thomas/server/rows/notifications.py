"""Notifications, as a row: six notification tools lent to the runs Thomas builds, and the notice a delegated task sends.

There are no routes. While the row is on, two things are lent. The first is the six ``notifications_*`` tools, which
every chat and worker run built from then on is given. A tool keeps its database files inside the ``notifications``
folder of Thomas's data folder: the scope refuses a name that leaves it, and another drive or a network name is refused
from the text before the disk is touched. The second is the notifier a delegation uses when a task ends, is blocked or
waits for your approval, which saves a notification in a database file of its own, ``THOMAS_NOTIFICATIONS_DB`` or
``data/notifications.sqlite`` beside where Thomas was started. Nothing in Thomas reads either one back to you.

Off ends both loans. A run built before then keeps its tools, and each one answers that notifications are turned off
and does nothing. A tool call that was already running is not cut. A delegation that ends later reaches the chat as
before and notifies nobody. Turning it on lends them again, to runs built from then on, and a run that kept the old
tools stays refused. Nothing is unloaded, and the files written stay where they are.

Two lists of tools have to carry them. A worker builds its tools when it starts, from the process-wide kernel's ledger
of lent tools, which is not the row's own kernel: that one is separate for each app, and a tool lent there would never
reach a worker. Chat does not build its tools again for each run. It uses the registry the app made when it was created,
before any row applied, so the row adds its tools to that registry and takes them out when it stops. A loan left over
from an app that was never stopped in this process is taken over, since one name cannot be lent twice, and so is a tool
of that loan which a later app's registry already holds.

``thomas/server/rows/__init__.py`` says how a row is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

OWNER = "notifications"


class _Notifications:
    name = OWNER
    inject = ("web",)
    imports = (
        "thomas.notifications.delegation_hooks",
        "thomas.notifications.tools",
    )

    def apply(self, ctx: Any, config: Any) -> None:
        from thomas.agent.kernel_wiring import LENT_TOOLS, LentTool, contribute_tools, contributed_tools, get_kernel
        from thomas.notifications.delegation_hooks import emit_delegation_notification
        from thomas.notifications.tools import build_notifications_tools
        from thomas.server.app_keys import APP_TOOLS
        from thomas.server.chat_delegation_emitter import lend_notifier
        from thomas.tools.fs_scope import scopes

        service = ctx["web"]
        scope = scopes().scope(Path(service.config.memory.root_path) / "notifications")
        root = get_kernel().root
        for left_over in contributed_tools(root):
            if left_over.lending.owner == OWNER:
                root.get(LENT_TOOLS).withdraw(left_over.lending)
        ctx.effect(contribute_tools(root, build_notifications_tools(scope), owner=OWNER))
        ctx.effect(lend_notifier(emit_delegation_notification))
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


plugin = _Notifications()
