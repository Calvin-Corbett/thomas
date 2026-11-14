"""Widgets Thomas can summon beside the conversation: live readings, the templates built from them, and saved ones.

A widget is a card made of blocks (``thomas.core.attention_blocks``). Three things live here:

* **Readings.** A named number, list or line of points read from the running server, such as ``machine.cpu``. A block
  names one and it is filled in each time the widget refreshes. Add one with ``@reading``.
* **Templates.** A widget with a name, so it can be summoned by saying the name. The ones in :data:`BUILT_IN` ship;
  one Thomas saves is a JSON file in the ``attention/widgets`` folder of the data folder, and is read from there.
* **Switches.** A toggle block turns one plugin row off or on. Its label and position are written here from the row's
  real name and state, never from whoever made the widget, and a row that cannot be turned off shows as locked.

``docs/attention_widgets.md`` is the guide. ``thomas/server/rows/attention.py`` starts the refresh.
"""

from __future__ import annotations

import asyncio
import collections
import json
import re
import time
from pathlib import Path
from typing import Any

from thomas.core.attention_blocks import clean_blocks, fill
from thomas.server.attention_widget_templates import BUILT_IN

READINGS: dict[str, tuple[str, Any]] = {}
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
# What a reading that cannot be taken raises. It answers nothing, and its block keeps the last thing it was given.
_UNREADABLE = (ImportError, KeyError, OSError, ValueError, TypeError, AttributeError, RuntimeError)


def reading(name: str, about: str) -> Any:
    """Register a live reading. The function takes the :class:`Widgets` and answers the fields its block kind takes."""

    def keep(function: Any) -> Any:
        READINGS[name] = (about, function)
        return function

    return keep


def _span(seconds: float) -> str:
    minutes = int(max(seconds, 0) // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours < 48 else f"{hours // 24} days"


def _load() -> tuple[Any, float]:
    from thomas.core import machine_load

    return machine_load.latest(), machine_load.limit()


@reading("machine.cpu", "This PC's CPU load, in percent, with the limit where Thomas holds new work. For a meter.")
def _cpu(widgets: Widgets) -> dict[str, Any]:
    now, cap = _load()
    return (
        {"value": now.cpu, "mark": cap or None, "hint": f"Thomas holds new work at {cap:.0f}%" if cap else ""}
        if now
        else {}
    )


@reading("machine.memory", "This PC's memory in use, in percent, with the same limit. For a meter.")
def _memory(widgets: Widgets) -> dict[str, Any]:
    now, cap = _load()
    return {"value": now.memory, "mark": cap or None, "hint": ""} if now else {}


@reading("machine.cpu_history", "CPU load over the last few minutes, one point every two seconds. For a spark.")
def _cpu_history(widgets: Widgets) -> dict[str, Any]:
    return {"points": list(widgets.cpu), "unit": "%"}


@reading("machine.memory_history", "Memory in use over the last few minutes. For a spark.")
def _memory_history(widgets: Widgets) -> dict[str, Any]:
    return {"points": list(widgets.memory), "unit": "%"}


@reading(
    "thomas.facts",
    "Thomas's version, the commit he is running, how long he has been up and whether he is restarting. For rows.",
)
def _facts(widgets: Widgets) -> dict[str, Any]:
    from thomas import __version__
    from thomas.core.head_sha import head_sha
    from thomas.server import owner_restart

    commit = head_sha(Path(__file__).resolve().parents[2]) or ""
    restart = owner_restart.status(widgets.app)
    waiting = f"waiting {_span(float(restart.get('elapsed_s') or 0))}" if restart.get("restarting") else ""
    if waiting and restart.get("words"):
        waiting += f". {restart['words']}"
    return {
        "rows": [
            {"label": "Version", "value": str(__version__)},
            {"label": "Commit on disk", "value": commit[:8] or "unknown"},
            {"label": "Running for", "value": _span(time.time() - widgets.started)},
            {
                "label": "Restart",
                "value": "Restarting" if restart.get("restarting") else "Not restarting",
                "note": waiting,
            },
        ]
    }


@reading("plugins.summary", "How many plugin rows are on, off, starting or failed. For rows.")
def _plugins(widgets: Widgets) -> dict[str, Any]:
    counts = collections.Counter(str(row.get("state") or "off") for row in widgets.plugin_rows())
    words = {"active": "On", "off": "Off", "loading": "Starting", "unloading": "Stopping", "failed": "Failed"}
    return {
        "rows": [
            {"label": words.get(state, state), "value": str(counts[state])} for state in words if counts.get(state)
        ]
    }


@reading("plugins.not_on", "The plugin rows that are off or failed, by the name the Plugins page shows. For rows.")
def _plugins_off(widgets: Widgets) -> dict[str, Any]:
    rows = [row for row in widgets.plugin_rows() if row.get("state") in ("off", "failed")]
    listed = [{"label": str(row.get("title") or row.get("id")), "value": str(row.get("state"))} for row in rows]
    return {"rows": listed or [{"label": "Every plugin is on", "value": ""}]}


@reading("cards.open", "How many cards and widgets are open beside the conversation now. For a reading.")
def _cards(widgets: Widgets) -> dict[str, Any]:
    from thomas.core.attention_cards import STORE

    return {"value": str(len(STORE.open_cards())), "unit": "open"}


class Widgets:
    """What turns a widget's blocks into what to draw now, for one running server."""

    def __init__(self, app: Any, folder: Path) -> None:
        self.app = app
        self.folder = Path(folder)
        self.started = time.time()
        self.cpu: collections.deque[float] = collections.deque(maxlen=120)
        self.memory: collections.deque[float] = collections.deque(maxlen=120)

    def plugin_rows(self) -> list[dict[str, Any]]:
        from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

        runtime = self.app.get(APP_RUNTIME_PLUGINS)
        return list(runtime.report()["rows"]) if runtime is not None else []

    def read(self, name: str) -> dict[str, Any]:
        entry = READINGS.get(name)
        if entry is None:
            return {}
        try:
            return entry[1](self) or {}
        except _UNREADABLE:
            return {}

    def switch(self, setting: str) -> dict[str, Any]:
        """A toggle's label and position, from the row itself."""
        row_id = setting.split(":", 1)[1]
        try:
            row = next((row for row in self.plugin_rows() if row.get("id") == row_id), None)
        except _UNREADABLE:
            row = None
        if row is None:
            return {"label": f"No plugin called {row_id}", "on": False, "locked": True}
        on = row.get("state") in ("active", "loading")
        return {
            "label": str(row.get("title") or row_id),
            "on": on,
            "locked": bool(row.get("required")),
            "state": str(row.get("state")),
        }

    def resolve(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        drawn = []
        for block in blocks:
            if block.get("reading"):
                block = fill(block, self.read(block["reading"]))
            if block["type"] == "toggle":
                block = {**block, **self.switch(block["setting"])}
            drawn.append(block)
        return drawn

    async def press(self, setting: str, on: bool) -> None:
        """Turn the row a toggle names on or off. ``ValueError`` says why not, in words for the card."""
        from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, Required

        if self.switch(setting).get("locked"):
            raise ValueError("That one cannot be turned off here.")
        runtime = self.app.get(APP_RUNTIME_PLUGINS)
        try:
            await (runtime.turn_on if on else runtime.turn_off)(setting.split(":", 1)[1])
        except Required:
            raise ValueError("That one cannot be turned off.") from None
        except _UNREADABLE as problem:
            raise ValueError(f"Thomas could not switch that: {problem}") from None

    def saved(self) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for path in sorted(self.folder.glob("*.json")) if self.folder.is_dir() else []:
            try:
                template = json.loads(path.read_text(encoding="utf-8"))
                found[path.stem] = {**template, "blocks": clean_blocks(template.get("blocks"))}
            except (OSError, ValueError, AttributeError):
                continue
        return found

    def templates(self) -> dict[str, dict[str, Any]]:
        return {**self.saved(), **BUILT_IN}

    def save(self, name: str, template: Any) -> dict[str, Any]:
        """Keep a widget under a name so it can be summoned again. Answers the template as saved."""
        if not _NAME.match(str(name)):
            raise ValueError("a template's name is 2 to 40 lowercase letters, digits and dashes")
        if name in BUILT_IN:
            raise ValueError(f"{name} is a widget that ships; save yours under another name")
        if not isinstance(template, dict) or not " ".join(str(template.get("title") or "").split()):
            raise ValueError("a template needs a title and blocks")
        kept = {
            "title": " ".join(str(template["title"]).split())[:120],
            "about": " ".join(str(template.get("about") or "").split())[:200],
            "every_seconds": float(template.get("every_seconds") or 0),
            "blocks": clean_blocks(template.get("blocks")),
        }
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{name}.json").write_text(json.dumps(kept, indent=2), encoding="utf-8")
        return kept

    def spec(self, name: str) -> dict[str, Any]:
        """The card to show for a template. One widget per template: summoning it again brings the same one forward."""
        template = self.templates().get(str(name))
        if template is None:
            raise ValueError(f"no widget called {name}. There are: {', '.join(sorted(self.templates()))}")
        return {
            "kind": "widget",
            "title": template["title"],
            "blocks": template["blocks"],
            "every_seconds": template.get("every_seconds") or 0,
            "key": f"widget-{name}",
            "template": str(name),
        }

    def catalogue(self) -> dict[str, Any]:
        """Everything a widget can be made from, for the tool that lists it and the route that answers it."""
        saved = self.saved()
        templates = [
            {"name": name, "title": row["title"], "about": row.get("about", ""), "ships": name in BUILT_IN}
            for name, row in sorted({**saved, **BUILT_IN}.items())
        ]
        return {
            "templates": templates,
            "readings": [{"name": name, "about": about} for name, (about, _) in sorted(READINGS.items())],
        }

    async def watch(self, store: Any, interval: float = 2.0) -> None:
        """Until cancelled: keep the last few minutes of load, and refill each open widget that is due."""
        while True:
            try:
                now, _cap = _load()
            except _UNREADABLE:
                now = None
            if now is not None:
                self.cpu.append(round(float(now.cpu), 1))
                self.memory.append(round(float(now.memory), 1))
            await asyncio.to_thread(store.refresh)
            await asyncio.sleep(interval)
