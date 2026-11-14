"""What a Build run records for the page: the context meter's numbers, usage and speed, and the two controls on it.

Kept apart from :mod:`thomas.forge.anvil.run_control` (pause, messages, questions) so neither grows past its size.
Everything here is still reachable as ``run_control.<name>``: that module hands any name it does not define to this one.
All of it lives in the run's own control folder: ``context.json`` (tokens in use, the window in force, the model's own
window, where the tokens went), ``context_cap.json`` (the window you chose with the slider), ``compact.request`` (one
click of Compact now) and ``usage.json`` (tokens, seconds and time to first output across the run's passes).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from thomas.forge.anvil.run_control import _read_json, _write_json, now_ms

log = logging.getLogger(__name__)


def _clean_breakdown(rows: Any) -> list[dict[str, Any]]:
    """The rows of the context panel, kept only if each is a short label with a whole, non-negative token count."""
    clean: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("label"), str):
            continue
        tokens = row.get("tokens")
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
            continue
        clean.append({"label": row["label"][:60], "tokens": tokens})
    return clean[:12]


def write_context(directory: Path, tokens: int, window: int, breakdown: Any = None, model_window: Any = None) -> None:
    """The lead's newest context use (tokens in its prompt, the window in force, where they went), for the meter.

    ``model_window`` is the window the model's own profile declares, kept beside the one in force (which is the
    one you chose with the slider, when you did) so the panel can say what the default is."""
    try:
        used, room = int(tokens), int(window)
    except (TypeError, ValueError):
        return
    if used < 0 or room <= 0:
        return
    own = (
        model_window
        if isinstance(model_window, int) and not isinstance(model_window, bool) and model_window > 0
        else room
    )
    try:
        _write_json(
            Path(directory) / "context.json",
            {
                "tokens": used,
                "window": room,
                "model_window": own,
                "breakdown": _clean_breakdown(breakdown),
                "at": now_ms(),
            },
        )
    except OSError:
        log.debug("could not record context use in %s", directory, exc_info=True)


CONTEXT_STEP = 25_000


CONTEXT_MIN = CONTEXT_STEP


CONTEXT_MAX = 2_000_000


def set_context_cap(directory: Path, window: int) -> int | None:
    """The context window you chose for this run, in whole steps of 25,000 (0 clears it). Returns what was kept."""
    try:
        wanted = int(window)
    except (TypeError, ValueError):
        return None
    path = Path(directory) / "context_cap.json"
    if wanted <= 0:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    kept = min(CONTEXT_MAX, max(CONTEXT_MIN, round(wanted / CONTEXT_STEP) * CONTEXT_STEP))
    try:
        _write_json(path, {"window": kept, "at": now_ms()})
    except OSError:
        log.debug("could not record a context window in %s", directory, exc_info=True)
        return None
    return kept


def read_context_cap(directory: Path) -> int | None:
    data = _read_json(Path(directory) / "context_cap.json")
    window = data.get("window") if data else None
    if isinstance(window, bool) or not isinstance(window, int) or not CONTEXT_MIN <= window <= CONTEXT_MAX:
        return None
    return window


def request_compaction(directory: Path) -> None:
    """Ask the lead to compact its context at its next step (the meter's Compact button)."""
    try:
        _write_json(Path(directory) / "compact.request", {"at": now_ms()})
    except OSError:
        log.debug("could not record a compaction request in %s", directory, exc_info=True)


def take_compaction_request(directory: Path) -> bool:
    """True once for each request: the file is removed as it is read, so one click compacts one time."""
    path = Path(directory) / "compact.request"
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def _usage_path(directory: Path) -> Path:
    return Path(directory) / "usage.json"


def add_usage(directory: Path, prompt: int, completion: int, total: int, seconds: float) -> None:
    """Add one finished pass of the lead to the run's totals: tokens used and the seconds the pass took."""
    try:
        numbers = [int(prompt), int(completion), int(total)]
        took = float(seconds)
    except (TypeError, ValueError):
        return
    if min(numbers) < 0 or took < 0:
        return
    existing = _read_json(_usage_path(directory)) or {}
    row = {
        "prompt": int(existing.get("prompt") or 0) + numbers[0],
        "completion": int(existing.get("completion") or 0) + numbers[1],
        "total": int(existing.get("total") or 0) + numbers[2],
        "seconds": float(existing.get("seconds") or 0) + took,
        "passes": int(existing.get("passes") or 0) + 1,
        "at": now_ms(),
    }
    if existing.get("first_output_s") is not None:
        row["first_output_s"] = existing["first_output_s"]
    try:
        _write_json(_usage_path(directory), row)
    except OSError:
        log.debug("could not record usage in %s", directory, exc_info=True)


def write_first_output(directory: Path, seconds: float) -> None:
    """How long the lead took to produce its first words, thought or tool call; kept once per run."""
    try:
        took = float(seconds)
    except (TypeError, ValueError):
        return
    existing = _read_json(_usage_path(directory)) or {}
    if took < 0 or existing.get("first_output_s") is not None:
        return
    try:
        _write_json(_usage_path(directory), {**existing, "first_output_s": took, "at": existing.get("at") or now_ms()})
    except OSError:
        log.debug("could not record the first output time in %s", directory, exc_info=True)


def usage_summary(catalog_root: str | Path, days: int = 7) -> dict[str, Any]:
    """Tokens per day and how fast the lead goes, over the runs that recorded usage in the last ``days`` days."""
    base = Path(catalog_root) / ".thomas" / "evolve" / "agent" / "run_control"
    since = now_ms() - max(1, int(days)) * 86_400_000
    per_day: dict[str, dict[str, int]] = {}
    seconds = completion = total = runs = 0
    firsts: list[float] = []
    try:
        folders = [path for path in base.iterdir() if path.is_dir()]
    except OSError:
        folders = []
    for folder in folders:
        row = _read_json(_usage_path(folder))
        if not row or int(row.get("at") or 0) < since:
            continue
        stamp = time.strftime("%Y-%m-%d", time.localtime(int(row["at"]) / 1000))
        day = per_day.setdefault(stamp, {"total": 0, "prompt": 0, "completion": 0, "runs": 0})
        for key in ("total", "prompt", "completion"):
            day[key] += int(row.get(key) or 0)
        day["runs"] += 1
        if row.get("seconds"):
            seconds += float(row["seconds"])
            completion += int(row.get("completion") or 0)
            total += int(row.get("total") or 0)
        if row.get("first_output_s") is not None:
            firsts.append(float(row["first_output_s"]))
        runs += 1
    firsts.sort()
    return {
        "days": [{"date": date, **per_day[date]} for date in sorted(per_day)],
        "runs": runs,
        "tokens_per_second": round(total / seconds, 1) if seconds else None,
        "reply_tokens_per_second": round(completion / seconds, 1) if seconds else None,
        "first_output_median_s": round(firsts[len(firsts) // 2], 1) if firsts else None,
    }


def read_context(directory: Path) -> dict[str, Any] | None:
    data = _read_json(Path(directory) / "context.json")
    if not data:
        return None
    tokens, window = data.get("tokens"), data.get("window")
    if (
        isinstance(tokens, bool)
        or isinstance(window, bool)
        or not isinstance(tokens, int)
        or not isinstance(window, int)
    ):
        return None
    if tokens < 0 or window <= 0:
        return None
    own = data.get("model_window")
    own = own if isinstance(own, int) and not isinstance(own, bool) and own > 0 else window
    return {
        "tokens": tokens,
        "window": window,
        "model_window": own,
        "breakdown": _clean_breakdown(data.get("breakdown")),
    }
