"""Mission benchmark route registration."""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from .mission_runtime_views import _collect_benchmark_runs, _run_dir_for_id
from .mission_support import (
    _ARTIFACT_CONTENT_TYPES,
    _BENCHMARK_ARTIFACTS,
    _MAX_BENCH_JOBS,
    _MAX_BENCH_LOG_LINES,
    _default_task_pack_key,
    _discover_task_packs,
    _iso_to_epoch,
    _utc_iso_now,
)


def register_mission_benchmark_routes(
    app: web.Application,
    *,
    repo_root: Path,
    runs_dir: Path,
    require_api_access: Callable[[web.Request], None],
    benchmark_jobs: dict[str, dict[str, Any]],
    benchmark_tasks: dict[str, asyncio.Task[Any]],
    benchmark_procs: dict[str, asyncio.subprocess.Process],
    benchmark_lock: asyncio.Lock,
) -> None:
    async def api_benchmark_runs(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            limit = int(str(request.query.get("limit") or "40").strip())
        except Exception:
            limit = 40
        limit = max(1, min(limit, 200))
        runs = _collect_benchmark_runs(runs_dir, limit=limit)
        return web.json_response(
            {
                "ok": True,
                "runs_dir": str(runs_dir),
                "runs": runs,
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_benchmark_packs(request: web.Request) -> web.Response:
        require_api_access(request)
        packs_map = _discover_task_packs(repo_root)
        default_key = _default_task_pack_key(packs_map)
        safe_keys = (
            "key",
            "id",
            "name",
            "version",
            "description",
            "protocol",
            "task_count",
            "duration_budget_seconds",
            "tasks",
            "file_name",
        )
        packs = sorted(
            [{k: v.get(k) for k in safe_keys} for v in packs_map.values()],
            key=lambda row: (0 if str(row.get("key") or "") == default_key else 1, str(row.get("name") or "")),
        )
        return web.json_response(
            {
                "ok": True,
                "default_pack": default_key,
                "packs": packs,
            },
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_benchmark_artifact(request: web.Request) -> web.Response:
        require_api_access(request)
        run_id = str(request.match_info.get("run_id") or "").strip()
        artifact = str(request.match_info.get("artifact") or "").strip()
        if artifact not in _BENCHMARK_ARTIFACTS:
            raise web.HTTPNotFound(text="artifact not found")
        run_dir = _run_dir_for_id(runs_dir, run_id)
        target = run_dir / artifact
        if not target.exists() or not target.is_file():
            raise web.HTTPNotFound(text="artifact not found")
        content_type = _ARTIFACT_CONTENT_TYPES.get(artifact, "application/octet-stream")
        return web.Response(
            body=target.read_bytes(),
            content_type=content_type,
            headers={"Cache-Control": "no-store"},
        )

    async def _run_benchmark_job(job_id: str, cmd: list[str], cwd: Path) -> None:
        log_tail: list[str] = []
        run_dir_text = ""
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async with benchmark_lock:
                job = benchmark_jobs.get(job_id)
                if job is not None:
                    job["status"] = "running"
                    job["started_at"] = _utc_iso_now()
                    job["pid"] = int(proc.pid or 0)
                    benchmark_procs[job_id] = proc

            if proc.stdout is not None:
                while True:
                    raw = await proc.stdout.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line:
                        log_tail.append(line)
                        if len(log_tail) > _MAX_BENCH_LOG_LINES:
                            log_tail = log_tail[-_MAX_BENCH_LOG_LINES:]
                        marker = "Agentic benchmark completed: "
                        if line.startswith(marker):
                            run_dir_text = line[len(marker) :].strip()

            exit_code = int(await proc.wait())
            resolved_run_dir = ""
            resolved_run_id = ""
            if run_dir_text:
                with contextlib.suppress(Exception):
                    resolved_path = Path(run_dir_text).resolve()
                    resolved_run_dir = str(resolved_path)
                    resolved_run_id = resolved_path.name

            async with benchmark_lock:
                job = benchmark_jobs.get(job_id)
                if job is not None:
                    job["status"] = "succeeded" if exit_code == 0 else "failed"
                    job["ended_at"] = _utc_iso_now()
                    job["exit_code"] = exit_code
                    job["run_dir"] = resolved_run_dir
                    job["run_id"] = resolved_run_id
                    job["log_tail"] = list(log_tail)
        except asyncio.CancelledError:
            if proc is not None and proc.returncode is None:
                with contextlib.suppress(Exception):
                    proc.terminate()
            async with benchmark_lock:
                job = benchmark_jobs.get(job_id)
                if job is not None:
                    job["status"] = "cancelled"
                    job["ended_at"] = _utc_iso_now()
                    job["log_tail"] = list(log_tail)
            raise
        except Exception as exc:
            async with benchmark_lock:
                job = benchmark_jobs.get(job_id)
                if job is not None:
                    job["status"] = "failed"
                    job["ended_at"] = _utc_iso_now()
                    job["error"] = f"{type(exc).__name__}: {exc}"
                    job["log_tail"] = list(log_tail)
        finally:
            async with benchmark_lock:
                benchmark_procs.pop(job_id, None)

    async def api_benchmark_run(request: web.Request) -> web.Response:
        require_api_access(request)
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        profile = str(payload.get("profile") or "local").strip() or "local"
        include_baseline = bool(payload.get("include_baseline", False))
        thomas_mode = str(payload.get("thomas_mode") or "fast").strip().lower()
        if thomas_mode not in {"fast", "auto", "thinking"}:
            thomas_mode = "fast"
        token_economy = str(payload.get("token_economy") or "optimal").strip().lower()
        if token_economy not in {"cheap", "optimal", "max"}:
            token_economy = "optimal"
        runner = str(payload.get("runner") or "embedded").strip().lower()
        if runner not in {"embedded", "api"}:
            runner = "embedded"

        packs_map = _discover_task_packs(repo_root)
        if not packs_map:
            raise web.HTTPNotFound(text="no benchmark task packs found")
        default_pack_key = _default_task_pack_key(packs_map)
        task_pack_key = str(payload.get("task_pack") or default_pack_key).strip().lower()
        aliases = {
            "quick": "smoke",
            "short": "smoke",
            "full": "local",
            "default": default_pack_key,
        }
        task_pack_key = aliases.get(task_pack_key, task_pack_key)
        pack_meta = packs_map.get(task_pack_key)
        if pack_meta is None:
            available = ", ".join(sorted(packs_map.keys()))
            raise web.HTTPBadRequest(text=f"unknown task_pack '{task_pack_key}'. available: {available}")
        task_pack_path = Path(str(pack_meta.get("path") or "")).resolve()
        if not task_pack_path.exists():
            raise web.HTTPNotFound(text=f"task pack not found: {task_pack_path}")

        max_iterations: int | None = None
        if payload.get("max_iterations") is not None:
            try:
                max_iterations = int(payload.get("max_iterations"))
            except Exception:
                raise web.HTTPBadRequest(text="invalid max_iterations")
            if max_iterations <= 0:
                raise web.HTTPBadRequest(text="invalid max_iterations")

        cmd = [
            sys.executable,
            "scripts/run_agentic_benchmark.py",
            "--profile",
            profile,
            "--task-pack",
            str(task_pack_path),
            "--thomas-runner",
            runner,
            "--thomas-mode",
            thomas_mode,
            "--thomas-token-economy",
            token_economy,
        ]
        if not include_baseline:
            cmd.append("--skip-baseline")
        if max_iterations is not None:
            cmd.extend(["--max-iterations", str(max_iterations)])

        job_id = secrets.token_urlsafe(8)
        created_at = _utc_iso_now()
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": created_at,
            "started_at": "",
            "ended_at": "",
            "pid": 0,
            "exit_code": None,
            "run_id": "",
            "run_dir": "",
            "error": "",
            "options": {
                "profile": profile,
                "task_pack": str(task_pack_path),
                "task_pack_key": task_pack_key,
                "task_pack_id": str(pack_meta.get("id") or ""),
                "task_pack_name": str(pack_meta.get("name") or ""),
                "task_count": int(pack_meta.get("task_count") or 0),
                "include_baseline": include_baseline,
                "thomas_mode": thomas_mode,
                "token_economy": token_economy,
                "runner": runner,
                "max_iterations": max_iterations,
            },
            "cmd": cmd,
            "log_tail": [],
        }

        task = asyncio.create_task(_run_benchmark_job(job_id, cmd, repo_root))
        async with benchmark_lock:
            benchmark_jobs[job_id] = job
            benchmark_tasks[job_id] = task
            if len(benchmark_jobs) > _MAX_BENCH_JOBS:
                stale = sorted(
                    benchmark_jobs.values(),
                    key=lambda j: _iso_to_epoch(j.get("created_at")),
                )[:-_MAX_BENCH_JOBS]
                for old in stale:
                    old_id = str(old.get("id") or "")
                    if not old_id or old_id == job_id:
                        continue
                    old_task = benchmark_tasks.get(old_id)
                    if old_task and not old_task.done():
                        continue
                    benchmark_jobs.pop(old_id, None)
                    benchmark_tasks.pop(old_id, None)
                    benchmark_procs.pop(old_id, None)

        return web.json_response(
            {"ok": True, "job": job},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_benchmark_jobs(request: web.Request) -> web.Response:
        require_api_access(request)
        async with benchmark_lock:
            jobs = [dict(v) for v in benchmark_jobs.values()]
        jobs.sort(key=lambda j: _iso_to_epoch(j.get("created_at")), reverse=True)
        return web.json_response(
            {"ok": True, "jobs": jobs},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_benchmark_job_cancel(request: web.Request) -> web.Response:
        require_api_access(request)
        job_id = str(request.match_info.get("job_id") or "").strip()
        if not job_id:
            raise web.HTTPBadRequest(text="missing job_id")

        async with benchmark_lock:
            job = benchmark_jobs.get(job_id)
            if job is None:
                raise web.HTTPNotFound(text="job not found")
            task = benchmark_tasks.get(job_id)
            proc = benchmark_procs.get(job_id)
            job["status"] = "cancel_requested"

        if proc is not None and proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.terminate()
        if task is not None and not task.done():
            task.cancel()

        return web.json_response({"ok": True, "job_id": job_id, "action": "cancel"})

    async def _cleanup_benchmark_jobs(_app: web.Application) -> None:
        async with benchmark_lock:
            tasks = list(benchmark_tasks.values())
            procs = list(benchmark_procs.values())
        for proc in procs:
            if proc.returncode is None:
                with contextlib.suppress(Exception):
                    proc.terminate()
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    app.on_cleanup.append(_cleanup_benchmark_jobs)
    app.router.add_get("/api/mission/benchmarks/packs", api_benchmark_packs)
    app.router.add_get("/api/mission/benchmarks/runs", api_benchmark_runs)
    app.router.add_get(
        "/api/mission/benchmarks/runs/{run_id}/artifact/{artifact}",
        api_benchmark_artifact,
    )
    app.router.add_post("/api/mission/benchmarks/run", api_benchmark_run)
    app.router.add_get("/api/mission/benchmarks/jobs", api_benchmark_jobs)
    app.router.add_post("/api/mission/benchmarks/jobs/{job_id}/cancel", api_benchmark_job_cancel)
