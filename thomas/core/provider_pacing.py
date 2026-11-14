"""Shared provider pacing ported from the real Praxis Stage 3 experiment.

LIVE STAGE3-01 (runs/20260918T173633Z-live-stage3-01) put about 100 requests in flight at once; the provider refused 9 of them without
usage (HTTP 429 rate limiting). Every refusal fell on a send made while 40 or more requests were in flight; the 92 sends made while
fewer than 40 were in flight had none (STAGE3-NOTES-02). All 100 builders stay live and concurrently active (holding work, tools and
integration holds); only their PROVIDER SENDS are paced here.

ProviderPacer is shared by every worker event loop and thread for one provider.
- A slot is taken before a request is forwarded and returned when the guard records that attempt's terminal facts. At most
  `cap` requests are in flight; `cap` starts at `ceiling` (the frozen spec value provider_max_inflight).
- A queued model request holds no HTTP connection. Its waiting time is recorded,
  and cancellation removes its ticket.
- Waiting is FIFO by arrival ticket and never holds a lock: acquire() polls with asyncio.sleep, so every event loop keeps running.
  A builder's own Retry-After wait happens before it joins the FIFO queue, so it never blocks other builders.
- AIMD: a provider refusal (429 or 5xx without usage) halves `cap` (never below `floor`), at most once per refusal window (a
  refusal of a request sent before the last decrease does not decrease again); each `increase_every` clean settlements since the
  last change add 1 (never above `ceiling`). Every change is journaled.
- Retry-After: a refused builder's NEXT send waits until the provider's Retry-After (seconds or an HTTP date), bounded by
  `retry_after_max_s`, or `retry_after_default_s` when the provider gave none. The wait is for THAT builder only.
- Per-builder refusal counts are kept for the report.
"""

from __future__ import annotations

import asyncio
import email.utils
import itertools
import threading
import time
from collections.abc import Callable
from typing import Any

SCHEMA = "stage3-provider-pacing/1"


def parse_retry_after(raw: Any, *, now_wall: float | None = None) -> float | None:
    """Seconds from a Retry-After value (delta-seconds or an HTTP date); None when absent or unparseable."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None
    try:
        seconds = float(text)
        return seconds if seconds >= 0 else None
    except ValueError:
        pass
    try:
        moment = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if moment is None:
        return None
    return max(0.0, moment.timestamp() - (time.time() if now_wall is None else now_wall))


class ProviderPacer:
    def __init__(
        self,
        *,
        ceiling: int,
        floor: int,
        increase_every: int,
        retry_after_default_s: float,
        retry_after_max_s: float,
        reserved_interactive: int = 0,
        clock: Callable[[], float] = time.monotonic,
        poll_s: float = 0.02,
    ) -> None:
        if type(ceiling) is not int or type(floor) is not int or not 1 <= floor <= ceiling:
            raise ValueError(f"the pacer needs 1 <= floor <= ceiling, got floor {floor!r} ceiling {ceiling!r}")
        if type(increase_every) is not int or increase_every < 1:
            raise ValueError("increase_every must be a positive int")
        if not 0 <= float(retry_after_default_s) <= float(retry_after_max_s):
            raise ValueError("0 <= retry_after_default_s <= retry_after_max_s must hold")
        if type(reserved_interactive) is not int or not 0 <= reserved_interactive < ceiling:
            raise ValueError("reserved_interactive must be smaller than the ceiling")
        self.ceiling, self.floor, self.increase_every = ceiling, floor, increase_every
        self.reserved_interactive = reserved_interactive
        self.retry_after_default_s, self.retry_after_max_s = float(retry_after_default_s), float(retry_after_max_s)
        self._clock = clock
        self._poll_s = float(poll_s)
        self._lock = threading.Lock()
        self._tickets = itertools.count(1)
        self._waiting: list[int] = []
        self._interactive_waiting: list[int] = []
        self.cap = ceiling
        self.inflight = 0
        self.peak_inflight = 0
        self._clean_since_change = 0
        self._last_decrease_mono: float | None = None
        self._not_before: dict[str, float] = {}
        self.refusals: dict[str, int] = {}
        self.journal: list[dict[str, Any]] = []
        self.waits: list[dict[str, Any]] = []

    def _note(self, event: str, **fields: Any) -> None:
        self.journal.append(
            {
                "seq": len(self.journal) + 1,
                "event": event,
                "t_mono": self._clock(),
                "t_wall": time.time(),
                "cap": self.cap,
                "inflight": self.inflight,
                **fields,
            }
        )

    async def acquire(
        self, builder: str, *, lane: str = "worker", abort: Callable[[], bool] = lambda: False
    ) -> dict[str, Any]:
        """Wait for this builder's Retry-After (if any) and then for a slot, FIFO. Returns the wait facts; `slot` is False only when
        abort() became true first (the caller then refuses through its own stop path and must not release)."""
        if lane not in {"worker", "interactive"}:
            raise ValueError("unknown provider admission lane")
        started = self._clock()
        with self._lock:
            not_before = self._not_before.get(builder)
        # The Retry-After wait comes first and OUTSIDE the FIFO queue, so a builder waiting out its own Retry-After never holds up
        # other builders' sends.
        while not_before is not None and self._clock() < not_before:
            if abort():
                return self._left(None, builder, started, self._clock() - started, slot=False)
            await asyncio.sleep(min(self._poll_s * 5, max(0.0, not_before - self._clock())))
        retry_wait = self._clock() - started
        with self._lock:
            ticket = next(self._tickets)
            queue = self._interactive_waiting if lane == "interactive" else self._waiting
            queue.append(ticket)
        try:
            while True:
                if abort():
                    return self._left(ticket, builder, started, retry_wait, slot=False)
                with self._lock:
                    allowance = self.cap if lane == "interactive" else max(1, self.cap - self.reserved_interactive)
                    if queue and queue[0] == ticket and self.inflight < allowance:
                        queue.pop(0)
                        self.inflight += 1
                        self.peak_inflight = max(self.peak_inflight, self.inflight)
                        self._not_before.pop(builder, None)
                        waited = self._clock() - started
                        row = {
                            "builder": builder,
                            "lane": lane,
                            "ticket": ticket,
                            "wait_s": round(waited, 6),
                            "retry_after_wait_s": round(retry_wait, 6),
                            "slot_wait_s": round(max(0.0, waited - retry_wait), 6),
                            "cap_at_acquire": self.cap,
                            "inflight_after_acquire": self.inflight,
                            "slot": True,
                        }
                        self.waits.append(row)
                        return dict(row)
                await asyncio.sleep(self._poll_s)
        finally:
            with self._lock:
                if ticket in queue:
                    queue.remove(ticket)

    def _left(
        self, ticket: int | None, builder: str, started: float, retry_wait: float, *, slot: bool
    ) -> dict[str, Any]:
        with self._lock:
            if ticket is not None:
                for queue in (self._waiting, self._interactive_waiting):
                    if ticket in queue:
                        queue.remove(ticket)
            row = {
                "builder": builder,
                "ticket": ticket,
                "wait_s": round(self._clock() - started, 6),
                "retry_after_wait_s": round(retry_wait, 6),
                "slot": slot,
                "aborted": True,
            }
            self.waits.append(row)
            return dict(row)

    def release(
        self,
        builder: str,
        *,
        kind: str,
        sent_mono: float | None = None,
        retry_after_raw: Any = None,
        status: Any = None,
    ) -> dict[str, Any]:
        """Return one slot. kind: "clean" (validated usage), "provider_refusal" (429/5xx without usage), "not_sent" or "failed"."""
        with self._lock:
            self.inflight = max(0, self.inflight - 1)
            change = None
            if kind == "provider_refusal":
                self.refusals[builder] = self.refusals.get(builder, 0) + 1
                parsed = parse_retry_after(retry_after_raw)
                wait = self.retry_after_default_s if parsed is None else min(parsed, self.retry_after_max_s)
                self._not_before[builder] = self._clock() + wait
                new_window = (
                    self._last_decrease_mono is None or sent_mono is None or sent_mono > self._last_decrease_mono
                )
                if new_window:
                    old = self.cap
                    self.cap = max(self.floor, self.cap // 2)
                    self._last_decrease_mono = self._clock()
                    self._clean_since_change = 0
                    change = {"from": old, "to": self.cap}
                self._note(
                    "provider_refusal",
                    builder=builder,
                    status=status,
                    retry_after_raw=None if retry_after_raw is None else str(retry_after_raw)[:64],
                    retry_after_s=round(wait, 6),
                    retry_after_bounded=parsed is not None and parsed > self.retry_after_max_s,
                    builder_refusals=self.refusals[builder],
                    decrease=change,
                    same_window=not new_window,
                )
            elif kind == "clean":
                # Settling a request sent before the last refusal does not prove
                # recovery at the newly reduced provider allowance.
                if self._last_decrease_mono is None or sent_mono is None or sent_mono > self._last_decrease_mono:
                    self._clean_since_change += 1
                if self._clean_since_change >= self.increase_every and self.cap < self.ceiling:
                    old = self.cap
                    self.cap += 1
                    self._clean_since_change = 0
                    change = {"from": old, "to": self.cap}
                    self._note("increase", builder=builder, increase=change)
            return {"kind": kind, "cap": self.cap, "inflight": self.inflight, "change": change}

    def report(self) -> dict[str, Any]:
        with self._lock:
            waits = [row for row in self.waits if row.get("slot")]
            ordered = sorted(row["wait_s"] for row in waits)
            return {
                "schema": SCHEMA,
                "ceiling": self.ceiling,
                "floor": self.floor,
                "increase_every": self.increase_every,
                "retry_after_default_s": self.retry_after_default_s,
                "retry_after_max_s": self.retry_after_max_s,
                "cap_now": self.cap,
                "inflight_now": self.inflight,
                "peak_inflight": self.peak_inflight,
                "waiting_now": len(self._waiting) + len(self._interactive_waiting),
                "reserved_interactive": self.reserved_interactive,
                "acquired": len(waits),
                "aborted": sum(1 for row in self.waits if row.get("aborted")),
                "wait_s": {
                    "max": ordered[-1] if ordered else 0.0,
                    "median": ordered[len(ordered) // 2] if ordered else 0.0,
                    "p90": ordered[int(len(ordered) * 0.9)] if ordered else 0.0,
                    "total": round(sum(ordered), 6),
                },
                "refusals_by_builder": dict(sorted(self.refusals.items())),
                "refusals_total": sum(self.refusals.values()),
                "cap_changes": [row for row in self.journal if row.get("decrease") or row.get("increase")],
                "journal": list(self.journal),
            }


def from_spec(spec: dict[str, Any], **kwargs: Any) -> ProviderPacer:
    pacing = spec["provider_pacing"]
    return ProviderPacer(
        ceiling=pacing["provider_max_inflight"],
        floor=pacing["floor"],
        increase_every=pacing["increase_every_clean_settlements"],
        retry_after_default_s=pacing["retry_after_default_s"],
        retry_after_max_s=pacing["retry_after_max_s"],
        **kwargs,
    )


__all__ = ["ProviderPacer", "SCHEMA", "from_spec", "parse_retry_after"]
