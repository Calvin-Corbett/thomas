"""Which files other agents claim on the workboard, read from the board's own text.

A self-edit run is handed this list as its protected paths, so the write tools and not the prose keep it out of
other agents' files. It lived beside the redesign planner, which imports the overlay, and every self-edit reached it
through that module. It has no part in the overlay, so it is here, and nothing in it reads a file or the environment.
"""

from __future__ import annotations

import re

_CLAIM_LINE_RE = re.compile(r"^\s*-\s*agent=(?P<agent>[^;]+);(?P<rest>.*)$")
_CLAIM_SCOPE_RE = re.compile(r"(?:^|;)\s*scope=(?P<scope>[^;]*)")


def board_fenced_paths(workboard_text: str, *, exempt_agents: set[str]) -> list[str]:
    """Every scope entry another agent claims on the workboard, sorted, deduplicated.

    Only lines in the "## Agent Claims" section count; an agent in
    ``exempt_agents`` (the server's own environment decides who) is not fenced.
    A self-edit run gets this list as ``protected_paths`` so the write tools,
    not the prose, keep it out of other agents' files.
    """

    fenced: set[str] = set()
    in_claims = False
    for raw in str(workboard_text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            in_claims = line.strip().lower() == "## agent claims"
            continue
        if not in_claims:
            continue
        match = _CLAIM_LINE_RE.match(line)
        if not match:
            continue
        agent = match.group("agent").strip()
        if agent in exempt_agents:
            continue
        scope = _CLAIM_SCOPE_RE.search(match.group("rest"))
        if not scope:
            continue
        for entry in scope.group("scope").split(","):
            entry = entry.strip().replace("\\", "/")
            if entry and entry != "unknown":
                fenced.add(entry)
    return sorted(fenced)
