"""Virtual Office agent roster for the Thomas REPL. Dynamically parses agent definitions from virtual_office.html so that renaming an agent in the Virtual Office propagates everywhere."""

import logging
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VirtualAgent:
    agent_id: str
    name: str
    role: str
    color: str   # Rich color name
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


# Ordered list of (keyword, specialty) tuples -- specific before general so that
# e.g. "devops" matches before "ops" and "engineer" never steals a more precise hit.
_ROLE_KEYWORDS: list[tuple[str, str]] = [
    ("ops",      "Operations"),
    ("devops",   "DevOps"),
    ("research", "Research"),
    ("creative", "Creative"),
    ("support",  "Support"),
    ("game",     "Gaming"),
    ("security", "Security"),
    ("data",     "Data"),
    ("design",   "Design"),
    ("qa",       "QA"),
    ("engineer", "Engineering"),   # last -- avoids false matches on e.g. "research"
]


def _role_to_specialty(role: str) -> str:
    """Return a specialty string by scanning the role text for known keywords."""
    role_lower = role.lower()
    for keyword, specialty in _ROLE_KEYWORDS:
        if keyword in role_lower:
            return specialty
    return "General"


# ---------------------------------------------------------------------------
# Cache state
# ---------------------------------------------------------------------------
_cached_roster: tuple["VirtualAgent", ...] | None = None
_cached_mtime: float | None = None
_cached_path: Path | None = None


def _find_virtual_office_html() -> Path | None:
    """Search several candidate locations for virtual_office.html."""
    project_root = Path(__file__).resolve().parent.parents[1]
    candidates = [
        project_root / "virtual_office.html",
        project_root / "thomas" / "server" / "web" / "virtual_office.html",
        project_root / "thomas" / "server" / "web" / "static" / "virtual_office.html",
        Path(os.getcwd()) / "virtual_office.html",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


# Regex that matches a single agent entry in the JS agents array inside the HTML.
# Named groups: id, name, role, body (customization block text), accent extracted separately.
_AGENT_RE = re.compile(
    r"""
    \{[^}]*                              # opening of object literal
    id\s*:\s*'(?P<id>[^']+)'            # id field
    .*?                                  # anything in between
    name\s*:\s*'(?P<name>[^']+)'        # name field
    .*?                                  # anything in between
    role\s*:\s*'(?P<role>[^']+)'        # role field
    .*?                                  # anything in between
    customization\s*:\s*\{(?P<body>.*?)\}  # customization block
    """,
    re.VERBOSE | re.DOTALL,
)

_ACCENT_RE = re.compile(r"accentColor\s*:\s*'(?P<accent>[^']+)'")
_BODY_RE   = re.compile(r"bodyColor\s*:\s*'(?P<body>[^']+)'")


def _parse_agents_from_html(html_path: Path) -> tuple["VirtualAgent", ...]:
    """Parse agent definitions out of *html_path* and return a tuple of VirtualAgent."""
    try:
        text = html_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("Cannot read %s: %s", html_path, exc)
        return ()

    agents: list[VirtualAgent] = []
    for m in _AGENT_RE.finditer(text):
        name       = m.group("name")
        role       = m.group("role")
        body_block = m.group("body")

        body_m   = _BODY_RE.search(body_block)
        accent_m = _ACCENT_RE.search(body_block)

        body_hex   = body_m.group("body")    if body_m   else "#008B8B"
        accent_hex = accent_m.group("accent") if accent_m else "#FFFFFF"

        rich_color = _hex_to_rich_color(body_hex)
        specialty  = _role_to_specialty(role)

        agents.append(VirtualAgent(
            agent_id  = name.lower(),   # use display name (lower-cased) as stable id
            name      = name,
            role      = role,
            color     = rich_color,
            accent    = accent_hex,
            specialty = specialty,
        ))

    log.debug("Parsed %d agents from %s", len(agents), html_path)
    return tuple(agents)


# ---------------------------------------------------------------------------
# Default fallback roster (used when HTML is not found or yields no agents)
# ---------------------------------------------------------------------------
_DEFAULT_ROSTER: tuple[VirtualAgent, ...] = (
    VirtualAgent("atlas",  "Atlas",  "Engineering Lead",    "blue",   "#2E5C8A", "Engineering"),
    VirtualAgent("nova",   "Nova",   "Research Specialist", "purple", "#6C3A7D", "Research"),
    VirtualAgent("spark",  "Spark",  "Creative Director",   "yellow", "#CC7700", "Creative"),
    VirtualAgent("cipher", "Cipher", "Ops Engineer",        "green",  "#2E7D4E", "Operations"),
    VirtualAgent("echo",   "Echo",   "Support Lead",        "cyan",   "#008B8B", "Support"),
    VirtualAgent("pixel",  "Pixel",  "Game Master",         "red",    "#CC3333", "Gaming"),
)


def get_roster() -> tuple[VirtualAgent, ...]:
    """Return the current agent roster, reloading from HTML if the file has changed."""
    global _cached_roster, _cached_mtime, _cached_path

    html_path = _find_virtual_office_html()

    if html_path is None:
        if _cached_roster is None:
            log.debug("virtual_office.html not found; using default roster")
            _cached_roster = _DEFAULT_ROSTER
        return _cached_roster

    try:
        mtime = html_path.stat().st_mtime
    except OSError:
        return _cached_roster or _DEFAULT_ROSTER

    if (
        _cached_roster is not None
        and _cached_path == html_path
        and _cached_mtime == mtime
    ):
        return _cached_roster

    parsed = _parse_agents_from_html(html_path)
    if parsed:
        _cached_roster = parsed
        _cached_mtime  = mtime
        _cached_path   = html_path
    else:
        log.warning("No agents parsed from %s; using default roster", html_path)
        _cached_roster = _DEFAULT_ROSTER

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
_active_assignments: dict[str, str] = {}   # task_key -> agent_id
_round_robin_index: int = 0


def get_agent(agent_id: str) -> VirtualAgent | None:
    """Look up an agent by id or (case-insensitive) name."""
    agent_id_lower = agent_id.lower()
    by_id   = _by_id()
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
    agent  = roster[_round_robin_index % len(roster)]
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
    """Return a short display label such as "ATLAS [codex]"."""
    name_part  = agent.name.upper()
    model_part = f" [{model}]" if model else ""
    return f"{name_part}{model_part}"


# ---------------------------------------------------------------------------
# Specialist map
# ---------------------------------------------------------------------------
SPECIALIST_AGENT_MAP: dict[str, str] = {
    "engineering": "atlas",
    "research":    "nova",
    "creative":    "spark",
    "ops":         "cipher",
    "support":     "echo",
    "gaming":      "pixel",
    "security":    "cipher",
    "data":        "nova",
    "design":      "spark",
    "qa":          "echo",
    "devops":      "cipher",
}


def agent_for_specialist(specialist_type: str) -> VirtualAgent | None:
    """Return the agent best suited for *specialist_type*, or None."""
    agent_id = SPECIALIST_AGENT_MAP.get(specialist_type.lower())
    return get_agent(agent_id) if agent_id else None
