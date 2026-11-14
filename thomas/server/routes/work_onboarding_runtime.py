"""Transactional bridge from Work onboarding history to a durable job."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from thomas.chat.session_store import SessionUnreadable
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE
from thomas.work import WorkConflictError, WorkDependencyUnavailableError, WorkStore
from thomas.work.lanes.onboarding_gate import evaluate_creation
from thomas.work.lanes.proposals import GateProposalStore
from thomas.work.lanes.stats import GateStatsStore, close_run
from thomas.work.lanes.store import lane_data_dir


class WorkOnboardingRuntime:
    """Serialize each idempotent cross-store job creation transaction."""

    def __init__(
        self,
        store: WorkStore,
        *,
        stats_store: GateStatsStore | None = None,
        proposal_store: GateProposalStore | None = None,
    ) -> None:
        self._store = store
        self._locks: dict[str, asyncio.Lock] = {}
        # Derived from the store this runtime serves, so lane data follows its
        # own WorkStore instead of a fixed home directory that every test would
        # write into. Callers may still inject to share instances with the routes.
        lane_dir = lane_data_dir(store.root_path)
        self._stats = stats_store or GateStatsStore(path=lane_dir / "lane_stats.json")
        self._proposals = proposal_store or GateProposalStore(path=lane_dir / "lane_proposals.json")

    def _existing_job(self, app_id: str, idempotency_key: str) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        return next(
            (
                row
                for row in self._store.list_jobs(app_id, include_archived=True)
                if isinstance(row.get("metadata"), dict) and row["metadata"].get("onboarding_key") == idempotency_key
            ),
            None,
        )

    def _lane_checked_payload(self, app_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Refuse a job whose onboarding is still collecting answers.

        The onboarding phase machine in ``WorkStore.update_onboarding`` already
        owns every content rule; it simply guards a route this one does not take.
        A waived creation still happens, but the skip is written onto the job.
        """

        onboarding = self._store.get_app(app_id).get("onboarding")
        decision, lane = evaluate_creation(onboarding, payload=payload)
        if lane is not None:
            # The run boundary. Every evaluation is real evidence about these
            # gates, so it is recorded whether the job was allowed, refused or
            # waived -- a gate that only ever gets counted when it passes would
            # look quieter than it is. close_run never raises.
            close_run(
                lane,
                waived_gate_ids=list(decision.failed_gate_ids) if decision.waived else [],
                stats_store=self._stats,
                proposal_store=self._proposals,
            )
        if not decision.allowed:
            raise WorkConflictError(decision.reason)
        if not decision.waived:
            return payload
        checked = dict(payload)
        metadata = dict(checked.get("metadata") or {})
        metadata.update(decision.to_metadata())
        checked["metadata"] = metadata
        return checked

    async def create_job(
        self,
        app: web.Application,
        app_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        payload = self._lane_checked_payload(app_id, payload)
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key:
            return self._store.create_job_with_status(app_id, payload)
        lock = self._locks.setdefault(f"{app_id}:{idempotency_key}", asyncio.Lock())
        async with lock:
            return await self._create_locked(app, app_id, payload, idempotency_key)

    async def _create_locked(
        self,
        app: web.Application,
        app_id: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        history_session_id = str(payload.get("history_session_id") or "").strip()
        existing_job = self._existing_job(app_id, idempotency_key)
        session_store = None
        conversation = None
        meta = None
        if history_session_id:
            session_store = app.get(APP_SESSION_STORE)
            if session_store is None:
                raise WorkDependencyUnavailableError("Work onboarding history could not be transferred")
            try:
                conversation = await session_store.load(history_session_id)
                meta = await session_store.load_meta(history_session_id)
            except SessionUnreadable as exc:
                raise WorkDependencyUnavailableError("Work onboarding history could not be read right now") from exc
            if conversation is None or meta is None:
                raise WorkConflictError("Work onboarding history was not found")
            prior_context = str(getattr(meta, "context_id", "") or "")
            transferred_context = f"{app_id}:{existing_job['id']}" if existing_job else ""
            if str(getattr(meta, "surface_mode", "") or "") != "work" or not (
                prior_context == app_id
                or prior_context.startswith(f"{app_id}:onboarding:")
                or (transferred_context and prior_context == transferred_context)
            ):
                raise WorkConflictError("history_session_id must belong to this Work app's onboarding")

        job, created = self._store.create_job_with_status(app_id, payload)
        if history_session_id and created:
            meta.surface_mode = "work"
            meta.context_id = f"{app_id}:{job['id']}"
            if not await session_store.save(history_session_id, conversation, meta, force=True):
                self._store.rollback_failed_job_creation(app_id, str(job["id"]))
                raise WorkDependencyUnavailableError("Work onboarding history could not be transferred")
        return job, created


__all__ = ["WorkOnboardingRuntime"]
