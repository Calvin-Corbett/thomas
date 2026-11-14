"""Read-only view of the landing queue: who waits, who holds, what landed lately. Stdlib only."""

from __future__ import annotations

from typing import Any

from scripts.crew.brief.landing_queue import Lane

BYPASS_NOTE = (
    "Anyone who runs commit.py directly while others are queued is not blocked, but their gate runs "
    "overlap the holder's and every queued landing gets slower. Land through land.py. This queue is advisory "
    "and tamper-evident only; it protects nothing."
)


NOTES = (
    "Rules: a submitted ticket that nobody asks about (land.py --wait) for 10 minutes leaves the line, so call --wait at least "
    "every 8 minutes; a ticket waits at most 45 minutes (exit 3). Tamper-evident, not tamper-proof: forging a `by` field "
    "evicts a ticket and --verify cannot always tell."
)


def build_status(
    lane: Lane, *, last: int = 10, agent: str = "", untagged_since_oldest: int | None = None, verify: bool = False
) -> dict[str, Any]:
    """Pure read: it does not reap, so asking never changes the queue."""
    now, states = lane.clock(), lane.states()
    open_rows = sorted(n for n, s in states.items() if s["open"])
    beats = lane.store.beats(open_rows)
    queue = []
    for pos, n in enumerate(open_rows):
        s, t = states[n], states[n]["ticket"]
        beat = beats.get(n)
        queue.append(
            {
                "ticket": n,
                "agent": t.get("agent"),
                "state": s["state"],
                "position": pos,
                "age_s": round(now - float(t.get("created") or now), 1),
                "attempt": t.get("attempt"),
                "subject": t.get("subject"),
                "beat_age_s": round(now - float(beat["t"]), 1) if beat and "t" in beat else None,
                "mode": t.get("mode"),
                "unbounded": bool(s.get("unbounded")),
                "overran": bool(s.get("overran")),
                "eta_s": round(lane.eta(pos), 1),
            }
        )
    holder = next((q for q in queue if q["state"] in ("holding", "landed")), None)
    if holder:
        s = states[holder["ticket"]]
        holder = {
            **holder,
            "held_s": round(now - s["granted_at"], 1),
            "lease_left_s": round(s["max_hold"] - (now - s["granted_at"]), 1),
        }
    landed, trouble = [], []
    for n in sorted(states):
        s, t = states[n], states[n]["ticket"]
        gr = next((e for e in s["events"] if e["kind"] == "granted"), None)
        if s["sha"]:
            fin = next((e for e in s["events"] if e.get("sha_landed")), None)
            landed.append(
                {
                    "ticket": n,
                    "agent": t.get("agent"),
                    "sha": s["sha"],
                    "state": s["state"],
                    "wait_s": round(float(gr["at"]) - float(t["created"]), 1) if gr else None,
                    "hold_s": round(float(fin["at"]) - float(gr["at"]), 1) if gr and fin else None,
                }
            )
        elif s["state"] in ("refused", "skipped", "abandoned"):
            trouble.append(
                {
                    "ticket": n,
                    "agent": t.get("agent"),
                    "state": s["state"],
                    "reason": s.get("reason")
                    or next((e.get("blocker") for e in s["events"] if e["kind"] == "refused"), ""),
                    "age_s": round(now - float(s.get("finished") or now), 1),
                }
            )
    mine = [
        {"ticket": n, "notice": s["notice"]}
        for n, s in states.items()
        if agent
        and s["ticket"].get("agent") == agent
        and s.get("notice")
        and now - float(s.get("finished") or 0) < 86400
    ]
    verdicts = sum(
        1
        for s in states.values()
        for e in s["events"]
        if str(e.get("by") or "").startswith("lane:") and e.get("kind") in ("abandoned", "skipped", "recovered")
    )
    out: dict[str, Any] = {
        "lane_verdicts_unauthenticated": verdicts,
        "queue_length": len(queue),
        "holder": holder,
        "queue": queue,
        "recent_landings": landed[-last:],
        "recent_trouble": trouble[-last:],
        "notices": mine,
        "root": str(lane.store.root),
        "config": {
            "max_hold_s": lane.cfg.max_hold,
            "slot_waste_cap_per_hour": lane.cfg.attempt_cap,
            "refusal_cap_per_hour": lane.cfg.refusal_cap,
        },
    }
    if untagged_since_oldest is not None:
        out["dev_commits_outside_queue"] = untagged_since_oldest
    if verify:
        out["tamper_findings"] = lane.audit()
    return out


def render(status: dict[str, Any]) -> str:
    lines = [f"Landing queue: {status['queue_length']} open ticket(s)  (root {status['root']})"]
    h = status["holder"]
    lines.append(
        f"- holder: {h['agent']} T{h['ticket']:06d} for {h['held_s']}s, lease left {h['lease_left_s']}s"
        if h
        else "- holder: none"
    )
    for q in status["queue"]:
        if q["state"] in ("holding", "landed"):
            continue
        lines.append(
            f"- #{q['position']} T{q['ticket']:06d} {q['agent']} {q['state']} age {q['age_s']}s attempt {q['attempt']} "
            f"est wait {q['eta_s']}s  {q.get('subject') or ''}"
        )
    if status["queue_length"] and status.get("dev_commits_outside_queue"):
        lines.append(
            f"- {status['dev_commits_outside_queue']} commit(s) reached dev while the queue was open without a landing ticket. "
            + BYPASS_NOTE
        )
    elif status["queue_length"] > 1:
        lines.append("- note: " + BYPASS_NOTE)
    flags = [
        f
        for f, on in (("hold overran", h and h.get("overran")), ("NOT in a job object", h and h.get("unbounded")))
        if on
    ]
    if flags:
        lines.append(f"- holder: {', '.join(flags)}")
    lines.append("Last landings:")
    lines += [
        f"  T{r['ticket']:06d} {r['agent']} {str(r['sha'])[:10]} waited {r['wait_s']}s held {r['hold_s']}s"
        for r in status["recent_landings"]
    ] or ["  none"]
    if status["recent_trouble"]:
        lines.append("Last refused or dropped:")
        lines += [f"  T{r['ticket']:06d} {r['agent']} {r['state']}: {r['reason']}" for r in status["recent_trouble"]]
    lines += [f"NOTICE for you (T{m['ticket']:06d}): {m['notice']}" for m in status["notices"]]
    if "tamper_findings" in status:
        lines += [
            "Tamper check: "
            + ("clean" if not status["tamper_findings"] else f"{len(status['tamper_findings'])} finding(s)")
        ]
        lines += [f"  ! {f}" for f in status["tamper_findings"]]
    lines.append(NOTES)
    lines.append(
        f"Unauthenticated: {status.get('lane_verdicts_unauthenticated', 0)} lane verdict(s) on record are attributed only "
        "by their own `by` text; any agent can write one."
    )
    return "\n".join(lines)
