"""Credential-scoped quota decisions and parked Praxis child continuations.

The scheduler owns worker tasks. These functions only record durable decisions;
it must checkpoint a parked row, end its worker task, then re-admit due rows.
"""

from __future__ import annotations

import email.utils
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# Public: Autopilot's usage-limit pause (thomas/server/autopilot_park.py) imports this name from
# here. The set itself lives at the bottom of the tree (thomas/core/provider_limits.py), where the
# transports that raise these codes and the surfaces that explain them can all reach one copy.
from thomas.core.provider_limits import QUOTA_CODES

_RESET_HEADERS = ("retry-after", "x-ratelimit-reset", "x-rate-limit-reset")


@dataclass(frozen=True)
class QuotaDecision:
    kind: str  # clean, transient, quota, or other
    credential: str
    retry_at: float | None = None  # Unix seconds; safe to persist across restarts
    reason: str = ""


def _reset_at(headers: Mapping[str, Any], now: float) -> float | None:
    lowered = {str(key).lower(): value for key, value in headers.items()}
    for name in _RESET_HEADERS:
        raw = lowered.get(name)
        if raw is None:
            continue
        try:
            number = float(str(raw).strip())
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(str(raw))
            except (TypeError, ValueError, IndexError):
                continue
            return parsed.timestamp()
        if name == "retry-after" or number < 1_000_000_000:
            return now + max(0.0, number)
        return number / 1000 if number > 10_000_000_000 else number
    return None


def _error_codes(error: Mapping[str, Any] | str | None) -> set[str]:
    if not isinstance(error, Mapping):
        return set()
    nested = error.get("error")
    source = nested if isinstance(nested, Mapping) else error
    return {str(source.get(name) or "").strip().lower().replace("-", "_") for name in ("code", "type")}


class QuotaClassifier:
    """Distinguish short 429 bursts from account exhaustion per credential."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._streaks: dict[str, tuple[int, float]] = {}

    def observe(
        self,
        credential: str,
        *,
        status: int,
        error: Mapping[str, Any] | str | None = None,
        headers: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> QuotaDecision:
        if not credential:
            raise ValueError("credential identity is required")
        at = time.time() if now is None else now
        reset_at = _reset_at(headers or {}, at)
        explicit = bool(_error_codes(error) & QUOTA_CODES)
        with self._lock:
            if status != 429 and not explicit:
                self._streaks.pop(credential, None)
                return QuotaDecision("clean" if 200 <= status < 300 else "other", credential)
            count, first = self._streaks.get(credential, (0, at))
            if not count:
                first = at
            count += 1
            self._streaks[credential] = (count, first)
            exhausted = explicit or (reset_at is not None and reset_at - at > 600) or (count >= 6 and at - first > 900)
        if exhausted:
            reason = (
                "provider_quota" if explicit else "long_reset" if reset_at and reset_at - at > 600 else "429_streak"
            )
            return QuotaDecision("quota", credential, max(at, reset_at or at + 300), reason)
        return QuotaDecision("transient", credential, max(at, reset_at or at + 1), "rate_limit")


def choose_credential(
    current: str,
    *,
    credentials: Mapping[str, str],  # credential identity -> provider
    exhausted_until: Mapping[str, float],
    allowed_providers: Iterable[str],
    now: float | None = None,
) -> str | None:
    """Prefer automatic same-provider failover; cross-provider needs prior consent."""
    at = time.time() if now is None else now
    provider = credentials.get(current)
    if provider is None:
        raise ValueError("current credential is not in the pool")
    allowed = set(allowed_providers)
    options = [
        key
        for key, candidate_provider in credentials.items()
        if key != current
        and exhausted_until.get(key, 0) <= at
        and (candidate_provider == provider or candidate_provider in allowed)
    ]
    return next((key for key in options if credentials[key] == provider), options[0] if options else None)


def park_child(row: dict[str, Any], decision: QuotaDecision) -> None:
    """Persist this row before releasing its worker task and admission lease."""
    if decision.kind != "quota":
        raise ValueError("only quota-exhausted children may enter quota_wait")
    if row.get("state") in {"completed", "failed", "stopped"}:
        raise ValueError("terminal child cannot be parked")
    row["state"] = "quota_wait"
    row["quota_credential"] = decision.credential
    row["resume_at"] = decision.retry_at
    row["quota_reason"] = decision.reason
    row["attempt_started_at"] = None


def re_admit_due(
    rows: Iterable[dict[str, Any]], *, now: float | None = None, available: Iterable[str] = ()
) -> list[dict[str, Any]]:
    """Move parked continuations back to the front of admission in FIFO order."""
    at = time.time() if now is None else now
    available_set = set(available)
    due = [
        row
        for row in rows
        if row.get("state") == "quota_wait"
        and ((row.get("resume_at") is not None and float(row["resume_at"]) <= at) or available_set)
    ]
    due.sort(key=lambda row: (float(row.get("resume_at") or 0), str(row.get("agent_id") or "")))
    for row in due:
        row["state"] = "starting"
        row["attempt_started_at"] = None
    return due
