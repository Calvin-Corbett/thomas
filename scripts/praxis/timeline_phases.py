"""When each card went up, and which phase every second of a project belongs to (``scripts/praxis_timeline.py``).

The promoter handles one promoter outcome at a time, so a card goes up when its change arrived or when the previous
outcome finished, whichever is later, plus the promoter's own checks. The changes on one shared card (one pairing
code, since 2026-10-09) are one outcome: one pick, one card and one finish. Every second from launch to landing, or to
now, is then put in exactly one phase, closed by the next thing that happened.
"""

from __future__ import annotations

import statistics
from typing import Any

from scripts.praxis.timeline_runs import AUTO_REPAIR_CAUSES
from scripts.praxis.timeline_sources import iso_to_epoch

OWNER_PHASES = frozenset({"queue_behind_other_card", "owner_card"})
OPERATOR_PHASES = frozenset({"waiting_for_manual_message"})
PHASE_ORDER = [
    "launch_setup",
    "run:first_build",
    "run:continuation",
    "run:done_check",
    "run:repair_round",
    "run:resume",
    "run:restart",
    "run:steer",
    "run:manual_message",
    "autopilot_gap",
    "waiting_for_manual_message",
    "precard_check",
    "precard_check+second_look",
    "second_look",
    "handover",
    "after_review_gap",
    "repair_start",
    "queue_behind_other_card",
    "promoter_precheck",
    "owner_card",
    "promoter_land",
    "after_verdict",
    "open_now",
    "other",
]
# The median of the exact cases (pending.json creation times that survived), used when a card time is not on disk.
PROMOTER_PRECHECK_FALLBACK_S = 14.0
_ORDER = {"launch": 0, "verdict": 1, "repair": 2, "run_end": 3, "sl_end": 4, "submitted": 5, "pick": 6, "card": 7,
          "answered": 8, "sl_start": 9, "run_start": 10}  # fmt: skip


def _key(hand_in: dict[str, Any]) -> str:
    return f"card:{hand_in['card_code']}" if hand_in.get("card_code") else f"sid:{hand_in['sid']}"


def _dict(value: object) -> dict[str, Any]:
    """These files are written by the promoter and by Build teams: a record of the wrong type reads as empty."""
    return value if isinstance(value, dict) else {}


def _num(value: object) -> float | None:
    """A time as a number; None for one that is missing or is not a number (a bool is not a time)."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def looks(row: dict[str, Any]) -> list[tuple[float, float]]:
    """(start, end) of each of a project's second looks whose two times can be read; any other is left out."""
    spans = ((_num(look.get("start")), _num(look.get("end"))) for look in row["second_looks"])
    return [(start, end) for start, end in spans if start is not None and end is not None]


def landed_times(row: dict[str, Any]) -> list[float]:
    """When each landed hand-in landed; one whose verdict time could not be read is left out."""
    return [
        float(h["verdict_ts"]) for h in row["hand_ins"] if h.get("verdict_status") == "landed" and h.get("verdict_ts")
    ]


def _outcomes(outbox: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Promoter outcomes by key: the members of one shared card are one outcome; any other verdict is its own."""
    found: dict[str, dict[str, Any]] = {}
    for sid, entry in outbox.items():
        verdict = _dict(_dict(entry).get("verdict"))
        ts = iso_to_epoch(verdict.get("ts"))
        if not ts:
            continue
        code = str(_dict(verdict.get("card")).get("pairing_code") or "")
        group = found.setdefault(f"card:{code}" if code else f"sid:{sid}", {"first": ts, "finish": ts})
        group["first"], group["finish"] = min(group["first"], ts), max(group["finish"], ts)
    return found


def _withdrawn(project: dict[str, Any], hand_in: dict[str, Any]) -> None:
    """Taken out of the inbox before the promoter picked it: it queued until the send-back that withdrew it."""
    sent = next((rep["at"] for rep in project["repairs"] if rep.get("sid") == hand_in["sid"] and rep.get("at")), None)
    hand_in.update(withdrawn_at=sent if sent is not None else hand_in.get("dir_mtime"), pick=None)
    hand_in.update(card_shown=None, answered=None)


def _pick(hand_in: dict[str, Any], members: list[dict[str, Any]], groups: dict, now: float) -> None:
    key = _key(hand_in)
    group = groups.get(key)
    end = group["first"] if group else (now if hand_in.get("where") == "inbox" else None)
    arrived = max(float(member["submitted_at"]) for member in members)
    before = [g["finish"] for k, g in groups.items() if k != key and (end is None or g["finish"] < end - 0.5)]
    previous = max(before, default=None)
    if previous is not None and previous > arrived:
        hand_in["pick"] = previous
        hand_in["pick_basis"] = "queued behind another card's answer (the previous promoter outcome's ts)"
    else:
        hand_in["pick"] = arrived
        own = float(hand_in["submitted_at"])
        hand_in["pick_basis"] = "arrival (promoter idle)" if arrived == own else "the last change on its card arrived"


def _card_and_answer(hand_in: dict[str, Any], exact: list[float]) -> None:
    created, modified = _num(hand_in.get("pending_created")), _num(hand_in.get("pending_modified"))
    pick = hand_in["pick"]
    status = hand_in.get("verdict_status")
    hand_in["card_shown"], hand_in["card_basis"] = None, ""
    rewritten_later = modified is None or created is None or created < modified - 0.5 or status is None
    if created is not None and pick - 1 <= created <= pick + 60 and rewritten_later:
        hand_in["card_shown"] = created
        hand_in["card_basis"] = "exact: pending.json creation time"
        exact.append(created - pick)
    answered = status in ("landed", "declined") and modified is not None
    hand_in["answered"] = modified if answered else None


def infer_cards(projects: list[dict[str, Any]], outbox: dict[str, dict[str, Any]], now: float) -> list[float]:
    """Set each hand-in's pick, card and answer times; return the exact pre-card seconds found."""
    groups = _outcomes(outbox)
    every = [hand_in for project in projects for hand_in in project["hand_ins"] if hand_in.get("submitted_at")]
    exact: list[float] = []
    picked: list[dict[str, Any]] = []
    for project in projects:
        for hand_in in project["hand_ins"]:
            if not hand_in.get("submitted_at"):  # no readable submit time: no pick, no card, no answer
                continue
            if hand_in.get("where") == "withdrawn" and not hand_in.get("verdict_ts"):
                _withdrawn(project, hand_in)
                continue
            members = [m for m in every if _key(m) == _key(hand_in)] if _key(hand_in) in groups else [hand_in]
            _pick(hand_in, members, groups, now)
            _card_and_answer(hand_in, exact)
            picked.append(hand_in)
    fallback = statistics.median(exact) if exact else PROMOTER_PRECHECK_FALLBACK_S
    for hand_in in picked:
        if hand_in["card_shown"] is None and hand_in.get("verdict_status") in ("landed", "declined", None):
            hand_in["card_shown"] = hand_in["pick"] + fallback
            hand_in["card_basis"] = f"inferred: pick time + {fallback:.0f} s"
        if hand_in["answered"] is not None and hand_in["card_shown"] is not None:
            hand_in["card_shown"] = min(hand_in["card_shown"], hand_in["answered"])
    for key in {_key(hand_in) for hand_in in picked if hand_in.get("card_code")}:
        members = [hand_in for hand_in in picked if _key(hand_in) == key]
        shown = [m["card_shown"] for m in members if m["card_shown"] is not None]
        answered = [m["answered"] for m in members if m["answered"] is not None]
        for member in members:
            member["card_shown"] = min(shown) if shown else None
            member["answered"] = max(answered) if answered else None
    return exact


def _markers(row: dict[str, Any]) -> list[tuple[float, str, dict[str, Any]]]:
    markers: list[tuple[float, str, dict[str, Any]]] = [(row["_launch_epoch"], "launch", {})]
    for run in row["runs"]:
        if run["start"] is not None:
            markers.append((run["start"], "run_start", run))
        if run["end"] is not None:
            markers.append((run["end"], "run_end", run))
    for start, end in looks(row):
        markers += [(start, "sl_start", {}), (end, "sl_end", {})]
    markers += [(rep["at"], "repair", rep) for rep in row["repairs"] if rep.get("at") is not None]
    for hand_in in row["hand_ins"]:
        submitted = hand_in.get("submitted_at") or None  # a time of 0 is a time that was not read
        if submitted is not None:
            markers.append((submitted, "submitted", hand_in))
        if hand_in.get("pick") is not None and submitted is not None and hand_in["pick"] > submitted + 0.5:
            markers.append((hand_in["pick"], "pick", hand_in))
        for name, kind in (("card_shown", "card"), ("answered", "answered")):
            if hand_in.get(name) is not None:
                markers.append((hand_in[name], kind, hand_in))
        if hand_in.get("verdict_ts"):
            markers.append((float(hand_in["verdict_ts"]), "verdict", hand_in))
    return sorted(markers, key=lambda marker: (marker[0], _ORDER.get(marker[1], 50)))


def _phase(k0: str, k1: str, p1: dict[str, Any], in_run: dict[str, Any] | None, open_card: bool) -> str:
    """The phase of the interval that the marker *k1* closes, after the marker *k0*."""
    if in_run is not None and k1 != "run_start":
        return "run:" + in_run["kind"]
    if k1 == "run_start":
        named = {"launch": "launch_setup", "repair": "repair_start", "verdict": "after_verdict"}
        if k0 in named:
            return named[k0]
        return "waiting_for_manual_message" if p1.get("source") == "manual" else "autopilot_gap"
    if k1 == "sl_start":
        return "precard_check"
    if k1 == "sl_end":
        return "second_look"
    if k1 == "repair" and k0 in ("submitted", "pick", "card"):
        return "queue_behind_other_card"  # withdrawn by a send-back while it waited for the promoter
    if k1 == "repair" and p1.get("cause") not in AUTO_REPAIR_CAUSES:
        return "waiting_for_manual_message"  # nothing moves until a person sends it back
    if k1 in ("submitted", "repair") and k0 == "sl_end":
        return "handover"
    if k1 == "submitted" and k0 == "run_end":
        return "precard_check+second_look"
    if k1 == "repair" and k0 == "run_end":
        return "precard_check" if p1.get("cause") == "precard_check_failed" else "precard_check+second_look"
    simple = {"pick": "queue_behind_other_card", "card": "promoter_precheck", "answered": "owner_card"}
    if k1 in simple:
        return simple[k1]
    if k1 == "verdict" and k0 == "answered":
        return "promoter_land"
    if k1 == "verdict" and k0 in ("card", "submitted", "pick"):
        return "owner_card" if p1.get("verdict_status") in ("landed", "declined") else "promoter_precheck"
    if k1 == "repair" and k0 == "verdict":
        return "after_verdict"
    if k1 == "now":
        return "owner_card" if open_card and k0 in ("card", "answered") else "open_now"
    return "after_review_gap" if k0 == "sl_end" else "other"


def attribute(row: dict[str, Any], now: float) -> None:
    """Split launch to the end (landing, or now while open) into phases; each marker closes the interval before it."""
    if row.get("_launch_epoch") is None:
        row["phases_s"], row["_end_epoch"] = {}, None
        return
    markers = _markers(row)
    landed = landed_times(row)
    open_project = row["state"] == "open"
    end = max(landed) if landed else (now if open_project else markers[-1][0])
    markers = [marker for marker in markers if marker[0] <= end + 0.5]
    if open_project:
        markers.append((now, "now", {}))
    open_card = any(h.get("card_shown") and not h.get("verdict_ts") for h in row["hand_ins"])
    spent: dict[str, float] = {}
    in_run: dict[str, Any] | None = None
    for (t0, k0, _p0), (t1, k1, p1) in zip(markers, markers[1:]):
        if t1 - t0 > 0:
            phase = _phase(k0, k1, p1, in_run, open_card)
            spent[phase] = spent.get(phase, 0.0) + (t1 - t0)
        if k1 == "run_start":
            in_run = p1
        elif k1 == "run_end":
            in_run = None
    row["phases_s"] = {phase: round(seconds, 1) for phase, seconds in spent.items()}
    row["_end_epoch"] = end


__all__ = [
    "OPERATOR_PHASES",
    "OWNER_PHASES",
    "PHASE_ORDER",
    "PROMOTER_PRECHECK_FALLBACK_S",
    "attribute",
    "infer_cards",
    "landed_times",
    "looks",
]
