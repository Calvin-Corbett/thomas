"""Where land.py runs: the repo, the commit tool, who the caller is, and how a lane is wired to the real world."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from scripts.crew.brief import land_git, landing_proc
from scripts.crew.brief.landing_queue import Config, Lane
from scripts.crew.brief.landing_store import FileTicketStore, resolve_queue_root

ROOT = Path(__file__).resolve().parents[3]
COMMIT: Path | None = None  # test seam: a stand-in commit tool (also THOMAS_LAND_COMMIT)
SESSION_KEYS = ("THOMAS_AGENT_SESSION_ID", "AGENT_SESSION_ID")
NOTHING_TO_STAGE = "no_claimed_changes"  # the commit tool's own blocker for "no changed file in the claim or --include"


def repo_root() -> Path:
    """The repo being landed into: THOMAS_LAND_ROOT (a test seam: a throwaway repo) or this checkout."""
    return Path(os.environ.get("THOMAS_LAND_ROOT") or ROOT)


def commit_path() -> Path:
    return Path(os.environ.get("THOMAS_LAND_COMMIT") or COMMIT or ROOT / "scripts" / "crew" / "brief" / "commit.py")


def resolve_identity(agent_arg: str, root: Path) -> tuple[str, str]:
    """(agent, session) the way the commit tool resolves it: the live session binding, never a bare env var or flag.

    Same condition as commit.py: a binding is required when a session id is in the environment or the repo is this
    checkout; only a throwaway repo with no session id falls back to the plain agent id."""
    from scripts.crew.brief import identity

    if any(str(os.getenv(k) or "").strip() for k in SESSION_KEYS) or root.resolve() == ROOT.resolve():
        bound = identity.require_bound_identity(agent_arg or None, repo_root=root)
        return bound.agent_id, bound.session_id
    return identity.resolve_agent(agent_arg or None) or "", ""


def presence_beat(root: Path, session: str) -> None:
    """Keep this session's heartbeat fresh while its ticket is open. Never revives a session that was closed."""
    try:
        from thomas.core import agent_presence_sessions as sessions

        sid = session or sessions.current_session_id()
        path = root / "runtime" / "coordination" / "presence" / f"{sid}.json"
        row = json.loads(path.read_text(encoding="utf-8"))
        if str(row.get("state") or "").strip().casefold() not in {"active", "alive"}:
            return
        sessions.heartbeat_session(repo_root=root, session_id=sid)
    except (ImportError, OSError, ValueError):  # a failed heartbeat must never cost the agent its turn
        pass


def staged_paths(root: Path, args: Any) -> list[str] | None:
    """What this landing would stage right now, as the commit tool's own dry run reports it.

    Unproven means not landed: paths are returned only for a dry run that finished and either passed or was refused by the commit
    tool's own nothing-to-stage blocker. Any other refusal (session identity, claim, P0, a gate) prints an empty path list before it
    ever chose a path, and a timeout says nothing at all: both return None."""
    from scripts.crew.brief import land_commit

    cmd = land_commit.commit_cmd(commit_path(), args, "land.py staged-set probe", dry=True)
    try:
        verdict, paths, timed_out = land_commit.dry_run(cmd, root, 120.0)
    except OSError:
        return None
    if timed_out or (not verdict.ok and verdict.blocker != NOTHING_TO_STAGE):
        return None
    return paths


def make_lane(
    root: Path, agent: str, session: str, cfg: Config, say: Any, staged_args: Any = None, **extra: Any
) -> Lane:
    def find_landed(key: str, includes: Any = (), own: bool = False) -> str | None:
        # Only the landing's own agent can ask the commit tool what ITS landing stages; anyone else has no probe.
        probe = (lambda: staged_paths(root, staged_args)) if own and staged_args is not None and not includes else None
        return land_git.find_landed(root, key, includes, cfg.window_commits, probe)

    return Lane(
        FileTicketStore(resolve_queue_root()),
        agent=agent,
        session=session,
        find_landed=find_landed,
        git_cleanup=lambda: landing_proc.clean_stale_locks(root),
        presence=lambda: presence_beat(root, session),
        say=say,
        cfg=cfg,
        **extra,
    )
