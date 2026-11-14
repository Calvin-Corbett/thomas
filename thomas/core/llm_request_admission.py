"""Optional shared admission around actual provider HTTP attempts.

The provider owns retries, credentials, token accounting, and HTTP configuration.
This object only limits simultaneous requests and their launch rate. It does not
claim to know a provider's account-specific token or requests-per-minute quota.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import os
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from thomas.core.config import resolve_thomas_data_dir
from thomas.core.cross_process_pacing import CrossProcessProviderPacer
from thomas.core.llm_transport_pool import retry_after_seconds
from thomas.core.provider_pacing import ProviderPacer

_SHARED_PACERS: dict[str, CrossProcessProviderPacer | ProviderPacer] = {}
_SHARED_PACERS_LOCK = threading.Lock()


def admission_key(config: Any) -> str:
    """Keep independent API credentials apart without storing a secret in SQLite."""
    provider = str(getattr(config, "provider", "") or "").strip().lower().replace("-", "_")
    if not provider:
        raise ValueError("model provider is required for request admission")
    if provider == "openai_codex":
        # Thomas currently connects one ChatGPT account. Access tokens rotate,
        # so hashing the token would reset the controller during an active run.
        return provider
    secret_name = str(getattr(config, "api_key_secret_name", "") or "").strip()
    key = str(getattr(config, "api_key", "") or "").strip()
    endpoint = str(getattr(config, "base_url", "") or "").strip().rstrip("/")
    identity = key or secret_name or endpoint
    if not identity:
        return provider
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"{provider}:{digest}"


class RoutedProviderAdmission:
    """Select an account queue for each actual model attempt, including failover."""

    def __init__(self, *, team: str, lane: str = "worker") -> None:
        self.team, self.lane = team, lane
        self._admissions: dict[str, SharedProviderAdmission] = {}
        self._closed = False

    def for_model(self, config: Any) -> SharedProviderAdmission:
        if self._closed:
            raise RuntimeError("This agent team's request admission is closed")
        key = admission_key(config)
        if key not in self._admissions:
            self._admissions[key] = shared_provider_admission(key, team=self.team, lane=self.lane)
        return self._admissions[key]

    def close(self) -> None:
        self._closed = True
        for admission in self._admissions.values():
            admission.close()


def shared_provider_admission(provider_key: str, *, team: str, lane: str = "worker") -> SharedProviderAdmission:
    """One adaptive provider controller across Chat and Build processes.

    A team owns only its leases. Stopping it cannot close the controller used by
    another team. The interactive lane keeps four request slots open for the
    Build lead and interactive Chat requests.
    """
    if not provider_key or not team or lane not in {"worker", "interactive"}:
        raise ValueError("provider and team identities are required")
    with _SHARED_PACERS_LOCK:
        pacer = _SHARED_PACERS.get(provider_key)
        if pacer is None:
            runtime_dir = Path(os.environ.get("THOMAS_RUNTIME_DIR") or resolve_thomas_data_dir() / "runtime")
            pacer = CrossProcessProviderPacer(
                runtime_dir / "praxis" / "provider_pacing.sqlite3",
                provider=provider_key,
                ceiling=100,
                floor=1,
                increase_every=8,
                reserved_interactive=4,
            )
            _SHARED_PACERS[provider_key] = pacer
    return SharedProviderAdmission(pacer, team=team, lane=lane)


class SharedProviderAdmission:
    """Adapt the experiment's per-builder pacer to the live HTTP stream seam."""

    def __init__(self, pacer: CrossProcessProviderPacer | ProviderPacer, *, team: str, lane: str = "worker") -> None:
        self.pacer = pacer
        self.team = team
        self.lane = lane
        self._lock = threading.Lock()
        self._active: dict[str | int, tuple[str, float]] = {}
        self._closed = False
        self._stats = dict(admitted=0, settled=0, peak_inflight=0, refusals=0, failed=0, cancelled_waits=0)

    async def acquire(self) -> str | int:
        if self._closed:
            raise RuntimeError("This agent team's request admission is closed")
        task = asyncio.current_task()
        builder = f"{self.team}:{task.get_name() if task is not None else 'request'}"
        try:
            row = await self.pacer.acquire(builder, lane=self.lane, abort=lambda: self._closed)
        except asyncio.CancelledError:
            with self._lock:
                self._stats["cancelled_waits"] += 1
            raise
        if not row["slot"]:
            raise RuntimeError("This agent team's request admission is closed")
        ticket = row["ticket"]
        with self._lock:
            self._active[ticket] = (builder, time.monotonic())
            self._stats["admitted"] += 1
            self._stats["peak_inflight"] = max(self._stats["peak_inflight"], len(self._active))
        return ticket

    def release(self, ticket: str | int, *, status: int = 0, retry_after: float = 0.0, complete: bool = False) -> None:
        with self._lock:
            active = self._active.pop(ticket, None)
            if active is None:
                return
            self._stats["settled"] += 1
            if status == 429 or 500 <= status <= 599:
                self._stats["refusals"] += 1
                kind = "provider_refusal"
            elif complete and 200 <= status < 300:
                kind = "clean"
            else:
                self._stats["failed"] += 1
                kind = "failed"
        builder, sent_at = active
        if isinstance(self.pacer, CrossProcessProviderPacer):
            self.pacer.release(
                builder,
                ticket=str(ticket),
                kind=kind,
                sent_mono=sent_at,
                retry_after_raw=retry_after,
                status=status,
            )
        else:
            self.pacer.release(builder, kind=kind, sent_mono=sent_at, retry_after_raw=retry_after, status=status)

    def snapshot(self) -> dict[str, Any]:
        report = self.pacer.report()
        with self._lock:
            return {
                **self._stats,
                "ceiling": report["ceiling"],
                "limit": report["cap_now"],
                "inflight": len(self._active),
                "waiting": report["waiting_now"],
                "closed": self._closed,
                "provider_peak_inflight": report["peak_inflight"],
                "provider_refusals_total": report["refusals_total"],
                "reserved_interactive": report["reserved_interactive"],
            }

    def close(self) -> None:
        self._closed = True


class RequestAdmission:
    """Cancellable FIFO admission shared by one explicitly owned agent team."""

    def __init__(self, *, ceiling: int, launch_interval: float = 0.0) -> None:
        if type(ceiling) is not int or not 1 <= ceiling <= 100:
            raise ValueError("ceiling must be an integer from 1 to 100")
        if not 0 <= launch_interval <= 60:
            raise ValueError("launch_interval must be between 0 and 60 seconds")
        self.ceiling = self.limit = ceiling
        self.launch_interval = float(launch_interval)
        self._lock = threading.Lock()
        self._tickets = itertools.count(1)
        self._waiting: deque[int] = deque()
        self._active: dict[int, int] = {}
        self._not_before = 0.0
        self._generation = 0
        self._clean = 0
        self._closed = False
        self._stats = dict(admitted=0, settled=0, peak_inflight=0, refusals=0, failed=0, cancelled_waits=0)

    async def acquire(self) -> int:
        ticket = next(self._tickets)
        with self._lock:
            if self._closed:
                raise RuntimeError("This agent team's request admission is closed")
            self._waiting.append(ticket)
        admitted = False
        try:
            while True:
                with self._lock:
                    if self._closed:
                        raise RuntimeError("This agent team's request admission is closed")
                    now = time.monotonic()
                    if self._waiting[0] == ticket and len(self._active) < self.limit and now >= self._not_before:
                        self._waiting.popleft()
                        self._active[ticket] = self._generation
                        self._not_before = now + self.launch_interval
                        self._stats["admitted"] += 1
                        self._stats["peak_inflight"] = max(self._stats["peak_inflight"], len(self._active))
                        admitted = True
                        return ticket
                await asyncio.sleep(0.02)
        finally:
            if not admitted:
                with self._lock:
                    self._waiting.remove(ticket)
                    self._stats["cancelled_waits"] += 1

    def release(self, ticket: int, *, status: int = 0, retry_after: float = 0.0, complete: bool = False) -> None:
        with self._lock:
            generation = self._active.pop(ticket, None)
            if generation is None:
                return
            self._stats["settled"] += 1
            if status == 429:
                self._stats["refusals"] += 1
                now = time.monotonic()
                self._not_before = max(self._not_before, now + max(0.0, retry_after))
                if generation == self._generation:
                    self.limit = max(1, self.limit // 2)
                    self._generation += 1
                    self._clean = 0
            elif complete and 200 <= status < 300:
                if generation != self._generation:
                    return
                self._clean += 1
                if self._clean >= 8 and self.limit < self.ceiling:
                    self.limit += 1
                    self._clean = 0
            else:
                self._stats["failed"] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "ceiling": self.ceiling,
                "limit": self.limit,
                "inflight": len(self._active),
                "waiting": len(self._waiting),
                "closed": self._closed,
                "launch_interval_s": self.launch_interval,
            }

    def close(self) -> None:
        """Reject future/queued sends; the team must also cancel its owned loops."""
        with self._lock:
            self._closed = True


@asynccontextmanager
async def admitted_stream(owner: Any, client: Any, method: str, url: str, *, attempt_state=None, **kwargs: Any):
    """Preserve client.stream behavior and hold admission until its body closes."""
    admission = getattr(owner, "_request_admission", None)
    if admission is not None and callable(getattr(admission, "for_model", None)):
        admission = admission.for_model(owner.config)
    if admission is None:
        if attempt_state is not None:
            attempt_state["started"] = True
        async with client.stream(method, url, **kwargs) as response:
            yield response
        return
    ticket = await admission.acquire()
    status, retry_after, complete = 0, 0.0, False
    try:
        if attempt_state is not None:
            attempt_state["started"] = True
        async with _drain_stream_close(client.stream(method, url, **kwargs)) as response:
            status = response.status_code
            if status == 429:
                retry_after = retry_after_seconds(response.headers, max_retry_after_s=300.0)
                if retry_after is None:
                    retry_after = 20.0
            yield response
        complete = True
    finally:
        admission.release(ticket, status=status, retry_after=retry_after, complete=complete)


@asynccontextmanager
async def _drain_stream_close(context):
    """Repeated parent cancellation must not abandon a live response body."""
    response = await context.__aenter__()
    try:
        yield response
    finally:
        close = asyncio.create_task(context.__aexit__(*sys.exc_info()))
        cancellation = None
        while True:
            try:
                await asyncio.shield(close)
                break
            except asyncio.CancelledError as exc:
                if close.done():
                    raise
                cancellation = exc
        if cancellation is not None:
            raise cancellation


async def finish_admitted_attempt(owner: Any, lease: Any, attempt_state: dict[str, bool]) -> None:
    """An attempt cancelled while queued sent nothing and must release its budget."""
    if getattr(owner, "_request_admission", None) is None or attempt_state["started"]:
        await owner.finish_budget_attempt(lease)
        return
    release = asyncio.create_task(owner.abort_budget_attempt(lease))
    try:
        await asyncio.shield(release)
    except asyncio.CancelledError:
        await release
        raise
