"""The widgets that ship: each a title, how often it refreshes, a line saying what it is for, and its blocks.

To add one, add an entry here. Its blocks are the eight kinds in ``thomas.core.attention_blocks``; a block that names a
``reading`` is filled from ``thomas.server.attention_widgets.READINGS`` each time the widget refreshes. Nothing else
needs to change: the name is summoned with the ``attention_widget`` tool or ``POST /api/attention/widgets/<name>``.
``docs/attention_widgets.md`` walks through it.
"""

from __future__ import annotations

from typing import Any


def _meter(label: str, source: str) -> dict[str, Any]:
    return {"type": "meter", "label": label, "reading": source}


#: The widgets that ship. A template is a title, how often it refreshes, a line saying what it is for, and its blocks.
BUILT_IN: dict[str, dict[str, Any]] = {
    "machine": {
        "title": "This PC",
        "about": "CPU and memory now, against the limit where Thomas holds new work, and the last few minutes of CPU.",
        "every_seconds": 4,
        "blocks": [
            _meter("CPU", "machine.cpu"),
            _meter("Memory", "machine.memory"),
            {"type": "spark", "label": "CPU, last few minutes", "reading": "machine.cpu_history"},
        ],
    },
    "thomas": {
        "title": "Thomas",
        "about": "The version and commit that are running, how long for, and whether a restart is waiting.",
        "every_seconds": 10,
        "blocks": [{"type": "rows", "reading": "thomas.facts"}],
    },
    "plugins": {
        "title": "Plugins",
        "about": "How many plugin rows are on, and which ones are off or failed.",
        "every_seconds": 10,
        "blocks": [
            {"type": "rows", "reading": "plugins.summary"},
            {"type": "rows", "label": "Not on", "reading": "plugins.not_on"},
        ],
    },
    "switches": {
        "title": "Quick switches",
        "about": "Switches for four plugin rows: the Agents page, Work, the notification tools and reply display types.",
        "every_seconds": 5,
        "blocks": [
            {"type": "toggle", "setting": f"row:{row}"} for row in ("agents", "work", "notifications", "display")
        ],
    },
    "overview": {
        "title": "At a glance",
        "about": "CPU, memory, what Thomas is running and how many plugins are on, in one widget.",
        "every_seconds": 5,
        "blocks": [
            _meter("CPU", "machine.cpu"),
            _meter("Memory", "machine.memory"),
            {"type": "rows", "reading": "thomas.facts"},
            {"type": "rows", "label": "Plugins", "reading": "plugins.summary"},
        ],
    },
}
