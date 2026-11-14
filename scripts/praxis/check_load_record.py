"""What a load run records and says (``scripts/praxis/check_load.py`` is the run itself).

One entry for each check, the free disk and the other load read inside that check's own window, the lines the run
prints, and the figures that go into the repo. The entries are the run's own summary,
``runtime/praxis_check_load/<stamp>.json``; only :func:`disk_record` goes into the repo, and it holds aggregates and
counts only: no module, copy name or path. A check is ``quiet`` only when its readings cover at least
:data:`MEASURED_SHARE_MIN` of its window and none of them had other load over
:data:`~scripts.praxis.check_load_machine.OTHER_LOAD_LIMIT_PCT` or a headless browser process of other work; one read
for less is not measured, never quiet. A run is quiet only when every check was, and the printed lines say first, in
capitals, when it was not, naming each check that overlapped other load and, apart from those, each not measured.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.praxis.check_load_machine import OTHER_LOAD_LIMIT_PCT, Reading

MEASURED_SHARE_MIN = 0.8  # a check whose readings cover less of the time it ran than this is not measured


def local_time(epoch: float) -> str:
    """*epoch* as a local ISO time with its offset, as ``scripts/praxis_timeline.py --since`` and ``--until`` take."""
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def ran_window(record: dict[str, Any], began: float, ended: float) -> tuple[float, float]:
    """The check's ``in_slot`` stage window exactly as the clocks record it, else the whole call."""
    stage = (record.get("stages") or {}).get("in_slot") or {}
    try:
        return datetime.fromisoformat(stage["start"]).timestamp(), datetime.fromisoformat(stage["end"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return began, ended


def disk_window(entry: dict[str, Any], samples: list[tuple[float, int]], start_free: int | None) -> None:
    """The lowest free disk read while *entry*'s check ran, and how far under the last reading before it that was."""
    before = [free for at, free in samples if at <= entry["ran_from"]]
    baseline = before[-1] if before else start_free
    inside = [free for at, free in samples if entry["ran_from"] <= at <= entry["ran_to"]]
    lowest = min(inside) if inside else None
    entry["free_disk_min_bytes"] = lowest
    entry["disk_peak_bytes"] = None if lowest is None or baseline is None else max(0, baseline - lowest)


def check_entry(execution_id: str, module: str, record: dict[str, Any], checked: Any, began: float) -> dict[str, Any]:
    """One check's line of the summary: its answer, how long it took, and the files and tests the clocks say it ran."""
    ended = time.time()
    ran_from, ran_to = ran_window(record, began, ended)
    return {
        "execution_id": execution_id,
        "module": module,
        "selected_files": record.get("selected_files"),
        "change_tests_seen": record.get("change_tests_seen"),
        "dev_tests_seen": record.get("dev_tests_seen"),
        "state": checked.state,
        "cause": checked.cause,
        "seconds": round(ended - began, 1),
        "ran_from": ran_from,
        "ran_to": ran_to,
    }


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def disk_record(result: dict[str, Any]) -> dict[str, Any]:
    """A load run's disk figures for the repo: the most disk one check used, the run's range, and each check's size.

    ``selected_files`` is one count for each check, in the order its copy was made, so a later run is compared with
    this one at the same size. It is counts only; it names no module.
    """
    return {
        "schema": "praxis-check-disk/1",
        "measured_at": datetime.fromtimestamp(result["started_at"]).astimezone().isoformat(timespec="seconds"),
        "checks": len(result["checks"]),
        "selected_files": [_count(entry.get("selected_files")) for entry in result["checks"]],
        "free_disk_start_bytes": result["free_disk_start_bytes"],
        "free_disk_min_bytes": result["free_disk_min_bytes"],
        "check_disk_peak_bytes": result["check_disk_peak_bytes"],
    }


def _list(entries: list[dict[str, Any]], key: str) -> str:
    return ", ".join("-" if entry.get(key) is None else str(entry[key]) for entry in entries)


def summary_lines(result: dict[str, Any]) -> list[str]:
    """What the run prints once every check has answered."""
    checks = result["checks"]
    slowest = max((entry["seconds"] for entry in checks), default=None)
    states = ", ".join(f"{entry['state']} {entry['cause'] or ''}".strip() for entry in checks)
    return [
        *load_lines(result),
        f"{len(checks)} checks; slowest {slowest} s; lowest free disk {result['free_disk_min_bytes']}",
        f"most disk one check used: {result['check_disk_peak_bytes']} bytes",
        f"states: {states}",
        f"test files selected: {_list(checks, 'selected_files')}; tests seen with the change: "
        f"{_list(checks, 'change_tests_seen')}; on dev: {_list(checks, 'dev_tests_seen')}",
    ]


def timeline_line(result: dict[str, Any], catalog: Path) -> str:
    """The ``scripts/praxis_timeline.py`` arguments that read this run: its window and the folder its clocks went to."""
    root = str(Path(catalog).absolute())
    root = f'"{root}"' if " " in root else root
    since, until = local_time(result["started_at"] - 300), local_time(result["ended_at"] + 300)
    return f"timeline: --since {since} --until {until} --catalog-root {root}"


def _figures(readings: list[tuple[Reading, float]]) -> dict[str, Any]:
    """Other load over *readings*: mean, peak, seconds over the limit, most headless browser processes.

    Each reading comes with the seconds it counts for, which is what the seconds over the limit add up.
    """
    read = [r.other_pct for r, _s in readings if r.other_pct is not None]
    browsers = [r.browsers for r, _s in readings if r.browsers is not None]
    over = [s for r, s in readings if r.other_pct is not None and r.other_pct > OTHER_LOAD_LIMIT_PCT]
    return {
        "other_cpu_mean_pct": round(sum(read) / len(read), 1) if read else None,
        "other_cpu_peak_pct": round(max(read), 1) if read else None,
        "other_cpu_over_s": round(sum(over, 0.0), 1),
        "headless_browser_processes_max": max(browsers) if browsers else None,
    }


def load_window(entry: dict[str, Any], readings: list[Reading]) -> None:
    """The other load while *entry*'s check ran, in the same window as its free disk, and how much of it was read.

    A reading counts for the part of the second before it that falls inside the window; one taken inside the window
    with no such part (the first, or one that failed) still gives its count of headless browser processes. The window
    is measured when the readings with other load cover at least :data:`MEASURED_SHARE_MIN` of it; quiet needs that.
    """
    start, end = entry["ran_from"], entry["ran_to"]
    parts = [(r, max(0.0, min(r.at, end) - max(r.at - r.span_s, start))) for r in readings]
    inside = [(r, s) for r, s in parts if s > 0 or start <= r.at <= end]
    figures, window_s = _figures(inside), end - start
    measured_s = sum((s for r, s in inside if r.other_pct is not None), 0.0)
    measured = window_s > 0 and measured_s >= MEASURED_SHARE_MIN * window_s
    over = any(r.other_pct > OTHER_LOAD_LIMIT_PCT for r, _s in inside if r.other_pct is not None)
    entry.update(figures)
    entry["other_load_measured_s"], entry["other_load_window_s"] = round(measured_s, 1), round(window_s, 1)
    entry["other_load_measured"] = measured
    entry["quiet"] = measured and not over and figures["headless_browser_processes_max"] == 0


def load_summary(
    checks: list[dict[str, Any]], readings: list[Reading], waited: dict[str, Any] | None, own_from: str | None
) -> dict[str, Any]:
    """The run's other load: ``quiet`` only when every check was, the figures over every reading, and the wait."""
    load = {"limit_pct": OTHER_LOAD_LIMIT_PCT, "own_cpu_from": own_from, "readings": len(readings)}
    load.update(_figures([(r, r.span_s) for r in readings]))
    quiet = bool(checks) and all(entry.get("quiet") is True for entry in checks)
    return {"quiet": quiet, "other_load": load, "wait_quiet": waited}


def _show(value: object, unit: str = "") -> str:
    return "-" if value is None else f"{value}{unit}"


def load_lines(result: dict[str, Any]) -> list[str]:
    """Whether other work ran beside the checks, said first, so a loaded run is never read as the code's speed."""
    load = result.get("other_load")
    if load is None:
        return []  # a summary from before other load was recorded
    lines, limit, waited = [], load["limit_pct"], result.get("wait_quiet")
    if waited and not waited.get("measured", True):
        lines.append("DID NOT WAIT for a quiet machine: other load cannot be measured here (no psutil)")
    elif waited and not waited["got_quiet"]:
        lines.append(f"NEVER GOT QUIET in the {waited['limit_s']:g} s --wait-quiet allowed; the checks started anyway")
    elif waited:
        lines.append(f"waited {waited['waited_s']:g} s for {waited['need_s']:g} quiet seconds in a row before starting")
    if load["other_cpu_peak_pct"] is None:
        return [*lines, "OTHER LOAD NOT MEASURED: nothing here shows whether other work slowed these checks"]
    if result["quiet"]:
        peak = _show(load["other_cpu_peak_pct"], "%")
        lines.append(f"quiet: other load at most {limit:g}% of the CPU (peak {peak}), no headless browser process")
        return lines
    checks = result["checks"]
    unseen = [entry for entry in checks if not entry.get("other_load_measured")]
    loaded = [entry for entry in checks if not entry.get("quiet") and entry.get("other_load_measured")]
    if loaded:
        lines.append(
            f"NOT QUIET: other work ran beside {len(loaded)} of {len(checks)} checks, so this run's times are not the"
            f" code's speed (own CPU from the {load['own_cpu_from']})"
        )
    for entry in loaded:
        mean, peak = _show(entry.get("other_cpu_mean_pct"), "%"), _show(entry.get("other_cpu_peak_pct"), "%")
        over, most = _show(entry.get("other_cpu_over_s")), _show(entry.get("headless_browser_processes_max"))
        lines.append(
            f"  {entry['execution_id']}: other load mean {mean}, peak {peak}, {over} s over {limit:g}%,"
            f" up to {most} headless browser processes"
        )
    if unseen:
        names = ", ".join(
            f"{entry['execution_id']} ({entry.get('other_load_measured_s', 0):g} of"
            f" {entry['ran_to'] - entry['ran_from']:g} s read)"
            for entry in unseen
        )
        them = "it" if len(unseen) == 1 else "them"
        lines.append(f"OTHER LOAD NOT MEASURED while {names} ran: nothing shows whether other work slowed {them}")
    return lines
