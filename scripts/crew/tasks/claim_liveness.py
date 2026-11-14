"""Proof that a claim is LIVE, so the dead-claim sweep never takes it.

The sweep judged a claim by its agent's last board message alone. Measured
2026-10-03 on a fixture: a claim written a moment ago (`claimed_at=now`) by an
agent whose last message was three days old read as `agent_activity_timeout`
(4320 minutes) and would have been reaped on the next cycle. A reused agent id
(`claude`) loses a fresh claim over an old message the same way.

Two pieces of timing evidence outrank a quiet message log:

* the claim says how old it is (`claimed_at=`), and a claim younger than a floor
  (24 hours) is never stale, whatever its agent last said;
* the agent's presence session heartbeat is recent (within the idle window).

When the check itself fails the claim is spared: not knowing is not a reason to
take someone's work.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.forge.gates.workboard_claim_freshness import _CLAIMED_AT_RE  # noqa: E402

FLOOR_MINUTES = 24 * 60.0
_CLAIM_ROW_AGENT = re.compile(r"^\s*-\s*`?agent=([^;]+);")
CLOCK_SKEW_SECONDS = 300.0


def default_presence_dir(workboard_path: Path) -> Path | None:
    """The repo's presence folder, but only for a board inside this repo."""

    try:
        inside = Path(workboard_path).resolve().is_relative_to(_REPO_ROOT)
    except (OSError, ValueError):
        return None
    return (_REPO_ROOT / "runtime" / "coordination" / "presence") if inside else None


def _heartbeat_unix(path: Path, agent_key: str) -> float | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or str(payload.get("state") or "").strip().lower() == "closed":
        return None
    if str(payload.get("agent_id") or "").strip().casefold() != agent_key:
        return None
    raw = str(payload.get("last_heartbeat_at") or "").strip()
    try:
        stamp = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def latest_heartbeat_unix(agent: str, presence_dir: Path | None) -> float | None:
    """Newest heartbeat of any open session bound to `agent`, or None."""

    if presence_dir is None or not presence_dir.is_dir():
        return None
    key = str(agent).strip().casefold()
    beats = [_heartbeat_unix(path, key) for path in presence_dir.glob("*.json")]
    found = [beat for beat in beats if beat is not None]
    return max(found) if found else None


def declared_unix_for_agent(workboard_path: Path, agent: str) -> int | None:
    """`claimed_at` of the claim row held by `agent`, found by agent id, never by line number.

    Line numbers shift whenever any claim above is added or released, and blame can take seconds
    between the sweep's evaluation and this read. An unreadable or empty board raises OSError, which
    the caller turns into "spare the claim": not being able to look is not a reason to take it.
    """

    text = Path(workboard_path).read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise OSError(f"board is empty or mid-write: {workboard_path}")
    key = str(agent).strip().casefold()
    for line in text.splitlines():
        row = _CLAIM_ROW_AGENT.match(line)
        if not row or row.group(1).strip().casefold() != key or "; scope=" not in line:
            continue
        match = _CLAIMED_AT_RE.search(line)
        if not match:
            return None
        try:
            parsed = datetime.fromisoformat(match.group(1).strip())
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    return None


def live_reason(
    *,
    workboard_path: Path,
    line_no: int,
    agent: str,
    now: datetime,
    max_idle_minutes: float,
    presence_dir: Path | None,
    floor_minutes: float = FLOOR_MINUTES,
) -> str | None:
    """Why this claim must not be reaped, or None when nothing shows it is live."""

    now_ts = now.timestamp()
    try:
        declared = declared_unix_for_agent(workboard_path, agent)
        beat = latest_heartbeat_unix(agent, presence_dir)
    except (OSError, ValueError):
        return "liveness_check_failed"
    if declared is not None and declared <= now_ts + CLOCK_SKEW_SECONDS:
        if now_ts - declared < float(floor_minutes) * 60.0:
            return "claim_younger_than_floor"
    if beat is not None and beat <= now_ts + CLOCK_SKEW_SECONDS:
        if now_ts - beat <= float(max_idle_minutes) * 60.0:
            return "recent_heartbeat"
    return None


def declared_claim_time(workboard_path: Path, agent: str) -> datetime | None:
    """`claimed_at` of this agent's claim as a datetime, or None if it does not say."""

    try:
        stamp = declared_unix_for_agent(workboard_path, agent)
    except (OSError, ValueError):
        return None
    return None if stamp is None else datetime.fromtimestamp(stamp, tz=timezone.utc)
