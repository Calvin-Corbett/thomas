from __future__ import annotations

import asyncio
import json
import sys
import traceback
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from thomas.core.autonomy import clamp_autonomy_level
from thomas.core.config import ModelConfig

from .agents import PlannerAgent, ReviewerAgent
from .executor import ExecutorAgent
from .media_agents import (
    MediaAgentError,
    MediaAgentTransientError,
    OpenAICompatMediaClient,
    _extract_text,
    _extract_video_meta,
)
from .mode_policy import apply_workflow_mode_policy
from .models import AutonomyError, AutonomyTransientError, Job
from .nl_workflow_compiler import compile_nl_workflow_payload
from .scheduler import EngineTiming, compute_next_run
from .workflows import WorkflowExecutionError, WorkflowRunner, summarize_workflow_telemetry

JobHandler = Callable[[Job], Awaitable[dict[str, Any]]]


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
        timing: EngineTiming | None = None,
        max_concurrency: int = 4,
        worker_id: str | None = None,
        model_resolver: Callable[[str | None], ModelConfig] | None = None,
        artifact_root: str | None = None,
    ):
        self.store = store
        self.policy = policy
        self.chat_adapter = chat_adapter
        self.timing = timing or EngineTiming()
        self._model_resolver = model_resolver
        self._artifact_root = Path(artifact_root or Path("runtime") / "autonomy" / "artifacts").expanduser()
        self._artifact_root.mkdir(parents=True, exist_ok=True)

        self._worker_id = worker_id or f"autonomy-{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._sema = asyncio.Semaphore(max(1, int(max_concurrency)))
        self._running = False

        self._handlers: dict[str, JobHandler] = {}
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
                except (ConnectionError, TimeoutError):
                    # Non-fatal; keep the engine alive.
                    pass

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

            except Exception:  # REVIEWED: async context
                # Don't let the worker die silently.
                traceback.print_exc()

        self._running = False

    def _register_builtin_handlers(self) -> None:
        self.register_handler("reminder", self._handle_reminder)
        self.register_handler("daily_briefing", self._handle_daily_briefing)
        self.register_handler("autonomy_task", self._handle_autonomy_task)
        self.register_handler("workflow_task", self._handle_workflow_task)
        self.register_handler("video_generation", self._handle_video_generation)
        self.register_handler("speech_transcription", self._handle_speech_transcription)
        self.register_handler("speech_synthesis", self._handle_speech_synthesis)
        self.register_handler("evolve_session", self._handle_evolve_session)

    # -------- core execution --------
    async def _run_job(self, job: Job) -> None:
        async with self._sema:
            # Reload a fresh copy (job may have been updated after claim)
            try:
                job = self.store.get_job(job.id)
            except Exception:  # REVIEWED: broad catch
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

            if job.requires_approval and not decision.requires_approval:
                self.store.set_job_status(
                    job.id,
                    "running",
                    approved=True,
                    requires_approval=False,
                    lock_clear=False,
                )
                job.approved = True
            elif job.requires_approval and decision.requires_approval and not job.approved:
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

    async def _handle_success(self, job: Job, result: dict[str, Any]) -> None:
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
            self.store.add_audit(
                job.id, "job.retry_scheduled", "engine", {"attempts": attempts, "delay_s": delay_s, "error": err}
            )
            self.store.set_job_status(
                job.id, "queued", error=err, attempts=attempts, next_run_at=next_run, lock_clear=True
            )
            return

        # Terminal failure
        self.store.add_audit(job.id, "job.failed_terminal", "engine", {"attempts": attempts, "error": err})

        if job.schedule:
            # For recurring jobs, don't brick the schedule. Record last error and schedule the next run.
            next_run = compute_next_run(job.schedule, now)
            if next_run is None:
                self.store.set_job_status(job.id, "dead", error=err, attempts=attempts, lock_clear=True)
            else:
                self.store.set_job_status(
                    job.id, "queued", error=err, attempts=0, next_run_at=next_run, lock_clear=True
                )
            return

        self.store.set_job_status(job.id, "dead", error=err, attempts=attempts, lock_clear=True)

    # -------- built-in handlers --------
    def _resolve_model_config(self, profile: str | None) -> ModelConfig:
        if callable(self._model_resolver):
            try:
                cfg = self._model_resolver(profile)
            except TypeError:
                cfg = self._model_resolver(None)
            if isinstance(cfg, ModelConfig):
                return cfg
        return ModelConfig(name=str(profile or "local"))

    @staticmethod
    def _to_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
        try:
            iv = int(value)
        except (ValueError, TypeError):
            iv = int(default)
        if iv < minimum:
            return minimum
        if iv > maximum:
            return maximum
        return iv

    @staticmethod
    def _to_optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except Exception as e:
            raise AutonomyError("payload.speed must be a number") from e

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, Mapping):
            return dict(value)
        return {}

    def _workflow_policy_for_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        autonomy_level = clamp_autonomy_level(payload.get("autonomy_level", 3), default=3)
        # Lower autonomy levels constrain fan-out for orchestrated workflows.
        worker_cap = {1: 1, 2: 2, 3: 3, 4: 4}.get(int(autonomy_level), 3)
        requested_workers = payload.get("worker_count")
        worker_count = self._to_int(requested_workers, default=worker_cap, minimum=1, maximum=8)
        worker_count = min(worker_count, worker_cap)
        return {
            "autonomy_level": int(autonomy_level),
            "worker_count": int(worker_count),
        }

    async def _handle_workflow_task(self, job: Job) -> dict[str, Any]:
        if self.chat_adapter is None:
            raise AutonomyTransientError("no chat adapter configured for workflow_task")

        raw_payload = self._as_dict(job.payload)
        payload, compile_meta = compile_nl_workflow_payload(raw_payload)
        payload, mode_policy = apply_workflow_mode_policy(payload, compile_meta=compile_meta)
        workflow = str(payload.get("workflow") or payload.get("pattern") or "chain").strip().lower()
        policy = self._workflow_policy_for_payload(payload)

        # Apply policy defaults to orchestrator fan-out when not explicitly bounded.
        if workflow in {"orchestrator_worker", "orchestrator-workers", "orchestrate"}:
            payload["worker_count"] = int(policy["worker_count"])

        runner = WorkflowRunner(
            chat_adapter=self.chat_adapter,
            session_id=job.session_id,
            default_profile=str(payload.get("profile") or "").strip() or None,
            execution_context=payload,
        )
        try:
            result = await runner.run(payload)
        except WorkflowExecutionError as e:
            raise AutonomyError(str(e)) from e

        telemetry = summarize_workflow_telemetry(result)
        out = self._as_dict(result)
        out["telemetry"] = telemetry
        out["workflow_policy"] = policy
        out["workflow_mode_policy"] = mode_policy
        if isinstance(compile_meta, dict):
            out["workflow_compile"] = compile_meta
        return out

    async def _handle_evolve_session(self, job: Job) -> dict[str, Any]:
        payload = self._as_dict(job.payload)
        goal = str(payload.get("goal") or payload.get("prompt") or "").strip()
        profile = str(payload.get("profile") or "").strip()
        passes = self._to_int(payload.get("passes"), default=1, minimum=1, maximum=8)
        timeout_seconds = self._to_int(payload.get("timeout_seconds"), default=1800, minimum=60, maximum=7200)
        promote_on_pass = bool(payload.get("promote_on_pass"))

        command = [
            sys.executable,
            "-m",
            "thomas",
            "evolve",
            "run",
            "--json",
            "--passes",
            str(passes),
            "--timeout-seconds",
            str(timeout_seconds),
        ]
        if goal:
            command.extend(["--goal", goal])
        if profile:
            command.extend(["--profile", profile])
        if promote_on_pass:
            command.append("--promote-on-pass")

        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds + 120)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise AutonomyError(f"evolve_session timed out after {timeout_seconds}s") from exc

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            raise AutonomyError(stderr_text or stdout_text or f"evolve_session exited with code {proc.returncode}")
        try:
            result = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            raise AutonomyError("evolve_session produced invalid JSON") from exc

        session = self._as_dict(result.get("session"))
        session_id = str(session.get("session_id") or "").strip()
        status = str(session.get("status") or "").strip() or "completed"
        changed_count = len(session.get("changed_files") or [])
        noun = "file" if changed_count == 1 else "files"
        msg = f"Evolve session {session_id or job.id} finished: {status} ({changed_count} changed {noun})."
        self.store.add_message(session_id=job.session_id, level="info", text=msg)
        return result

    def _media_client_for_job(self, job: Job) -> OpenAICompatMediaClient:
        payload = self._as_dict(job.payload)
        profile = str(payload.get("profile") or "").strip() or None
        cfg = self._resolve_model_config(profile)
        return OpenAICompatMediaClient(cfg)

    def _artifact_output_path(self, job_id: str, *, audio_format: str) -> Path:
        ext = str(audio_format or "mp3").strip().lower() or "mp3"
        ext = ext if ext.startswith(".") else f".{ext}"
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        return (self._artifact_root / f"{job_id}{ext}").resolve()

    async def _handle_video_generation(self, job: Job) -> dict[str, Any]:
        payload = self._as_dict(job.payload)
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise AutonomyError("video_generation requires payload.prompt")

        duration_seconds = payload.get("duration_seconds")
        if duration_seconds is not None:
            try:
                duration_seconds = int(duration_seconds)
            except Exception as e:
                raise AutonomyError("video_generation payload.duration_seconds must be an integer") from e

        client = self._media_client_for_job(job)
        try:
            raw = await client.generate_video(
                prompt=prompt,
                model=str(payload.get("model") or "").strip() or None,
                endpoint_paths=payload.get("endpoint_paths") or payload.get("endpoint_path"),
                image_url=str(payload.get("image_url") or "").strip() or None,
                duration_seconds=duration_seconds,
                size=str(payload.get("size") or "").strip() or None,
                extra=self._as_dict(payload.get("extra")),
            )
            parsed = self._as_dict(raw)
            status, video_id, video_url = _extract_video_meta(parsed)
            return {
                "video_id": video_id,
                "status": status,
                "url": video_url,
                "provider_response": parsed,
            }
        except MediaAgentTransientError as e:
            raise AutonomyTransientError(str(e)) from e
        except MediaAgentError as e:
            raise AutonomyError(str(e)) from e
        finally:
            try:
                await client.aclose()
            except (ConnectionError, TimeoutError):
                pass

    async def _handle_speech_transcription(self, job: Job) -> dict[str, Any]:
        payload = self._as_dict(job.payload)
        audio_path = str(payload.get("audio_path") or "").strip()
        if not audio_path:
            raise AutonomyError("speech_transcription requires payload.audio_path")

        client = self._media_client_for_job(job)
        try:
            raw = await client.transcribe_audio(
                audio_path=audio_path,
                model=str(payload.get("model") or "").strip() or None,
                endpoint_path=str(payload.get("endpoint_path") or "/audio/transcriptions").strip(),
                language=str(payload.get("language") or "").strip() or None,
                prompt=str(payload.get("prompt") or "").strip() or None,
                response_format=str(payload.get("response_format") or "").strip() or None,
                extra=self._as_dict(payload.get("extra")),
            )
            parsed = self._as_dict(raw)
            text = _extract_text(parsed)
            return {
                "text": text,
                "provider_response": parsed,
            }
        except MediaAgentTransientError as e:
            raise AutonomyTransientError(str(e)) from e
        except MediaAgentError as e:
            raise AutonomyError(str(e)) from e
        finally:
            try:
                await client.aclose()
            except (ConnectionError, TimeoutError):
                pass

    async def _handle_speech_synthesis(self, job: Job) -> dict[str, Any]:
        payload = self._as_dict(job.payload)
        text = str(payload.get("text") or payload.get("input") or "").strip()
        if not text:
            raise AutonomyError("speech_synthesis requires payload.text")

        audio_format = str(payload.get("audio_format") or payload.get("format") or "mp3").strip().lower() or "mp3"
        output_path_raw = str(payload.get("output_path") or "").strip()
        if output_path_raw:
            output_path = Path(output_path_raw).expanduser()
        else:
            output_path = self._artifact_output_path(job.id, audio_format=audio_format)

        client = self._media_client_for_job(job)
        try:
            raw = await client.synthesize_speech(
                text=text,
                voice=str(payload.get("voice") or "alloy").strip() or "alloy",
                model=str(payload.get("model") or "").strip() or None,
                endpoint_path=str(payload.get("endpoint_path") or "/audio/speech").strip(),
                audio_format=audio_format,
                speed=self._to_optional_float(payload.get("speed")),
                output_path=output_path,
                extra=self._as_dict(payload.get("extra")),
            )
            parsed = self._as_dict(raw)
            return {
                "output_path": str(parsed.get("output_path") or output_path),
                "size_bytes": int(parsed.get("size_bytes") or 0),
                "provider_response": parsed,
            }
        except MediaAgentTransientError as e:
            raise AutonomyTransientError(str(e)) from e
        except MediaAgentError as e:
            raise AutonomyError(str(e)) from e
        finally:
            try:
                await client.aclose()
            except (ConnectionError, TimeoutError):
                pass

    async def _handle_reminder(self, job: Job) -> dict[str, Any]:
        msg = str(job.payload.get("message") or job.payload.get("text") or "").strip()
        if not msg:
            msg = f"Reminder: {job.name}"
        self.store.add_message(session_id=job.session_id, level="info", text=msg)
        return {"sent": True, "message": msg}

    async def _handle_daily_briefing(self, job: Job) -> dict[str, Any]:
        prompt = str(job.payload.get("prompt") or "").strip()
        if not prompt:
            prompt = "Generate a concise daily briefing with: priorities, risks, and next actions."

        content: dict[str, Any] = {"prompt": prompt, "generated": False}
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

    async def _handle_autonomy_task(self, job: Job) -> dict[str, Any]:
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
        self.store.add_audit(
            job.id, "autonomy_task.plan", "planner", {"plan": plan, "review_ok": ok, "problems": problems}
        )

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
