from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from .models import AutonomyError, AutonomyTransientError, Job
from .agents import PlannerAgent, ReviewerAgent
from .executor import ExecutorAgent
from .scheduler import EngineTiming, compute_next_run


JobHandler = Callable[[Job], Awaitable[Dict[str, Any]]]
log = logging.getLogger(__name__)


class AutonomyEngine:
    """Autonomy background runner.

    - Claims due jobs from the store
    - Applies policy gates (deny / require approval)
    - Runs handlers
    - Persists result/error and schedules retries/next-run
    """

    def __init__(
        self,
        *,
        store,
        policy,
        chat_adapter=None,
        timing: Optional[EngineTiming] = None,
        max_concurrency: int = 4,
        worker_id: Optional[str] = None,
    ):
        self.store = store
        self.policy = policy
        self.chat_adapter = chat_adapter
        self.timing = timing or EngineTiming()

        self._worker_id = worker_id or f"autonomy-{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._sema = asyncio.Semaphore(max(1, int(max_concurrency)))
        self._running = False

        self._handlers: Dict[str, JobHandler] = {}
        self._register_builtin_handlers()

    # -------- public API --------
    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def is_running(self) -> bool:
        return self._running

    def register_handler(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    def wake_up(self) -> None:
        # Safe to call from non-async contexts.
        if not self._stop.is_set():
            self._wake.set()

    # Backwards-compat alias
    def wakeup(self) -> None:
        self.wake_up()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())
        self._running = True
        self.wake_up()

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._wake.set()
        await self._task
        self._task = None
        self._running = False

    # -------- internal loop --------
    async def _run_loop(self) -> None:
        # Periodic recovery for stuck locks:
        # - if Thomas crashes mid-run, locked jobs should be re-queued
        while not self._stop.is_set():
            try:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self.timing.scheduler_tick_s)
                except asyncio.TimeoutError:
                    pass
                self._wake.clear()

                now = datetime.now(timezone.utc)
                # Requeue any stale running jobs with expired locks.
                try:
                    self.store.reap_stale_running(now=now)
                except Exception as e:
                    # Non-fatal; keep the engine alive.
                    log.debug("Failed to reap stale running jobs: %s", e)

                # Claim due jobs (up to remaining capacity)
                claimed = self.store.claim_due_jobs(
                    worker_id=self._worker_id,
                    limit=self.timing.claim_batch,
                    now=now,
                    lock_ttl_s=self.timing.lock_ttl_s,
                )

                if not claimed:
                    continue

                # Each item: (Job, lock_token) – token currently unused but reserved for future lock extension.
                tasks = []
                for item in claimed:
                    if isinstance(item, tuple):
                        job = item[0]
                    else:
                        job = item
                    tasks.append(asyncio.create_task(self._run_job(job)))

                # Let tasks run concurrently but don't await forever on a single tick.
                # We'll await completion of this batch; new jobs will be picked up on the next tick / wakeup.
                await asyncio.gather(*tasks)

            except Exception:
                # Don't let the worker die silently.
                traceback.print_exc()

        self._running = False

    def _register_builtin_handlers(self) -> None:
        self.register_handler("reminder", self._handle_reminder)
        self.register_handler("daily_briefing", self._handle_daily_briefing)
        self.register_handler("autonomy_task", self._handle_autonomy_task)

    # -------- core execution --------
    async def _run_job(self, job: Job) -> None:
        async with self._sema:
            # Reload a fresh copy (job may have been updated after claim)
            try:
                job = self.store.get_job(job.id)
            except Exception:
                return

            if job.cancelled or job.status in ("cancelled",):
                return

            # Policy gate
            decision = self.policy.decision_for_job(kind=job.kind, risk_class=job.risk_class)
            if not decision.allowed:
                err = {"type": "policy_denied", "reason": decision.reason, "transient": False}
                self.store.set_job_status(job.id, "dead", error=err, attempts=job.attempts, lock_clear=True)
                self.store.add_audit(job.id, "job.policy_denied", "policy", err)
                return

            if decision.requires_approval and not job.approved:
                # Create approval request if none pending.
                pending = self.store.list_job_approvals(job.id, status="pending")
                if not pending:
                    action = {
                        "job_id": job.id,
                        "name": job.name,
                        "kind": job.kind,
                        "risk_class": job.risk_class,
                        "payload_preview": job.payload,
                    }
                    self.store.create_approval(job_id=job.id, action=action, risk_class=job.risk_class)
                self.store.set_job_status(job.id, "awaiting_approval", requires_approval=True, lock_clear=True)
                return

            handler = self._handlers.get(job.kind)
            if handler is None:
                err = {"type": "unknown_kind", "message": f"no handler for kind '{job.kind}'", "transient": False}
                self.store.set_job_status(job.id, "dead", error=err, attempts=job.attempts, lock_clear=True)
                self.store.add_audit(job.id, "job.failed", "engine", err)
                return

            # Execute
            try:
                result = await handler(job)
            except AutonomyTransientError as e:
                await self._handle_failure(job, e, transient=True)
                return
            except AutonomyError as e:
                await self._handle_failure(job, e, transient=False)
                return
            except Exception as e:
                # Default to transient-ish: many exceptions are environmental.
                await self._handle_failure(job, e, transient=True)
                return

            await self._handle_success(job, result)

    async def _handle_success(self, job: Job, result: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        self.store.add_audit(job.id, "job.succeeded", "engine", {"result": result})

        if job.schedule:
            next_run = compute_next_run(job.schedule, now)
            # "once" schedules return None after they have elapsed; treat that as terminal.
            if next_run is None:
                self.store.set_job_status(job.id, "succeeded", result=result, error=None, attempts=0, lock_clear=True)
            else:
                self.store.set_job_status(
                    job.id,
                    "queued",
                    result=result,
                    error=None,
                    attempts=0,
                    next_run_at=next_run,
                    lock_clear=True,
                )
        else:
            self.store.set_job_status(job.id, "succeeded", result=result, error=None, attempts=0, lock_clear=True)

    async def _handle_failure(self, job: Job, exc: Exception, *, transient: bool) -> None:
        now = datetime.now(timezone.utc)
        attempts = int(job.attempts or 0) + 1

        tb = traceback.format_exc(limit=30)
        err = {
            "type": exc.__class__.__name__,
            "message": str(exc),
            "transient": bool(transient),
            "traceback": tb,
        }

        # Retry loop for transient failures
        if transient and attempts < job.retry_policy.max_attempts:
            delay_s = job.retry_policy.compute_delay(attempts)
            next_run = now + timedelta(seconds=delay_s)
            self.store.add_audit(job.id, "job.retry_scheduled", "engine", {"attempts": attempts, "delay_s": delay_s, "error": err})
            self.store.set_job_status(job.id, "queued", error=err, attempts=attempts, next_run_at=next_run, lock_clear=True)
            return

        # Terminal failure
        self.store.add_audit(job.id, "job.failed_terminal", "engine", {"attempts": attempts, "error": err})

        if job.schedule:
            # For recurring jobs, don't brick the schedule. Record last error and schedule the next run.
            next_run = compute_next_run(job.schedule, now)
            if next_run is None:
                self.store.set_job_status(job.id, "dead", error=err, attempts=attempts, lock_clear=True)
            else:
                self.store.set_job_status(job.id, "queued", error=err, attempts=0, next_run_at=next_run, lock_clear=True)
            return

        self.store.set_job_status(job.id, "dead", error=err, attempts=attempts, lock_clear=True)

    # -------- built-in handlers --------
    async def _handle_reminder(self, job: Job) -> Dict[str, Any]:
        msg = str(job.payload.get("message") or job.payload.get("text") or "").strip()
        if not msg:
            msg = f"Reminder: {job.name}"
        self.store.add_message(session_id=job.session_id, level="info", text=msg)
        return {"sent": True, "message": msg}

    async def _handle_daily_briefing(self, job: Job) -> Dict[str, Any]:
        prompt = str(job.payload.get("prompt") or "").strip()
        if not prompt:
            prompt = "Generate a concise daily briefing with: priorities, risks, and next actions."

        content: Dict[str, Any] = {"prompt": prompt, "generated": False}
        if self.chat_adapter is not None:
            try:
                content = await self.chat_adapter.generate_json(
                    system_prompt="You generate structured daily briefings for a personal assistant. Output JSON only.",
                    user_prompt=prompt,
                    session_id=job.session_id,
                    schema_hint={
                        "summary": "string",
                        "priorities": [{"title": "string", "why": "string"}],
                        "risks": [{"title": "string", "mitigation": "string"}],
                        "next_actions": [{"title": "string", "eta": "string"}],
                    },
                )
                content["generated"] = True
            except Exception as e:
                content = {"summary": f"(briefing generation failed: {e})", "generated": False}

        bid = self.store.add_briefing(content=content)
        self.store.add_message(session_id=job.session_id, level="briefing", text=f"Daily briefing created ({bid}).")
        return {"briefing_id": bid, "content": content}

    async def _handle_autonomy_task(self, job: Job) -> Dict[str, Any]:
        """Planner → reviewer → executor pipeline.

        The planner is LLM-backed (via the provided chat_adapter) and must output STRICT JSON.
        The reviewer is deterministic and flags obvious dangers.
        The executor enqueues validated actions as child jobs.
        """
        goal = str(job.payload.get("goal") or job.payload.get("task") or job.payload.get("prompt") or "").strip()
        if not goal:
            raise AutonomyError("autonomy_task requires payload.goal")

        context = str(job.payload.get("context") or "").strip()

        if self.chat_adapter is None:
            raise AutonomyTransientError("no chat adapter configured for autonomy_task")

        planner = PlannerAgent(self.chat_adapter)
        plan = await planner.plan(goal=goal, context=context, session_id=job.session_id)

        reviewer = ReviewerAgent()
        ok, problems = reviewer.review(plan)
        self.store.add_audit(job.id, "autonomy_task.plan", "planner", {"plan": plan, "review_ok": ok, "problems": problems})

        if problems:
            self.store.add_message(
                session_id=job.session_id,
                level="warn",
                text=f"Autonomy plan reviewer flags: {', '.join(problems[:5])}",
            )

        executor = ExecutorAgent(store=self.store, policy=self.policy, parent_id=job.id, session_id=job.session_id)
        outcome = executor.enqueue_plan(plan)

        self.store.add_audit(job.id, "autonomy_task.spawned_children", "executor", outcome)
        self.wake_up()
        return {"goal": goal, **outcome}
