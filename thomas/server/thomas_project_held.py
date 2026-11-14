"""A Thomas project whose settle is held for whoever started it.

Autopilot settles a Thomas project on its own done check, with its own summary
(``evolve_agent_autopilot._thomas_project_should_settle``). A project whose
``thomas_project`` record carries ``hold_settle`` -- a ``meta`` field its starter
sets -- is never settled there: that starter, today the ratchet
(``thomas/server/ratchet/repair.py``), proves the team's result again first, and
then settles it with a summary that names what it proved.

So a held project needs two things Build itself does not: a way to read how it
ended without creating anything, and a way to end one that will not be handed in
while keeping its conversation readable. Both live here rather than in
``thomas_project``, which stays below the repo's 800-line limit.

Callers import this module directly -- ``thomas_project`` does not re-export it,
so nothing here changes that file. The two functions that need its private
readers import it when they run, which also keeps the dependency one-way.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_projects, forge_code_store

log = logging.getLogger(__name__)


def project_catalog_root() -> Path:
    """The root a Thomas project's conversation outlives its green in, for callers outside Build."""
    from thomas.server.thomas_project import _catalog_root

    return _catalog_root()


def held_outcome(project_root: Path, catalog_root: Path, cid: str) -> dict[str, Any] | None:
    """How a project whose settle is held (``hold_settle`` on its record) ended, read without creating anything.

    ``autonomy_level`` is the level Build recorded: Autopilot without your grant
    runs at a lower one (dial_elevation), and the ratchet records which it was.
    """
    from thomas.server.thomas_project import _read_live

    conversation = _read_live(project_root, catalog_root, cid)
    if conversation is None:
        return None
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    last = next((t for t in reversed(turns) if isinstance(t, dict) and t.get("role") == "agent"), None) or {}
    requested = (conversation.get("settings") or {}).get("requested") or {}
    return {
        "ok": bool(last.get("ok")),
        "outcome": str(last.get("outcome") or ""),
        "reason": str(last.get("reason") or "no run finished"),
        "autonomy_level": requested.get("autonomy_level"),
        "transcript_tail": str(last.get("transcript") or "")[-1500:],
    }


def record_retirement(catalog_root: Path, cid: str, *, outcome: str, reason: str = "", submission: str = "") -> None:
    """Record the ending on a retired project's catalog copy without marking it settled."""
    conversation = forge_code_store.load_conversation(catalog_root, cid)
    if conversation is None:
        return
    project = conversation.get("thomas_project")
    if not isinstance(project, dict):
        return
    project["retirement"] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outcome": outcome,
        "reason": reason,
        "submission": submission,
    }
    forge_code_store.write_conversation(catalog_root, conversation)


def retire_held(
    project_root: Path,
    catalog_root: Path,
    cid: str,
    *,
    outcome: str = "",
    reason: str = "",
    submission: str = "",
) -> None:
    """Copy a held conversation to the catalog and forget its green binding."""
    conversation = forge_code_store.load_conversation(project_root, cid)
    if conversation is not None:
        forge_code_store.write_conversation(catalog_root, conversation)
        if outcome:
            record_retirement(catalog_root, cid, outcome=outcome, reason=reason, submission=submission)
    try:
        forge_code_projects.forget_conversation(catalog_root, cid)
    except OSError:
        log.warning("could not forget %s's green binding after retiring it", cid, exc_info=True)


__all__ = ["held_outcome", "project_catalog_root", "retire_held"]
