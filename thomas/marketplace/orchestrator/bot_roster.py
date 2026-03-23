"""Bot Roster — maps Thomas's named office bots to specialist capabilities.

When Thomas delegates a task, he doesn't say "sending to the reasoning
specialist." He picks a NAMED BOT from the office roster — like Nova,
Trey, or Zach — and that bot spawns into the chat to do the work.

The roster defines which bots handle which types of work, their visual
identity (color, costume), and how to pick one when multiple bots share
a specialty.

The bot names and visuals come from OFFICE_AGENT_SEEDS in the frontend
runtime. This module is the Python-side mirror of that roster.

Architecture context for AI agents:
  - Used by brain_v3.py to pick a bot for each delegated task
  - Bot identity flows through events to the frontend for portal spawn
  - See plans/thomas/V3_CHAT_SPEC.md for the full picture
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Bot:
    """A named bot from Thomas's office."""

    id: str  # lowercase key: "nova", "trey", etc.
    name: str  # display name: "Nova", "Trey", etc.
    color: str  # hex color: "#4fc3f7"
    costume: str  # visual: "cap", "headset", "visor", "bowtie", ""
    tint: str  # color name: "blue", "green", etc.
    specialties: list[str]  # what this bot is good at

    def to_event_dict(self) -> dict[str, Any]:
        """Serialize for frontend event payload."""
        return {
            "bot_id": self.id,
            "bot_name": self.name,
            "bot_color": self.color,
            "bot_costume": self.costume,
            "bot_tint": self.tint,
        }


# ── The Official Roster ───────────────────────────────────────────────
# These match OFFICE_AGENT_SEEDS in app_runtime_primary.mjs.
# If you add a bot here, add it there too.

ROSTER: list[Bot] = [
    Bot("brandon", "Brandon", "#42a5f5", "visor", "blue", ["reasoning", "planning", "general"]),
    Bot("trey", "Trey", "#66bb6a", "headset", "green", ["research", "analysis"]),
    Bot("zach", "Zach", "#ffa726", "cap", "orange", ["coding", "tools", "engineering"]),
    Bot("matt", "Matt", "#ec407a", "bowtie", "pink", ["synthesis", "design", "creative"]),
    Bot("taylor", "Taylor", "#ab47bc", "", "purple", ["reasoning", "analysis", "planning"]),
    Bot("john", "John", "#ffee58", "visor", "yellow", ["reasoning", "support", "general"]),
    Bot("nova", "Nova", "#4fc3f7", "cap", "blue", ["research", "analysis", "reasoning"]),
    Bot("pixel", "Pixel", "#69f0ae", "headset", "green", ["creative", "synthesis", "design"]),
    Bot("byte", "Byte", "#ce93d8", "bowtie", "purple", ["coding", "tools", "data"]),
    Bot("orbit", "Orbit", "#90caf9", "", "blue", ["tools", "ops", "engineering"]),
    Bot("echo", "Echo", "#a5d6a7", "visor", "green", ["research", "synthesis", "comms"]),
    Bot("glitch", "Glitch", "#ffcc80", "cap", "orange", ["coding", "debug", "tools"]),
]

# Lookup by ID
_BY_ID: dict[str, Bot] = {bot.id: bot for bot in ROSTER}

# Lookup by specialty → list of bots
_BY_SPECIALTY: dict[str, list[Bot]] = {}
for _bot in ROSTER:
    for _spec in _bot.specialties:
        _BY_SPECIALTY.setdefault(_spec, []).append(_bot)


def get_bot(bot_id: str) -> Bot | None:
    """Get a bot by ID."""
    return _BY_ID.get(bot_id.lower().strip())


def pick_bot_for_specialist(specialist_id: str, *, exclude: set[str] | None = None) -> Bot:
    """Pick a named bot for a specialist type.

    Maps specialist IDs (reasoning, coding, research, etc.) to bots
    that have that specialty. Picks randomly for variety — you won't
    always see the same bot for the same task type.

    If no bot matches the specialty, falls back to Brandon (general).
    If all matching bots are excluded (busy), falls back to any available bot.
    """
    exclude = exclude or set()

    # Map specialist ID to roster specialties
    specialty_map = {
        "reasoning": "reasoning",
        "coding": "coding",
        "research": "research",
        "synthesis": "synthesis",
        "tools": "tools",
    }
    specialty = specialty_map.get(specialist_id, "general")

    # Find available bots with this specialty
    candidates = [b for b in _BY_SPECIALTY.get(specialty, []) if b.id not in exclude]

    # Fallback: any bot not excluded
    if not candidates:
        candidates = [b for b in ROSTER if b.id not in exclude]

    # Final fallback: Brandon always available
    if not candidates:
        return _BY_ID["brandon"]

    return random.choice(candidates)


def all_bots() -> list[Bot]:
    """Return the full roster."""
    return list(ROSTER)
