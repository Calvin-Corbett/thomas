"""Which model profiles are resting, for how long, and whose limit is really out.

The LLM client parks a profile after a rate limit or a run of server
failures (``thomas/core/llm_client.py``, one process-wide registry keyed by
profile name). A chat turn that hits the park fails with a generic error and
the person learns nothing about when the model is back. This reader lets a
route say so, and the page count it down (frontier parity: Codex shows its
rate-limit reset; 2026-09-05).

A park after a rate limit is capped at ten minutes, and the plan limit that
set it can run for a day and a half, so ``remaining_s`` on its own is the
"wait a moment" you were told in about, as a ticking countdown. The park now
keeps the provider's own refusal, so when that refusal says the account is out
of allowance the row also carries whose limit it is and when it resets, read
by the one reader (``thomas/core/provider_limits.py``) and worded once there.
A park that remembers nothing, or a genuine short burst, carries neither and
is still just a countdown.

Three questions, three lifetimes, so no caller has to pick the wrong one:
``active_cooldowns`` is the park itself, ``spent_allowances`` is whose account
is out and until when, and ``limit_rows`` is what a page asks for -- both, so a
limit that outlives its park is still announced.
"""

from __future__ import annotations

import math
import time
from typing import Any

from thomas.core import llm_client
from thomas.core.provider_limits import read_limit, when_words


def active_cooldowns(*, at: float | None = None) -> list[dict[str, Any]]:
    """Resting profiles, longest wait first; empty when every profile is available."""
    now = time.time() if at is None else float(at)
    rows: list[dict[str, Any]] = []
    for profile, cooldown in list(llm_client._PROVIDER_COOLDOWNS.items()):
        remaining = float(cooldown.remaining())
        if remaining <= 0:
            continue
        row: dict[str, Any] = {
            "profile": str(profile),
            "remaining_s": int(math.ceil(remaining)),
            "failure_type": str(cooldown.failure_type or ""),
        }
        rows.append(row | _account_limit(str(cooldown.refusal or ""), now))
    rows.sort(key=lambda r: r["remaining_s"], reverse=True)
    return rows


def spent_allowances(*, at: float | None = None) -> dict[str, float]:
    """Profiles whose remembered refusal says the account is out, and when each resets.

    ``active_cooldowns`` answers on the park's own clock, and a rate-limit park is
    capped at ten minutes (``llm_provider_state.py``) while the allowance behind it
    can be out until Saturday. "Is this account out?" therefore has to be asked with
    the reset as its lifetime, not the park's: the park's record outlives the park
    itself — it is cleared when that profile next answers — so the words are still
    here to read. Whoever names what you can use instead reads this, so a plan that
    is out is not offered ten minutes after refusing you.

    A refusal that named no reset is not kept past the park: the provider gave
    nothing to wait for, and claiming a connection is out with no time to point at
    would keep it hidden until the process restarts. A wait the body gave only as a
    duration ("retry after 3600s") is the same case here, because the duration runs
    from the refusal and this reads it later: counted from now, it would move further
    off every time it was asked and never arrive. A clock time is asked for, and
    ``resets_at`` is what every engine this product speaks to gives on a plan limit.
    """
    now = time.time() if at is None else float(at)
    out: dict[str, float] = {}
    for profile, cooldown in list(llm_client._PROVIDER_COOLDOWNS.items()):
        limit = read_limit(str(cooldown.refusal or ""), at=now)
        if limit is None or limit.resets_at is None or not limit.is_account_limit(now):
            continue
        if limit.resets_at > now:
            out[str(profile)] = limit.resets_at
    return out


def limit_rows(*, at: float | None = None) -> list[dict[str, Any]]:
    """What the line under the message box is told: every park, and every allowance still out.

    ``active_cooldowns`` answers on the park's own clock, and that is the wrong clock
    for "is this account out of allowance?" -- a rate-limit park is capped at ten
    minutes and the limit you met ran 41 hours. Read on it alone the line went quiet
    eleven minutes into that limit, and a chat page opened at any point over the rest
    of the day said nothing about the limit at all: the page has no other way to learn
    one is running before it sends a message and is refused.

    A spent allowance is therefore reported for as long as it is out, with
    ``remaining_s`` 0, because there is no park left to count: the page ends such a
    line at the reset rather than at the park (``rate_limit_banner.js``). A burst that
    has cleared, and a park that remembered nothing, are gone from here as before.
    """
    now = time.time() if at is None else float(at)
    rows = active_cooldowns(at=now)
    parked = {str(row["profile"]) for row in rows}
    for profile in spent_allowances(at=now):
        if profile in parked:
            continue
        cooldown = llm_client._PROVIDER_COOLDOWNS.get(profile)
        facts = _account_limit(str(getattr(cooldown, "refusal", "") or ""), now)
        if facts:
            rows.append({"profile": profile, "remaining_s": 0, "failure_type": "rate_limit"} | facts)
    return rows


def _account_limit(refusal: str, now: float) -> dict[str, Any]:
    """The spent-allowance facts the remembered refusal carried, or nothing.

    Nothing is the honest answer for a burst limit and for a park with no words:
    the page must not name a reset the provider never gave.
    """
    limit = read_limit(refusal, at=now)
    if limit is None or not limit.is_account_limit(now):
        return {}
    facts: dict[str, Any] = {"account": limit.account, "spent": True}
    moment = limit.reached_at(now)
    if moment is not None:
        facts["resets_at"] = round(moment, 3)
        facts["resets_words"] = when_words(moment)
        facts["resets_estimated"] = bool(limit.estimated)
    return facts


__all__ = ["active_cooldowns", "limit_rows", "spent_allowances"]
