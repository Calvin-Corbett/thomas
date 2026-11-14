"""What Claude Code's ``opus``/``sonnet``/``haiku`` actually start, and how to say so.

The model menu used to label ``opus`` "Claude Opus (newest)". Nothing checked
that. On this machine's Claude Code 2.1.278, ``--model opus`` starts
``claude-opus-5`` while ``claude-opus-5-5`` exists and is newer, so every run
carried a label that outranked the fact. The label was a promise about a name
the CLI resolves privately, written by us, verified by nobody.

This module holds the two things that CAN be checked, and keeps them apart:

* **What the engine reported.** Claude Code prints a ``system``/``init`` event
  naming the exact model it started, and its ``result`` carries ``modelUsage``
  keyed by exact model id. ``remember_engine_model`` records that observation;
  it is the only evidence of what an alias resolves to on THIS machine, because
  only the engine knows.
* **What the provider listed.** ``thomas/core/listed_models.py`` carries the
  Claude ids Anthropic's own list returned on its last check.
  ``newest_listed_for`` orders them. That answers "which Opus is newest", which
  is a DIFFERENT question from "which Opus does ``opus`` start" — the bug above
  is exactly the gap between the two, so the wording never merges them.

``alias_label`` turns whichever of those exists into a display name and a
sentence that names its basis. With neither, the label is "Claude Opus" and the
description says the exact model is recorded after the first run. It never says
"newest" on nobody's authority.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

# The three names Claude Code accepts as a size rather than as an exact model.
# Kept as its own tuple, not imported from ``claude_plan.CLAUDE_PLAN_MODEL_IDS``,
# because that one answers "what may the transport send"; this one answers "what
# is an alias, and therefore needs resolving". They coincide today.
CLAUDE_SIZE_ALIASES = ("opus", "sonnet", "haiku")

_SIZE_TITLES = {"opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku"}

# Where the alias resolutions this machine has observed are kept, so the menu
# still tells the truth on the next boot instead of forgetting it at exit.
_STORE_NAME = "claude_alias_ids.json"

_lock = threading.Lock()
_observed: dict[str, str] | None = None

# Digit groups in an Anthropic model id. An eight-digit group is a release DATE
# and the rest are the VERSION: ``claude-sonnet-4-5-20250929`` is version (4, 5)
# of 2025-09-29, ``claude-sonnet-4-20250514`` is version (4,) of 2025-05-14.
# Ordering the raw groups instead made that second id (4, 20250514) outrank the
# first (4, 5, 20250929), and the menu would have called the older model newest.
_DIGITS = re.compile(r"\d+")
_DATE_DIGITS = 8


def normalize_alias(name: str) -> str:
    """The bare alias in ``name``, or "" when it is not one.

    Accepts the shapes a turn actually carries: ``opus``, ``claude:opus``,
    ``Claude:Opus``. An exact id (``claude-opus-5-5``) is not an alias and
    answers "".
    """
    text = str(name or "").strip().lower()
    if ":" in text:
        text = text.rsplit(":", 1)[-1].strip()
    return text if text in CLAUDE_SIZE_ALIASES else ""


def _store_path() -> Path:
    """The observations file under the active Thomas data directory."""
    home = str(os.environ.get("THOMAS_HOME") or "").strip()
    if home:
        return Path(home) / _STORE_NAME
    from thomas.core.config import resolve_thomas_data_dir

    return resolve_thomas_data_dir() / _STORE_NAME


def _load() -> dict[str, str]:
    """Read the observations file. Unreadable or malformed reads as empty.

    A lost observation costs a label its exact id until the next run reports
    one; a raised exception here would cost the model menu.
    """
    global _observed
    if _observed is not None:
        return _observed
    rows: dict[str, str] = {}
    try:
        raw = json.loads(_store_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for alias, exact in raw.items():
                key, value = normalize_alias(str(alias)), str(exact or "").strip()
                if key and value:
                    rows[key] = value
    except (OSError, ValueError, TypeError):
        rows = {}
    _observed = rows
    return rows


def _save(rows: dict[str, str]) -> None:
    try:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    except (OSError, ValueError, TypeError):
        pass  # the in-process resolution still holds; only the next boot forgets


def forget_observations() -> None:
    """Drop the in-process cache so the next read goes back to the file (tests)."""
    global _observed
    with _lock:
        _observed = None


def remember_engine_model(requested: str, exact_id: str) -> bool:
    """Record that ``requested`` started ``exact_id``, as the engine reported it.

    Returns whether this changed what is known. Only an ALIAS is recorded: a
    turn that asked for an exact id taught us nothing about a name the CLI
    resolves. An ``exact_id`` that is itself an alias is refused for the same
    reason — an engine echoing "opus" back has not resolved anything.
    """
    alias = normalize_alias(requested)
    exact = str(exact_id or "").strip()
    if not alias or not exact or normalize_alias(exact):
        return False
    with _lock:
        # Compare against the FILE, not this process's copy of it. The Build
        # runner is another process writing the same file; with only the cache
        # to compare, a server whose copy already matched never rewrote a wrong
        # value the runner had put on disk, and that value came back on restart.
        globals()["_observed"] = None
        rows = dict(_load())
        if rows.get(alias) == exact:
            return False
        rows[alias] = exact
        globals()["_observed"] = rows
        _save(rows)
    return True


def engine_model_for(alias: str) -> str:
    """The exact id the engine last reported for this alias here, or ""."""
    key = normalize_alias(alias)
    if not key:
        return ""
    with _lock:
        return _load().get(key, "")


def _version_key(model_id: str) -> tuple[tuple[int, ...], int]:
    """``(version, date)`` for ordering: the version decides, the date breaks a tie."""
    groups = _DIGITS.findall(model_id)
    version = tuple(int(part) for part in groups if len(part) != _DATE_DIGITS)
    dates = [int(part) for part in groups if len(part) == _DATE_DIGITS]
    return version, max(dates, default=0)


def newest_listed_for(alias: str, listed: object = None) -> str:
    """The newest exact id Anthropic's own list carries for this size, or "".

    This is what the PROVIDER published, not what the alias starts. The two
    disagreed on the machine that prompted this module, so the caller must keep
    them apart in what it says.
    """
    key = normalize_alias(alias)
    if not key:
        return ""
    if listed is None:
        from thomas.core.listed_models import listed as listed_ids

        listed = listed_ids("anthropic")
    candidates = [
        str(model_id)
        for model_id in (listed or ())
        if key in str(model_id).lower() and str(model_id).lower().startswith("claude")
    ]
    if not candidates:
        return ""
    return max(candidates, key=lambda model_id: (_version_key(model_id), model_id))


def resolve_alias(alias: str, listed: object = None) -> tuple[str, str]:
    """``(exact_id, basis)`` for an alias, engine first, provider list second.

    ``basis`` is ``"engine"``, ``"provider-list"``, or ``""`` with no id. The
    engine wins because it is the only source that answers the question the
    label asks — what this name STARTS.
    """
    key = normalize_alias(alias)
    if not key:
        return "", ""
    observed = engine_model_for(key)
    if observed:
        return observed, "engine"
    published = newest_listed_for(key, listed)
    return (published, "provider-list") if published else ("", "")


def alias_label(alias: str, listed: object = None) -> tuple[str, str]:
    """``(display_name, description)`` for one alias — checked claims only."""
    key = normalize_alias(alias)
    if not key:
        return "", ""
    title = f"Claude {_SIZE_TITLES[key]}"
    exact, basis = resolve_alias(key, listed)
    if basis == "engine":
        return f"{title} ({exact})", f"Claude Code's `{key}` started {exact} here."
    if basis == "provider-list":
        # Deliberately NOT in the display name: Anthropic listing this as the
        # newest of its size is not a statement about what `opus` starts, and
        # putting it in the name would make it read as one.
        return title, f"Anthropic's list has {exact} as its newest {_SIZE_TITLES[key]}; `{key}` is unchecked here."
    return title, f"Claude Code chooses the exact model for `{key}`; Thomas records it from the first run that uses it."
