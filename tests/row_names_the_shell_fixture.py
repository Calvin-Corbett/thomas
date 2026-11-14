"""A row that names a module the shell keeps, and imports nothing of it. The file is never loaded as a real row."""

from __future__ import annotations

from typing import Any


class _NamesTheShell:
    name = "names-the-shell"
    inject = ()
    imports = ("thomas.server.routes.preferences_aiohttp",)

    def apply(self, ctx: Any, config: Any) -> None:
        return None


plugin = _NamesTheShell()
