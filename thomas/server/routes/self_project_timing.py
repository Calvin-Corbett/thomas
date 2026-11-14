"""Measured stage durations for the self-project list; missing endpoints stay unknown."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.server.precard.clocks import clocks_path
from thomas.server.routes.self_project_listing_cache import read_record
from thomas.server.routes.self_project_speed import speed_scoreboard
from thomas.server.self_change_status import outbox_dir

_STEP_ROWS: tuple[float, list[dict[str, Any]]] = (0.0, [])
STEP_ROWS_FRESH_S = 60.0  # the list refreshes every 30 s; eight days of step log is read at most once a minute


def _step_rows() -> list[dict[str, Any]]:
    """The last eight days of the step log, the scoreboard's today and last 7 days, read at most once a minute."""
    global _STEP_ROWS
    import time

    from thomas.core import step_log

    read_at, rows = _STEP_ROWS
    if time.monotonic() - read_at > STEP_ROWS_FRESH_S or not read_at:
        rows = step_log.read(days=8)
        _STEP_ROWS = (time.monotonic(), rows)
    return rows


def _disk_free_gb() -> float | None:
    """Free space on the drive holding Thomas's data, in GB."""
    import shutil

    from thomas.core.config import resolve_thomas_data_dir

    try:
        return round(shutil.disk_usage(resolve_thomas_data_dir()).free / 1e9, 1)
    except (OSError, RuntimeError, ValueError):
        return None


STAGES = ("building", "checks", "second_look", "repair_rounds", "card_wait")
LABELS = {
    "building": "building",
    "checks": "checks",
    "second_look": "second look",
    "repair_rounds": "repair rounds",
    "card_wait": "waiting for your card",
}
# A very large clock log must not hold up the live project listing.
MAX_CLOCK_BYTES = 4 * 1024 * 1024
_SUBMISSION_ID = re.compile(r"^self-[A-Za-z0-9_-]{1,160}$")


def _card_wait(cid: str, conversation: dict[str, Any], outbox: Path | None) -> float | None:
    """Sum completed sign-in prompts for this project's hand-in, not queue time."""
    if outbox is None:
        return None
    project = conversation.get("thomas_project")
    submission = project.get("submission") if isinstance(project, dict) else None
    if not isinstance(submission, str) or not _SUBMISSION_ID.fullmatch(submission):
        return None
    chat = str(project.get("chat_session_id") or "") or cid
    record = None
    for suffix in ("verdict", "pending"):
        path = outbox / f"{submission}.{suffix}.json"
        try:
            if path.stat().st_size > MAX_CLOCK_BYTES:
                continue
            candidate = read_record(path)
        except (OSError, ValueError):
            continue
        if isinstance(candidate, dict) and candidate.get("chat") == chat and candidate.get("card_prompts"):
            record = candidate
            break
    if record is None:
        return None
    total = 0.0
    seen = False
    prompts = record.get("card_prompts")
    for prompt in prompts if isinstance(prompts, list) else []:
        if not isinstance(prompt, dict):
            continue
        start, end = prompt.get("start"), prompt.get("end")
        if (
            isinstance(start, (int, float))
            and isinstance(end, (int, float))
            and not isinstance(start, bool)
            and not isinstance(end, bool)
            and 0 < start <= end
            and end - start <= 86400
        ):
            total += end - start
            seen = True
    return round(total, 3) if seen else None


def _epoch(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.timestamp() if stamp.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _clocks(catalog: Path) -> dict[str, dict[str, float]]:
    path = clocks_path(catalog)
    try:
        if path.stat().st_size > MAX_CLOCK_BYTES:
            return {}
        with path.open(encoding="utf-8") as stream:
            lines = stream.read(2_000_000).splitlines()
    except OSError:
        return {}
    totals: dict[str, dict[str, float]] = {}
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or not isinstance(record.get("stages"), dict):
            continue
        cid = record.get("conversation_id")
        if not isinstance(cid, str) or not cid:
            continue
        stages = totals.setdefault(cid, {})
        for name, key in (("check_for_hand_in", "checks"), ("second_look", "second_look")):
            value = record["stages"].get(name)
            if not isinstance(value, dict):
                continue
            start, end = _epoch(value.get("start")), _epoch(value.get("end"))
            if start is not None and end is not None and end >= start:
                stages[key] = stages.get(key, 0.0) + end - start
    return totals


def _runs(conversation: dict[str, Any]) -> tuple[float | None, float | None]:
    """Count only completed Build turns, pairing each agent turn with its initiating user turn."""
    building = repairs = 0.0
    seen_build = seen_repair = False
    started: float | None = None
    kind = ""
    turns = conversation.get("turns")
    for turn in turns if isinstance(turns, list) else []:
        if not isinstance(turn, dict):
            continue
        if turn.get("role") == "user":
            text = str(turn.get("text") or "")
            started = _epoch(turn.get("ts"))
            if text.startswith("Autopilot: continuing: repair round"):
                kind = "repair"
            elif text.startswith("Autopilot: continuing:"):
                kind = "other"
            else:
                kind = "build"
        elif turn.get("role") == "agent" and started is not None and "run_id" in turn:
            end = _epoch(turn.get("ts"))
            if end is not None and end >= started:
                if kind == "repair":
                    repairs += end - started
                    seen_repair = True
                elif kind == "build":
                    building += end - started
                    seen_build = True
            started = None
    return (round(building, 3) if seen_build else None, round(repairs, 3) if seen_repair else None)


def _started_today(conversation: dict[str, Any], today: Any, zone: Any) -> bool:
    turns = conversation.get("turns")
    if not isinstance(turns, list):
        return False
    for turn in turns:
        if isinstance(turn, dict) and turn.get("role") == "user":
            start = _epoch(turn.get("ts"))
            try:
                return start is not None and datetime.fromtimestamp(start, zone).date() == today
            except (OverflowError, ValueError):
                return False
    return False


def add_timings(
    rows: list[dict[str, Any]],
    conversations: dict[str, dict[str, Any]],
    catalog: Path,
    now: datetime | None = None,
    running: frozenset[str] | set[str] = frozenset(),
) -> dict[str, Any]:
    """Annotate listed projects and total today's recorded stages without extrapolating gaps."""
    now = now or datetime.now().astimezone()
    today = now.date()
    checks = _clocks(catalog)
    try:
        outbox = outbox_dir()
    except OSError:
        outbox = None
    totals = {key: 0.0 for key in STAGES}
    counts = {key: 0 for key in STAGES}
    for cid, conversation in conversations.items():
        build, repair = _runs(conversation)
        timing: dict[str, float | None] = dict.fromkeys(STAGES)
        timing.update(checks.get(cid, {}))
        timing["building"] = build
        timing["repair_rounds"] = repair
        timing["card_wait"] = _card_wait(cid, conversation, outbox)
        if _started_today(conversation, today, now.tzinfo):
            for key, seconds in timing.items():
                if seconds is not None:
                    totals[key] += seconds
                    counts[key] += 1
        checks[cid] = timing
    for row in rows:
        # Neither a missing prompt interval nor the hand-in time is a measured card wait.
        row["timings_seconds"] = checks.get(row.get("conversation_id", ""), dict.fromkeys(STAGES))
    measured = [key for key in STAGES if counts[key]]
    slowest = max(measured, key=lambda key: totals[key]) if measured else None
    return {
        "slowest_today": f"Slowest today: {LABELS[slowest]} ({round(totals[slowest])}s measured)" if slowest else None,
        "speed_scoreboard": {
            **speed_scoreboard(conversations, checks, outbox, now, running, step_rows=_step_rows()),
            "disk_free_gb": _disk_free_gb(),
        },
    }
