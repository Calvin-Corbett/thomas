"""Where the wall-clock time of every Thomas self-change project goes, read from disk (spec 2026-10-12 Step 0).

    python scripts/praxis_timeline.py [--since 2026-10-07T00:00] [--until 2026-10-12T00:00]
        [--recent-since 2026-10-09T00:00] [--baseline-out FILE] [--no-git] [--green-root DIR ...]

It reads, and never writes, the catalog checkout's conversations, run transcripts and hand_in_clocks.jsonl, every
green's conversations (each --green-root, and wherever the catalog's project registry binds one), the cage folder
(hand-ins, verdicts, second looks, the promoter log) and read-only git. It writes timeline.json and timeline.md into
--out-dir (``runtime/praxis_timeline`` by default, which git ignores) and, when asked, a baseline of aggregates only (no
titles, ids, request words or paths) to --baseline-out. timeline.md names each project for the operator; the baseline,
which goes into the repo, names none.

A project whose conversation this account cannot read (the caged account's green, say) is listed in meta.unreadable,
counted in aggregate.projects_unreadable and named in the summary line. --baseline-out then writes nothing and exits 3,
unless every such conversation is found in another --green-root (a folder of exported copies) or --allow-unreadable is
given: a baseline that missed a project would be published as if it had not.

The window is [--since, --until): a project counts when it launched inside it. --until is that launch filter, the
check clocks that count, and the end of the window shares and of each day (per_day), and nothing else. Each project's
own rows (runs, state, phases, totals) are followed to the extraction time, the time the tool runs, not to --until: a
project launched before --until that landed after it is followed to its landing, and a run that ended after --until
is not still running. Every second from a project's launch to its landing, to its last event once it has ended (a
conversation quiet for an hour with nothing waiting, as the server counts it), or to the extraction time while it is
open, is put in exactly one phase. The check clocks give each stage's median, p90 and maximum, and the p90 of checks
that started together.

The window shares and per_day count every project launched in the window, ratchet projects included; the aggregate
counts Thomas projects only and leaves the ratchet out. Projects launched before --since that were still in flight are
not read, so they are not in the window and the shares read low at its start.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.praxis import timeline_report  # noqa: E402
from scripts.praxis.timeline_cage import load_hand_ins, load_outbox, load_second_looks, promoter_restarts  # noqa: E402
from scripts.praxis.timeline_load import clocks_summary, pass_lines, per_day, window_shares  # noqa: E402
from scripts.praxis.timeline_phases import attribute, infer_cards  # noqa: E402
from scripts.praxis.timeline_runs import build_project  # noqa: E402
from scripts.praxis.timeline_sources import (  # noqa: E402
    CAGE_ROOT_ENV,
    DEFAULT_CAGE_ROOT,
    Paths,
    cid_epoch,
    git_commit,
    iso_to_epoch,
    load_clocks,
    load_conversations,
    transcript_index,
)
from scripts.praxis.timeline_totals import aggregate, totals  # noqa: E402

GREEN_ROOT_ENV = "THOMAS_GREEN_ROOT"
DEFAULT_DAYS = 5


def _local_zone() -> tzinfo:
    zone = datetime.now().astimezone().tzinfo
    assert zone is not None
    return zone


def _epoch(text: str, zone: tzinfo) -> float:
    moment = datetime.fromisoformat(text)
    return (moment if moment.tzinfo else moment.replace(tzinfo=zone)).timestamp()


def _greens(named: list[str]) -> list[Path]:
    """The roots named, else THOMAS_GREEN_ROOT, else the green root Thomas uses (read only when none is named)."""
    roots = [Path(name) for name in named if name]
    if roots:
        return roots
    from_env = str(os.environ.get(GREEN_ROOT_ENV) or "").strip()
    if from_env:
        return [Path(from_env).expanduser()]
    from thomas.server.green_checkout import green_root  # only when no root is named

    return [green_root()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Where the time of every Thomas self-change project goes.")
    parser.add_argument("--since", default="", help=f"local ISO time; default {DEFAULT_DAYS} days before --until")
    parser.add_argument("--until", default="", help="local ISO time that ends the window; default now")
    parser.add_argument("--recent-since", default="", help="local ISO time; also aggregate projects launched since it")
    parser.add_argument("--catalog-root", default=str(_REPO_ROOT))
    parser.add_argument("--cage-root", default=str(os.environ.get(CAGE_ROOT_ENV) or DEFAULT_CAGE_ROOT))
    parser.add_argument(
        "--green-root",
        action="append",
        default=[],
        metavar="DIR",
        help="a folder holding work/<exec>/... (a green root, or a folder of exported copies); may be given more than "
        "once, and a conversation found in any counts as read; default: THOMAS_GREEN_ROOT, else Thomas's green root",
    )
    parser.add_argument("--dev-branch", default="dev")
    parser.add_argument("--no-git", action="store_true", help="do not read commits")
    parser.add_argument("--out-dir", default="", help="default: <catalog>/runtime/praxis_timeline")
    parser.add_argument("--baseline-out", default="", help="also write a baseline of aggregates only here")
    parser.add_argument(
        "--allow-unreadable",
        action="store_true",
        help="write --baseline-out although some project's conversation could not be read (exit 3 otherwise)",
    )
    return parser


def _launched_before(cid: str, conversation: dict[str, Any], end: float) -> bool:
    """False for a project launched at or after *end*: the reader has a lower bound only, so the window ends here."""
    launch = cid_epoch(cid)
    if launch is None:
        launch = iso_to_epoch(conversation.get("created_at"))
    return launch is None or launch < end


def collect(
    paths: Paths,
    *,
    since: float,
    now: float,
    tz: tzinfo,
    until: float | None = None,
    recent_since: float | None = None,
    commit_lookup: Callable[[str], dict | None] | None = None,
) -> dict[str, Any]:
    """Every project launched in [since, until): its rows, the aggregate, the clocks, the window, each day, pass lines.

    *now* is the extraction time: every project's rows (runs, state, phases, totals) are followed to it. *until*, the
    window's end, defaults to *now* and is only the launch filter, the clocks summary, the window shares and per_day.
    """
    lookup = commit_lookup or (lambda _sha: None)
    end = now if until is None else until
    unreadable: list[dict[str, str]] = []
    found = {cid: c for cid, c in load_conversations(paths, since, unreadable).items() if _launched_before(cid, c, end)}
    unreadable = [entry for entry in unreadable if _launched_before(entry["conversation_id"], {}, end)]
    hand_ins, outbox, looks = load_hand_ins(paths.cage), load_outbox(paths.cage), load_second_looks(paths.cage)
    index = transcript_index(paths.agent_dir, since)
    ordered = sorted(found.items(), key=lambda item: cid_epoch(item[0]) or 0.0)
    rows = [build_project(c, hand_ins, outbox, looks, paths.agent_dir, now, index, lookup) for _cid, c in ordered]
    exact = infer_cards(rows, outbox, now)
    for row in rows:
        attribute(row, now)
        row["totals"] = totals(row)
    cohorts: dict[str, Any] = {}
    if recent_since is not None:
        cohorts["launched_since_recent"] = aggregate([r for r in rows if (r["_launch_epoch"] or 0) >= recent_since])
        cohorts["launched_before_recent"] = aggregate([r for r in rows if (r["_launch_epoch"] or 0) < recent_since])
    clocks = clocks_summary(load_clocks(paths.catalog), since=since, until=end)
    window = window_shares(rows, start=since, end=end)
    # With no project launched in the window, nothing was building and no share was measured: the line says so.
    seen = any(row["_launch_epoch"] is not None for row in rows)
    lines = pass_lines(clocks, window if seen else {**window, "building_busy_share": None})
    meta = {
        "extracted_at": datetime.fromtimestamp(now, tz).isoformat(timespec="seconds"),
        "since": datetime.fromtimestamp(since, tz).isoformat(timespec="minutes"),
        "until": datetime.fromtimestamp(end, tz).isoformat(timespec="minutes"),
        "recent_since": datetime.fromtimestamp(recent_since, tz).isoformat(timespec="minutes") if recent_since else "",
        "promoter_precheck_exact_s": [round(seconds, 1) for seconds in exact],
        "promoter_restarts": promoter_restarts(paths.cage, since),
        "unreadable": unreadable,
        "notes": timeline_report.NOTES,
    }
    projects = [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]
    for clean, row in zip(projects, rows):
        clean["launch_epoch"] = row["_launch_epoch"]
    return {
        "meta": meta,
        "aggregate": {**aggregate(rows), "projects_unreadable": len(_unreadable_names(unreadable))},
        "cohorts": cohorts,
        "clocks": clocks,
        "window": window,
        "per_day": per_day(rows, tz=tz, start=since, end=end),
        "pass_lines": lines,
        "projects": projects,
    }


def _unreadable_names(entries: list[dict[str, str]]) -> list[str]:
    """What to call each project that could not be read: its id, or the folder when the id is not known."""
    return sorted({entry["conversation_id"] or entry["where"] for entry in entries})


def _window(args: argparse.Namespace, zone: tzinfo, now: float) -> tuple[float, float, float | None]:
    """(since, until, recent_since) from the arguments; a time that is not a time, or an empty window, is a ValueError."""
    try:
        until = _epoch(args.until, zone) if args.until else now
        since = _epoch(args.since, zone) if args.since else until - DEFAULT_DAYS * 86400.0
        recent = _epoch(args.recent_since, zone) if args.recent_since else None
    except (ValueError, OverflowError, OSError) as error:
        raise ValueError(f"not a local ISO time ({error})") from None
    if since >= until:
        raise ValueError("--since must be before --until")
    return since, until, recent


def main(argv: list[str] | None = None, *, now: float | None = None, tz: tzinfo | None = None) -> int:
    args = build_parser().parse_args(argv)
    zone = tz or _local_zone()
    extracted = now if now is not None else time.time()
    try:
        since, until, recent = _window(args, zone, extracted)
    except ValueError as error:
        print(f"praxis_timeline: {error}", file=sys.stderr)
        return 2
    catalog = Path(args.catalog_root)
    first, *more = _greens(args.green_root)
    paths = Paths(catalog, Path(args.cage_root), first, args.dev_branch, tuple(more))
    lookup = None if args.no_git else (lambda sha: git_commit(catalog, sha, args.dev_branch))
    payload = collect(
        paths, since=since, until=until, now=extracted, tz=zone, recent_since=recent, commit_lookup=lookup
    )
    out = Path(args.out_dir) if args.out_dir else catalog / "runtime" / "praxis_timeline"
    out.mkdir(parents=True, exist_ok=True)
    (out / "timeline.json").write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8", newline="\n")
    (out / "timeline.md").write_text(timeline_report.markdown(payload), encoding="utf-8", newline="\n")
    unread = _unreadable_names(payload["meta"]["unreadable"])
    summary = f"{len(payload['projects'])} projects; wrote {out / 'timeline.json'} and timeline.md"
    print(summary + (f"; could not read {len(unread)}: {', '.join(unread)}" if unread else ""))
    if args.baseline_out and unread and not args.allow_unreadable:
        print(
            f"praxis_timeline: no baseline written, {len(unread)} project(s) could not be read: add a --green-root "
            "that holds a copy of each, or pass --allow-unreadable",
            file=sys.stderr,
        )
        return 3
    if args.baseline_out:
        target = Path(args.baseline_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(timeline_report.baseline(payload), indent=1, sort_keys=True, default=str)
        target.write_text(text + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
