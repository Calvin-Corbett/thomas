"""Who made each commit on this checkout, counted from what every commit already says about itself.

Nothing here changes a commit or the history. A commit is read for four things, in this order, and the first that applies
names who made it:

1. Thomas's own work: a ``Thomas-Submitted-By`` or ``Thomas-Committed-By: self-change-promoter`` trailer, or an author
   address that is Thomas's account on GitHub (:data:`THOMAS_NOREPLY`).
2. A ``Thomas-Agent`` trailer, which names the agent that wrote it: ``claude``, ``codex`` and so on.
3. A ``Co-Authored-By`` line that names Claude, Codex or Thomas.
4. Nothing of those: you made it.

A commit made before these trailers existed is counted as yours, because that is the only thing the history says about it.
Counts come from ``git log`` run through :func:`thomas.core.git_process.run_git`, so a slow repository cannot hold the
caller longer than its timeout. A copy of Thomas with no repository beside it answers with an ``error`` and no counts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from thomas.core.git_process import run_git

#: The address GitHub gives the Thomas-Agent account, which links its commits to its profile.
THOMAS_NOREPLY = "352198248+thomas-agent@users.noreply.github.com"
THOMAS = "thomas"
YOU = "you"
#: The actors shown even when they have made nothing, in the order a person reads them.
ALWAYS_SHOWN = (THOMAS, "claude", "codex", YOU)
RECENT_DAYS = 30
_RECORD = "\x1e"
_FIELD = "\x1f"
_FORMAT = f"{_RECORD}%H{_FIELD}%ae{_FIELD}%ct{_FIELD}%(trailers:only,unfold)"
_SELF_CHANGE_TOOLS = ("self-change-promoter",)

_cache: dict[tuple[str, str, int], Tally] = {}


@dataclass(frozen=True)
class Tally:
    """The counts for one checkout: every commit, and the ones from the last :data:`RECENT_DAYS` days."""

    total: dict[str, int] = field(default_factory=dict)
    recent: dict[str, int] = field(default_factory=dict)
    commits: int = 0
    error: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "total": dict(self.total),
            "recent": dict(self.recent),
            "commits": self.commits,
            "recent_days": RECENT_DAYS,
            "error": self.error,
        }


def _trailers(block: str) -> list[tuple[str, str]]:
    pairs = []
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            pairs.append((key.strip().lower(), value.strip()))
    return pairs


def _named(text: str) -> str:
    low = text.lower()
    if "thomas-agent" in low or "thomas agent" in low:
        return THOMAS
    if "claude" in low or "anthropic" in low:
        return "claude"
    if "codex" in low or "openai" in low or "gpt" in low:
        return "codex"
    return ""


def _agent(name: str) -> str:
    """The actor an agent's own name belongs to: ``claude-perf`` is Claude's, and ``human`` is you."""
    for family in ("claude", "codex"):
        if name == family or name.startswith(f"{family}-"):
            return family
    if name in {"thomas", "thomas-agent"}:
        return THOMAS
    if name in {"human", "you"}:
        return YOU
    return name


def who_made(author_email: str, trailer_block: str) -> str:
    """The actor a commit belongs to, from its author address and its trailers."""
    pairs = _trailers(trailer_block)
    values = {}
    for key, value in pairs:
        values.setdefault(key, []).append(value)
    if author_email.strip().lower() == THOMAS_NOREPLY:
        return THOMAS
    if "thomas-submitted-by" in values:
        return THOMAS
    if any(v.lower() in _SELF_CHANGE_TOOLS for v in values.get("thomas-committed-by", [])):
        return THOMAS
    for agent in values.get("thomas-agent", []):
        name = agent.lower().strip()
        if name:
            return _agent(name)
    for line in values.get("co-authored-by", []):
        named = _named(line)
        if named:
            return named
    return YOU


def _count(rows: list[tuple[str, int]], since: int) -> tuple[dict[str, int], dict[str, int]]:
    total = dict.fromkeys(ALWAYS_SHOWN, 0)
    recent = dict.fromkeys(ALWAYS_SHOWN, 0)
    for actor, when in rows:
        total[actor] = total.get(actor, 0) + 1
        if when >= since:
            recent[actor] = recent.get(actor, 0) + 1
    for actor in total:
        recent.setdefault(actor, 0)
    return total, recent


def tally(repo: str | Path, *, rev: str = "HEAD", now: float | None = None, timeout: float = 60.0) -> Tally:
    """Count the commits reachable from ``rev`` in ``repo`` by who made them. Merge commits are not counted."""
    clock = time.time() if now is None else now
    head = run_git(["rev-parse", rev], cwd=repo, timeout=10.0)
    if not head.ok:
        return Tally(error="Thomas could not read the history of this copy.")
    key = (str(repo), head.output().strip(), int(clock // 86400))
    if key in _cache:
        return _cache[key]
    log = run_git(["log", "--no-merges", f"--format={_FORMAT}", rev], cwd=repo, timeout=timeout)
    if not log.ok:
        return Tally(error="Thomas could not read the history of this copy.")
    rows: list[tuple[str, int]] = []
    for record in log.stdout.split(_RECORD):
        parts = record.split(_FIELD, 3)
        if len(parts) != 4:
            continue
        try:
            when = int(parts[2])
        except ValueError:
            continue
        rows.append((who_made(parts[1], parts[3]), when))
    total, recent = _count(rows, int(clock - RECENT_DAYS * 86400))
    result = Tally(total=total, recent=recent, commits=len(rows))
    _cache.clear()
    _cache[key] = result
    return result
