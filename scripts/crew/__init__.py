"""Praxis.Crew construction umbrella -- scripts side.

Hosts the script-invoked Crew sub-pieces:
- Workboard (the status board: claims, issues, messaging, audit)
- Tasks (task manager family)
- Swarm (multi-process agent spawning)
- Brief (agent lifecycle: startup_router, briefing, identity, presence, etc.)
- Autopilot (scheduled/recurring autonomous tasks) -- lives in
  thomas/server/routes/, not scripts; not represented here.

Renamed from ``scripts/{workboard_*, agent_*}.py`` to align with Praxis
vocabulary.
"""
