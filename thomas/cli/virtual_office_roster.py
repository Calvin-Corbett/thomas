"""Expose the canonical browser Virtual Office agent seeds to the Thomas REPL."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VirtualAgent:
    agent_id: str
    name: str
    role: str
    color: str  # Rich color name
    accent: str  # hex
    specialty: str


def _hex_to_rich_color(hex_color: str) -> str:
    """Map a hex body color to a Rich named color."""
    hx = hex_color.lstrip("#")
    if len(hx) < 6:
        return "cyan"
    try:
        r = int(hx[0:2], 16)
        g = int(hx[2:4], 16)
        b = int(hx[4:6], 16)
    except ValueError:
        return "cyan"

    if r > 180 and g < 120 and b < 120 and abs(g - b) < 60:
        return "red"
    if r > 100 and b > 110 and g < 100:
        return "purple"
    # Cyan before blue: G and B both high and nearly equal, no red
    if g > 130 and b > 130 and r < 100 and abs(g - b) < 50:
        return "cyan"
    if b > r and b > g and b > 130 and r < 130:
        return "blue"
    if g > r and g > b and g > 120:
        return "green"
    if r > 160 and g > 100 and b < 100:
        return "yellow"
    return "cyan"


# ---------------------------------------------------------------------------
# Cache state
# ---------------------------------------------------------------------------
_cached_roster: tuple["VirtualAgent", ...] | None = None
_cached_mtime_ns: int | None = None
_cached_path: Path | None = None


def _canonical_agent_seed_path() -> Path:
    """Return the active browser runtime file that owns ``OFFICE_AGENT_SEEDS``."""
    return Path(__file__).resolve().parents[1] / "server" / "web" / "js" / "runtime" / "office_static_config.js"


_SEED_BLOCK_RE = re.compile(r"\bconst\s+OFFICE_AGENT_SEEDS\s*=\s*\[(?P<body>.*?)\];", re.DOTALL)
_SEED_OBJECT_RE = re.compile(r"\{(?P<body>[^{}]*)\}", re.DOTALL)
_SEED_FIELD_RE = re.compile(
    r"\b(?P<key>name|color|specialty)\s*:\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)


def _parse_agents_from_seed_source(source_path: Path) -> tuple["VirtualAgent", ...]:
    """Parse ``OFFICE_AGENT_SEEDS`` from the active browser runtime source."""
    try:
        text = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("Cannot read Virtual Office agent seeds from %s: %s", source_path, exc)
        return ()

    block_match = _SEED_BLOCK_RE.search(text)
    if block_match is None:
        log.warning("OFFICE_AGENT_SEEDS was not found in %s", source_path)
        return ()

    agents: list[VirtualAgent] = []
    for object_match in _SEED_OBJECT_RE.finditer(block_match.group("body")):
        fields = {
            match.group("key"): match.group("value")
            for match in _SEED_FIELD_RE.finditer(object_match.group("body"))
        }
        if not {"name", "color", "specialty"}.issubset(fields):
            continue
        name = fields["name"]
        seed_color = fields["color"]
        specialty = fields["specialty"]
        agents.append(
            VirtualAgent(
                agent_id=name.lower(),
                name=name,
                role=specialty,
                color=_hex_to_rich_color(seed_color),
                accent=seed_color,
                specialty=specialty,
            )
        )

    log.debug("Parsed %d canonical agents from %s", len(agents), source_path)
    return tuple(agents)


def get_roster() -> tuple[VirtualAgent, ...]:
    """Return canonical agents, reloading when the active JS seed file changes."""
    global _cached_roster, _cached_mtime_ns, _cached_path

    source_path = _canonical_agent_seed_path()
    try:
        mtime_ns = source_path.stat().st_mtime_ns
    except OSError as exc:
        if _cached_roster is not None:
            log.warning("Keeping cached Virtual Office roster after source stat failed: %s", exc)
            return _cached_roster
        raise RuntimeError(f"Canonical Virtual Office agent seed source is unavailable: {source_path}") from exc

    if _cached_roster is not None and _cached_path == source_path and _cached_mtime_ns == mtime_ns:
        return _cached_roster

    parsed = _parse_agents_from_seed_source(source_path)
    if parsed:
        _cached_roster = parsed
        _cached_mtime_ns = mtime_ns
        _cached_path = source_path
    else:
        if _cached_roster is not None:
            log.warning("Keeping cached Virtual Office roster after seed parsing failed")
            return _cached_roster
        raise RuntimeError(f"No OFFICE_AGENT_SEEDS could be parsed from {source_path}")

    return _cached_roster


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _by_id() -> dict[str, VirtualAgent]:
    return {a.agent_id: a for a in get_roster()}


def _by_name() -> dict[str, VirtualAgent]:
    return {a.name.lower(): a for a in get_roster()}


# ---------------------------------------------------------------------------
# Assignment tracking
# ---------------------------------------------------------------------------
_active_assignments: dict[str, str] = {}  # task_key -> agent_id
_round_robin_index: int = 0


def get_agent(agent_id: str) -> VirtualAgent | None:
    """Look up an agent by id or (case-insensitive) name."""
    agent_id_lower = agent_id.lower()
    by_id = _by_id()
    by_name = _by_name()
    return by_id.get(agent_id_lower) or by_name.get(agent_id_lower)


def assign_agent(task_key: str, preferred_id: str | None = None) -> VirtualAgent:
    """
    Return a persistent agent assignment for *task_key*.

    If *preferred_id* is given and resolves to a known agent that assignment is
    used.  Otherwise a round-robin agent is chosen from the roster.
    """
    global _round_robin_index

    # Return existing assignment if already set.
    if task_key in _active_assignments:
        agent = get_agent(_active_assignments[task_key])
        if agent:
            return agent

    # Try preferred agent.
    if preferred_id:
        agent = get_agent(preferred_id)
        if agent:
            _active_assignments[task_key] = agent.agent_id
            return agent

    # Round-robin fallback.
    roster = get_roster()
    agent = roster[_round_robin_index % len(roster)]
    _round_robin_index += 1
    _active_assignments[task_key] = agent.agent_id
    return agent


def release_agent(task_key: str) -> None:
    """Remove the assignment for *task_key*."""
    _active_assignments.pop(task_key, None)


def get_assignment(task_key: str) -> VirtualAgent | None:
    """Return the agent currently assigned to *task_key*, or None."""
    agent_id = _active_assignments.get(task_key)
    return get_agent(agent_id) if agent_id else None


def list_active() -> dict[str, VirtualAgent]:
    """Return a mapping of task_key -> VirtualAgent for all active assignments."""
    result: dict[str, VirtualAgent] = {}
    for task_key, agent_id in list(_active_assignments.items()):
        agent = get_agent(agent_id)
        if agent:
            result[task_key] = agent
    return result


def format_agent_label(agent: VirtualAgent, model: str = "") -> str:
    """Return a short display label such as ``BRANDON [codex]``."""
    name_part = agent.name.upper()
    model_part = f" [{model}]" if model else ""
    return f"{name_part}{model_part}"


# ---------------------------------------------------------------------------
# Specialist map
# ---------------------------------------------------------------------------
SPECIALIST_AGENT_MAP: dict[str, str] = {
    "engineering": "brandon",
    "research": "trey",
    "creative": "pixel",
    "ops": "nova",
    "support": "john",
    "gaming": "zach",
    "security": "glitch",
    "data": "byte",
    "design": "matt",
    "qa": "john",
    "devops": "nova",
    "planning": "taylor",
    "documentation": "echo",
    "integration": "orbit",
    "debugging": "glitch",
}


def agent_for_specialist(specialist_type: str) -> VirtualAgent | None:
    """Return the agent best suited for *specialist_type*, or None."""
    agent_id = SPECIALIST_AGENT_MAP.get(specialist_type.lower())
    return get_agent(agent_id) if agent_id else None
