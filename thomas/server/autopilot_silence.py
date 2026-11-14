"""Record each server's life and decide whether an unfinished Autopilot run can carry on.

What is heard from a run is its start or the last write to its transcript (:func:`last_heard`).
Every conversation in the catalog with an unfinished run is eligible, even if the server was
powered off for weeks or there is no record of the previous server's life.

Each server records its boot, last sign of life and the runs its pass deliberately left stopped
(:func:`life_path`). A run heard from after that server booted and silent for more than
:func:`grace_s` before its last sign of life went quiet while it ran, and waits for a message
from you. A run last heard from before it booted belongs to an earlier server and carries on,
unless the previous pass deliberately left it stopped. Runs that this pass could not start go
in its carrying list so the next server can try again.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.forge.anvil.forge_code_settings import EXECUTION_TIMEOUTS_S

HEARTBEAT_S = 300.0  # how often a running server records that it is alive
LIFE_NAME = "server_life.json"


@dataclass(frozen=True)
class Life:
    """What a server recorded about itself for the next one."""

    booted_at: float
    alive_at: float
    stopped: frozenset[str] = frozenset()  # runs its restart pass left waiting for you
    carrying: frozenset[str] = frozenset()  # runs its restart pass was still about to carry on


def last_heard(catalog_root: Path, run_id: str, started: float) -> float:
    """When anything was last heard from run *run_id*: its start, or the last write to its transcript if later."""
    if not run_id:
        return started
    from thomas.forge.anvil.run_files import transcript_path as _transcript_path

    try:
        written = _transcript_path(Path(catalog_root), run_id).stat().st_mtime
    except OSError:  # no transcript: the run was stopped before it wrote anything
        return started
    return max(started, written)


def grace_s(conversation: dict[str, Any]) -> float:
    """How long a live run of *conversation* can go without a word: two of its pass limits and 15 minutes."""
    requested = ((conversation.get("settings") or {}).get("requested") or {}) if isinstance(conversation, dict) else {}
    dial = str(requested.get("token_economy") or "max") if isinstance(requested, dict) else "max"
    return 2.0 * EXECUTION_TIMEOUTS_S.get(dial, EXECUTION_TIMEOUTS_S["max"]) + 15 * 60.0


def silent_for(heard_at: float, booted: float) -> float:
    """Seconds between the last thing heard from a run and the boot; never negative."""
    return max(0.0, booted - heard_at)


def took(seconds: float) -> str:
    return f"{seconds / 60:.0f} minutes" if seconds < 3600 else f"{seconds / 3600:.1f} hours"


def carried_on_words(silent_s: float) -> str:
    """The one-line reason a carry-on gets in the pass's report and the server log."""
    return f"nothing was heard from its Build run for {took(silent_s)} before this server started"


def life_path(catalog_root: Path) -> Path:
    """Beside Build's run receipts for this catalog, in this server's own data folder: two servers that share a
    checkout keep their own receipts, and so their own lives."""
    from thomas.server.routes.evolve_agent_receipts import _receipt_path

    return _receipt_path(Path(catalog_root)).with_name(LIFE_NAME)


def _life(raw: Any) -> Life | None:
    if not isinstance(raw, dict):
        return None
    try:
        booted = float(raw["booted_at"])
        alive = float(raw.get("alive_at") or booted)
    except (KeyError, TypeError, ValueError):
        return None
    stopped, carrying = (frozenset(str(cid) for cid in raw.get(key) or []) for key in ("stopped", "carrying"))
    return Life(booted, max(booted, alive), stopped, carrying)


def previous_life(catalog_root: Path, booted: float) -> Life | None:
    """The life of the server before the one that started at *booted*; None when nothing recorded one."""
    try:
        raw = json.loads(life_path(catalog_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    life = _life(raw)
    if life is not None and life.booted_at < booted:
        return life
    return _life(raw.get("before")) if isinstance(raw, dict) else None  # this server's own: the one before is inside


def record_life(catalog_root: Path, life: Life, before: Life | None) -> None:
    """Write this server's life, with the one before it inside, replacing the file in one step."""

    def plain(item: Life) -> dict[str, Any]:
        return {"booted_at": item.booted_at, "alive_at": item.alive_at, "stopped": sorted(item.stopped),
                "carrying": sorted(item.carrying)}  # fmt: skip

    path = life_path(catalog_root)
    payload = {**plain(life), "before": plain(before) if before is not None else None}
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".server-life-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(payload, out)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            Path(temporary).unlink(missing_ok=True)


def stopped_with_the_server(
    before: Life | None, cid: str, started: float, heard: float, booted: float, grace: float
) -> tuple[str, float]:
    """Return why a run stays stopped, and its silence during the prior server's life.

    ``"earlier"`` means the prior pass deliberately left it stopped. ``"silent"`` means it
    was heard after that server started, then went quiet before its last sign of life.
    With no record, or a last word before that server started, the run can be carried on.
    """
    if before is None:
        return "", 0.0
    if started < before.booted_at and cid in before.stopped:
        return "earlier", 0.0
    if heard < before.booted_at:  # stopped with an earlier server, not silent during this one's life
        return "", 0.0
    if heard < before.alive_at - grace:
        return "silent", before.alive_at - heard
    return "", 0.0


def life_now(booted: float, alive: float, stopped: Iterable[str], carrying: Iterable[str]) -> Life:
    return Life(booted, max(booted, alive), frozenset(stopped), frozenset(carrying))


__all__ = [
    "HEARTBEAT_S",
    "LIFE_NAME",
    "Life",
    "carried_on_words",
    "grace_s",
    "last_heard",
    "life_now",
    "life_path",
    "previous_life",
    "record_life",
    "silent_for",
    "stopped_with_the_server",
    "took",
]
