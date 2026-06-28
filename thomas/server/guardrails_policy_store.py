"""Server-side persistence for the guardrails policy (preset + per-group modes).

A tiny locked JSON file living next to the preferences DB. The policy model and
validation live in :mod:`thomas.server.guardrails_state`; this module only reads
and writes it durably.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from thomas.server.guardrails_state import GuardrailsState, normalize_state

_LOCK = threading.RLock()


def _policy_path() -> Path:
    """`guardrails_policy.json` in the same directory as the preferences DB."""
    try:
        from thomas.preferences._utils import get_db_path

        base = Path(get_db_path()).expanduser().parent
    except Exception:
        base = Path.home() / ".thomas"
    return base / "guardrails_policy.json"


def load_guardrails_policy() -> GuardrailsState:
    """Read the persisted policy, coerced to a valid state (defaults if absent)."""
    path = _policy_path()
    with _LOCK:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return GuardrailsState()
    return normalize_state(raw if isinstance(raw, dict) else None)


def save_guardrails_policy(state: GuardrailsState | dict | None) -> GuardrailsState:
    """Validate and persist the policy. Returns the normalized state that was saved."""
    norm = state if isinstance(state, GuardrailsState) else normalize_state(state if isinstance(state, dict) else None)
    path = _policy_path()
    with _LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(norm.to_dict(), separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass
    return norm
