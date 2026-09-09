"""Transactional bridge from Work onboarding history to a durable job."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE
from thomas.work import WorkConflictError, WorkDependencyUnavailableError, WorkStore


class WorkOnboardingRuntime:
    """Serialize each idempotent cross-store job creation transaction."""

    def __init__(self, store: WorkStore) -> None:
        self._store = store
        self._locks: dict[str, asyncio.Lock] = {}

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

    async def create_job(
        self,
        app: web.Application,
        app_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
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
            conversation = await session_store.load(history_session_id)
            meta = await session_store.load_meta(history_session_id)
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
