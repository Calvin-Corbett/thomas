"""The timeline's words: the notes on where each time comes from, ``timeline.md``, and a baseline that names no one.

``timeline.md`` is the operator's own report and does name each project (its title and green name), so it stays in the
output folder that git ignores. :func:`baseline` is what goes into the repo, which is published: aggregates only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

BASELINE_SCHEMA = "praxis-timeline-baseline/1"
BASELINE_KEYS = ("aggregate", "cohorts", "clocks", "window", "per_day", "pass_lines")
NOTES = [
    "Run start is the user turn's ts in the conversation record; run end is the agent turn's ts. A run with no agent "
    "turn ends at its transcript's last write (found by creation time), or is still running while that transcript "
    "was written in the last 15 minutes.",
    "Run kind is read from how the message that started it opens (the Autopilot prefixes). Text Autopilot did not "
    "write is a manual message.",
    "Launch is the conversation's created_at; the start request began a few seconds earlier.",
    "Second look is the reviewer's Claude session in the cage folder: its first and last message times.",
    "Check before the card, per settle, runs from the settling run's end to the second look's first message, so it "
    "includes any wait for a place. The clocks give the check's own stages exactly.",
    "Hand-in is submission.json's submitted_at; verdict is the outbox verdict's ts; your answer is the last write of "
    "the outbox pending.json.",
    "A card goes up when its change arrived or when the promoter's previous outcome finished, whichever is later; the "
    "changes on one shared card are one outcome. The card time is exact where pending.json's creation time survived, "
    "otherwise the pick time plus the median of the exact cases.",
    "Waiting on you: queue_behind_other_card (a ready card waits for another card's answer) and owner_card (a card is "
    "up). Waiting on the operator: waiting_for_manual_message. Everything else is machine time.",
    "Every project since --since is read from the catalog and every green, not from the project list (which shows "
    "the newest 20 handed in).",
    "--until is the launch filter, the check clocks that count, and the end of the window shares and of each day "
    "(per_day), and nothing else. Each project's own rows (runs, state, phases, totals) are followed to the "
    "extraction time, not to --until: a project launched before --until that landed after it is followed to its "
    "landing, and a run that ended after --until is not still running.",
    "The window shares and per_day count every project launched in the window, ratchet projects included; the "
    "aggregate counts Thomas projects only and leaves the ratchet out. Projects launched before --since that were "
    "still in flight are not read, so they are not in the window: the shares read low at its start.",
    "A project is open only while something can still move it: its conversation was written in the last hour (the "
    "server's own hour of quiet), or a hand-in has no final verdict, a run is going, or it is paused for a usage "
    "limit. Any other project with no landing has ended and is followed to its last event, not to the extraction time.",
    "A project whose conversation this account could not read (a permission error, as with the caged account's green) "
    "is listed in meta.unreadable and counted in aggregate.projects_unreadable. The baseline is not written while any "
    "is listed, unless every one is found in another --green-root or --allow-unreadable is given.",
]


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _cell(text: object, limit: int) -> str:
    """Text for one table cell: on one line, without the bar that would start another column."""
    return " ".join(str(text).split()).replace("|", "/")[:limit]


def _aggregate_lines(agg: dict[str, Any]) -> list[str]:
    unread = f"; {agg['projects_unreadable']} could not be read" if agg.get("projects_unreadable") else ""
    if not agg.get("projects"):
        return [f"- no projects{unread}"]
    hand, check, look = agg["hand_ins"], agg["precard_check"], agg["second_look"]
    lines = [
        f"- Projects: {agg['projects']} ({agg['projects_landed']} landed{unread})",
        f"- Median launch to first run {_fmt(agg['median_launch_to_first_run_min'])}, to first hand-in "
        f"{_fmt(agg['median_launch_to_first_hand_in_min'])}, to landed {_fmt(agg['median_launch_to_landed_min'])}",
        f"- Totals: machine {_fmt(agg['total_machine_min'])}, waiting on you {_fmt(agg['total_owner_wait_min'])}, "
        f"waiting on the operator {_fmt(agg['total_operator_wait_min'])}",
        f"- Dominant phase: {agg['dominant_phase']}; dominant machine phase: {agg['dominant_machine_phase']}",
        f"- Check before the card: {check['n']} settles, median {_fmt(check['median_min'])}, max "
        f"{_fmt(check['max_min'])}; second look: {look['n']}, median {_fmt(look['median_min'])}",
        f"- Hand-ins: {hand['count']}; median queue behind another card "
        f"{_fmt(hand['median_queue_behind_other_card_min'])}, median card to your answer "
        f"{_fmt(hand['median_owner_card_min'])}",
        "",
        "| phase | who | total min | share | projects |",
        "|---|---|---:|---:|---:|",
    ]
    for phase, data in agg["per_phase"].items():
        share = data["share_of_all_tracked"]
        percent = _fmt(None if share is None else round(100 * share, 1))
        total, who, held = _fmt(data["total_min"]), data["who"], data["projects_with_phase"]
        lines.append(f"| {phase} | {who} | {total} | {percent}% | {held} |")
    return lines


def _clocks_lines(clocks: dict[str, Any]) -> list[str]:
    check = clocks["check"]
    lines = [
        f"- Records: {clocks['records']}; checks {check['n']}, p90 {_fmt(check['p90_s'])} s; under load "
        f"{check['under_load_n']}, p90 {_fmt(check['p90_under_load_s'])} s; most waiting or running at once "
        f"{check['max_checks_at_once']}, most running at once {check['max_running_at_once']}",
        f"- Lowest free disk recorded: {_fmt(clocks['free_disk_min_bytes'])} bytes; causes {clocks['check_causes']}",
        "",
        "| stage | n | median s | p90 s | max s |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, data in clocks["stages"].items():
        median, p90, longest = _fmt(data["median_s"]), _fmt(data["p90_s"]), _fmt(data["max_s"])
        lines.append(f"| {_cell(name, 60)} | {data['n']} | {median} | {p90} | {longest} |")
    return lines


def _project_line(row: dict[str, Any]) -> str:
    totals, launched = row["totals"], row.get("launch_epoch")
    when = datetime.fromtimestamp(launched, timezone.utc).strftime("%m-%d %H:%M") if launched else "-"
    kinds = ", ".join(f"{kind} {count}" for kind, count in totals["run_counts"].items())
    return (
        f"| {_cell(row['title'], 40)} | {_cell(row['execution_id'][-12:], 12)} | {row['state']} | {when} | "
        f"{_fmt(totals['launch_to_first_hand_in_min'])} | {_fmt(totals['launch_to_landed_min'])} | "
        f"{_fmt(totals['machine_min'])} | {_fmt(totals['owner_wait_min'])} | {kinds} | {totals['repair_rounds']} |"
    )


def markdown(payload: dict[str, Any]) -> str:
    """The operator's report: pass lines, the aggregate, the clocks, each day, and one row per project."""
    meta = payload["meta"]
    out = [
        "# Praxis timeline",
        "",
        f"Projects started from {meta['since']} to {meta['until']}. Minutes unless marked.",
        "",
    ]
    out += ["## Pass lines", "", "| line | value | target | met |", "|---|---:|---:|---|"]
    out += [
        f"| {n} | {_fmt(v['value'])} | {_fmt(v['target'])} | {_fmt(v['met'])} |"
        for n, v in payload["pass_lines"].items()
    ]
    out += ["", "## Aggregate (Thomas projects)", "", *_aggregate_lines(payload["aggregate"])]
    for name, cohort in payload["cohorts"].items():
        out += ["", f"## Cohort: {name}", "", *_aggregate_lines(cohort)]
    out += ["", "## Check clocks", "", *_clocks_lines(payload["clocks"])]
    out += ["", "## Per day", "", "| day | landed | in flight avg | max | building | runs | failed run min |",
            "|---|---:|---:|---:|---:|---:|---:|"]  # fmt: skip
    for day in payload["per_day"]:
        out.append(
            f"| {day['day']} | {day['landed']} | {_fmt(day['in_flight_avg'])} | {day['in_flight_max']} | "
            f"{_fmt(day['building_busy_share'])} | {_fmt(day['busy_runs_share'])} | {_fmt(day['failed_run_min'])} |"
        )
    out += ["", "## One row per project", "", "| project | green | state | launch | to hand-in | to landed | machine | "
            "waiting on you | runs | repairs |", "|---|---|---|---|---:|---:|---:|---:|---|---:|"]  # fmt: skip
    out += [_project_line(row) for row in payload["projects"]]
    out += ["", "## Notes on sources", "", *[f"- {note}" for note in meta["notes"]]]
    return "\n".join(out) + "\n"


def baseline(payload: dict[str, Any]) -> dict[str, Any]:
    """Aggregates only, for the repo (which is published): no title, id, request words, reason or path."""
    meta = payload["meta"]
    kept = {key: payload[key] for key in BASELINE_KEYS}
    return {"schema": BASELINE_SCHEMA, "extracted_at": meta["extracted_at"], "since": meta["since"],
            "until": meta["until"], **kept}  # fmt: skip


__all__ = ["BASELINE_KEYS", "BASELINE_SCHEMA", "NOTES", "baseline", "markdown"]
