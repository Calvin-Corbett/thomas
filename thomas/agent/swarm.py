"""
Swarm Mode â€” multi-agent task graph orchestrator (stdlib-only).

What this is
- A small but *serious* multi-agent orchestrator designed to be integrated into Thomas.
- A Planner agent produces a strict JSON TaskGraph.
- Specialist subagents execute tasks concurrently when dependencies are satisfied.
- A Reviewer agent synthesizes the final answer.

Hard constraints honored
- stdlib-only for all new Python code
- Windows compatible
- Existing /api/chat behavior remains unchanged unless mode="swarm" routes here

Event contract
Every emitted event is NDJSON-friendly (a dict) and includes:
  - type, run_id, agent_id, task_id, seq, ts

Required event types (you can add more without breaking UI):
  - swarm_start
  - task_update
  - agent_text
  - agent_tool_start
  - agent_tool_result
  - swarm_done

Safety + concurrency
- Tool calls that mutate the filesystem are serialized through a global asyncio.Lock.
- Total parallel running tasks are limited via asyncio.Semaphore.
- Optional per-agent concurrency limits (useful when multiple tasks share one model backend).
- Clean cancellation: cancelling a run stops outstanding work, marks remaining tasks cancelled/blocked.

Integration note
This module avoids importing the rest of the Thomas codebase. The server layer should provide:
- subagents: dict[str, Subagent] (must include "planner" and "reviewer")
- tool_call callback OR tool registry + mutates_fs signal
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import json
import re
import time
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timezone
from typing import Any, Protocol

# -----------------------------
# Small utilities
# -----------------------------

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_\-]{0,31}$")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def _ensure_type(name: str, val: Any, typ: type) -> None:
    if not isinstance(val, typ):
        raise ValueError(f"{name} must be {typ.__name__}")


def _ensure_keys_exact(obj: dict[str, Any], *, allowed: Iterable[str], required: Iterable[str], where: str) -> None:
    allowed_set = set(allowed)
    required_set = set(required)
    keys = set(obj.keys())
    missing = sorted(required_set - keys)
    extra = sorted(keys - allowed_set)
    if missing:
        raise ValueError(f"{where}: missing required keys: {missing}")
    if extra:
        raise ValueError(f"{where}: unexpected keys: {extra}")


def _extract_first_json_object(s: str) -> dict[str, Any]:
    """
    Extract the first JSON object from an LLM response. This supports the reality that
    some models will wrap JSON in prose even when instructed not to.

    Strictness:
    - We only accept a JSON *object* at the top-level.
    - If parsing fails, we raise ValueError.

    This is intentionally not "smart" beyond finding the first balanced {...}.
    """
    if not isinstance(s, str) or not s.strip():
        raise ValueError("planner output is empty")

    in_str = False
    esc = False
    depth = 0
    start = None

    for i, ch in enumerate(s):
        if start is None:
            if ch == "{":
                start = i
                depth = 1
                in_str = False
                esc = False
            continue

        # we are inside object
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        else:
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = s[start : i + 1]
                    try:
                        obj = json.loads(chunk)
                    except Exception as e:
                        raise ValueError(f"failed to parse planner JSON: {e}") from e
                    if not isinstance(obj, dict):
                        raise ValueError("planner JSON must be an object")
                    return obj

    raise ValueError("unterminated JSON object in planner output")


def _guess_mutates_fs(tool_name: str, args: dict[str, Any]) -> bool:
    """
    Best-effort safety heuristic. Real Thomas integration should supply the correct
    mutates_fs signal from the tool registry.

    We still keep a conservative default because the requirement is explicit:
    FS-mutating tools must be serialized.
    """
    name = (tool_name or "").lower()
    mutating_keywords = (
        "write",
        "save",
        "edit",
        "patch",
        "apply",
        "delete",
        "remove",
        "rename",
        "mkdir",
        "rmdir",
        "move",
        "copy",
        "download",
        "upload",
        "git",
        "pip",
        "install",
        "shell",
        "cmd",
        "powershell",
    )
    if any(k in name for k in mutating_keywords):
        return True

    # args might contain file paths or commands
    arg_blob = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args)
    if any(k in arg_blob.lower() for k in ("rm ", "del ", "move ", "copy ", "git ", "pip ", "powershell", "cmd.exe")):
        return True

    return False


# -----------------------------
# Data model
# -----------------------------


class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"  # deps failed, so task will not run


@dataclasses.dataclass(frozen=True)
class Artifact:
    """
    Optional structured outputs produced by tasks.
    """

    kind: str  # e.g. "patch", "command", "note", "file"
    title: str
    content: str = ""
    path: str = ""
    meta: dict[str, Any] = dataclasses.field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Artifact:
        _ensure_type("artifact", d, dict)
        kind = d.get("kind", "")
        title = d.get("title", "")
        content = d.get("content", "")
        path = d.get("path", "")
        meta = d.get("meta", {})
        if not isinstance(kind, str) or not kind:
            raise ValueError("artifact.kind must be a non-empty string")
        if not isinstance(title, str) or not title:
            raise ValueError("artifact.title must be a non-empty string")
        if not isinstance(content, str):
            raise ValueError("artifact.content must be string")
        if not isinstance(path, str):
            raise ValueError("artifact.path must be string")
        if meta is None:
            meta = {}
        if not isinstance(meta, dict):
            raise ValueError("artifact.meta must be object")
        return Artifact(kind=kind, title=title, content=content, path=path, meta=meta)


@dataclasses.dataclass(frozen=True)
class TaskSpec:
    id: str
    title: str
    agent: str  # e.g. planner/coder/tester/reviewer
    deps: tuple[str, ...] = ()
    prompt: str = ""
    acceptance: tuple[str, ...] = ()
    meta: dict[str, Any] = dataclasses.field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> TaskSpec:
        if not isinstance(d, dict):
            raise ValueError("task must be an object")

        # strict keys (except meta which can contain anything)
        _ensure_keys_exact(
            d,
            allowed=("id", "title", "agent", "deps", "prompt", "acceptance", "meta"),
            required=("id", "title", "agent"),
            where="task",
        )

        tid = d["id"]
        title = d["title"]
        agent = d["agent"]
        deps = d.get("deps", [])
        prompt = d.get("prompt", "")
        acceptance = d.get("acceptance", [])
        meta = d.get("meta", {})

        if not isinstance(tid, str) or not _TASK_ID_RE.match(tid):
            raise ValueError("task.id must match /^[A-Za-z0-9][A-Za-z0-9_\\-]{0,63}$/")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("task.title must be a non-empty string")
        if not isinstance(agent, str) or not _AGENT_ID_RE.match(agent):
            raise ValueError("task.agent must match /^[a-z][a-z0-9_\\-]{0,31}$/")

        if deps is None:
            deps = []
        if not isinstance(deps, list) or not all(isinstance(x, str) for x in deps):
            raise ValueError("task.deps must be a list of strings")
        deps_t = tuple(deps)

        if not isinstance(prompt, str):
            raise ValueError("task.prompt must be string")

        if acceptance is None:
            acceptance = []
        if not isinstance(acceptance, list) or not all(isinstance(x, str) for x in acceptance):
            raise ValueError("task.acceptance must be a list of strings")
        acceptance_t = tuple(x.strip() for x in acceptance if x.strip())

        if meta is None:
            meta = {}
        if not isinstance(meta, dict):
            raise ValueError("task.meta must be an object")

        return TaskSpec(
            id=tid,
            title=title.strip(),
            agent=agent,
            deps=deps_t,
            prompt=prompt,
            acceptance=acceptance_t,
            meta=meta,
        )


@dataclasses.dataclass(frozen=True)
class TaskGraph:
    version: int
    goal: str
    summary: str
    tasks: dict[str, TaskSpec]

    def validate(self) -> None:
        if self.version != 1:
            raise ValueError("task graph version must be 1")
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise ValueError("goal must be a non-empty string")
        if not isinstance(self.summary, str):
            raise ValueError("summary must be a string")

        # deps exist
        for tid, t in self.tasks.items():
            for dep in t.deps:
                if dep not in self.tasks:
                    raise ValueError(f"task {tid} depends on missing task {dep}")

        # cycle detect
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(n: str) -> None:
            if n in visited:
                return
            if n in visiting:
                raise ValueError(f"cycle detected at task {n}")
            visiting.add(n)
            for dep in self.tasks[n].deps:
                dfs(dep)
            visiting.remove(n)
            visited.add(n)

        for tid in self.tasks:
            dfs(tid)

    @staticmethod
    def from_planner_json(planner_text: str, *, max_tasks: int = 64) -> TaskGraph:
        obj = _extract_first_json_object(planner_text)

        _ensure_keys_exact(
            obj,
            allowed=("version", "goal", "summary", "tasks"),
            required=("version", "goal", "tasks"),
            where="task_graph",
        )

        version = obj["version"]
        goal = obj["goal"]
        summary = obj.get("summary", "")
        tasks_raw = obj["tasks"]

        if not isinstance(version, int):
            raise ValueError("task_graph.version must be integer")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("task_graph.goal must be a non-empty string")
        if not isinstance(summary, str):
            raise ValueError("task_graph.summary must be a string")
        if not isinstance(tasks_raw, list):
            raise ValueError("task_graph.tasks must be a list")

        if not tasks_raw:
            raise ValueError("task_graph.tasks cannot be empty")
        if len(tasks_raw) > max_tasks:
            raise ValueError(f"task_graph.tasks too large (max {max_tasks})")

        tasks: dict[str, TaskSpec] = {}
        for td in tasks_raw:
            t = TaskSpec.from_dict(td)
            if t.id in tasks:
                raise ValueError(f"duplicate task id {t.id}")
            tasks[t.id] = t

        g = TaskGraph(version=version, goal=goal.strip(), summary=summary, tasks=tasks)
        g.validate()
        return g

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "goal": self.goal,
            "summary": self.summary,
            "tasks": [
                {"id": t.id, "title": t.title, "agent": t.agent, "deps": list(t.deps)} for t in self.tasks.values()
            ],
        }


@dataclasses.dataclass
class TaskResult:
    ok: bool
    output: str = ""
    error: str = ""
    artifacts: list[Artifact] = dataclasses.field(default_factory=list)
    meta: dict[str, Any] = dataclasses.field(default_factory=dict)


class ToolCallFunc(Protocol):
    async def __call__(self, name: str, args: dict[str, Any]) -> dict[str, Any]: ...


class Subagent(Protocol):
    agent_id: str

    async def run_task(
        self,
        *,
        task: TaskSpec,
        graph: TaskGraph,
        prior_results: dict[str, TaskResult],
        emit_text,
        call_tool,
        cancel_event: asyncio.Event,
    ) -> TaskResult: ...


@dataclasses.dataclass(frozen=True)
class SwarmConfig:
    max_parallel_tasks: int = 6
    # optional per-agent limits; omitted agent_id -> unlimited (bounded by max_parallel_tasks)
    max_parallel_per_agent: dict[str, int] = dataclasses.field(default_factory=dict)
    # planner/reviewer prompts can be overridden by server
    strict_planner: bool = True
    max_tasks: int = 64


class SwarmRunRegistry:
    """
    Global registry so /cancel endpoint can find and stop a run.
    """

    _lock = asyncio.Lock()
    _runs: dict[str, SwarmOrchestrator] = {}

    @classmethod
    async def register(cls, orch: SwarmOrchestrator) -> None:
        async with cls._lock:
            cls._runs[orch.run_id] = orch

    @classmethod
    async def unregister(cls, run_id: str) -> None:
        async with cls._lock:
            cls._runs.pop(run_id, None)

    @classmethod
    async def cancel(cls, run_id: str) -> bool:
        async with cls._lock:
            orch = cls._runs.get(run_id)
            if orch is None:
                return False
            orch.cancel()
            return True


# -----------------------------
# Orchestrator
# -----------------------------


class SwarmOrchestrator:
    def __init__(
        self,
        *,
        run_id: str,
        config: SwarmConfig | None = None,
        tool_call: ToolCallFunc | None = None,
        tool_mutates_fs: callable | None = None,
    ) -> None:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        self.run_id = run_id
        self.config = config or SwarmConfig()
        self._tool_call = tool_call
        self._tool_mutates_fs = tool_mutates_fs  # (name,args)->bool

        # cancellation + sequencing
        self._cancel = asyncio.Event()
        self._seq = 0

        # locks + limits
        self._fs_lock = asyncio.Lock()
        self._task_sem = asyncio.Semaphore(max(1, int(self.config.max_parallel_tasks)))
        self._agent_sems: dict[str, asyncio.Semaphore] = {
            a: asyncio.Semaphore(max(1, int(n))) for a, n in (self.config.max_parallel_per_agent or {}).items()
        }

        # runtime state
        self.graph: TaskGraph | None = None
        self.task_status: dict[str, TaskStatus] = {}
        self.task_results: dict[str, TaskResult] = {}
        self._blocked_by: dict[str, str] = {}  # task_id -> failed dep id
        self._events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._done_evt = asyncio.Event()

    def cancel(self) -> None:
        self._cancel.set()

    async def astream(
        self,
        *,
        user_request: str,
        subagents: dict[str, Subagent],
        planner_prompt: str | None = None,
        reviewer_prompt: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Streams events. This is a producer/consumer:
        - background task runs the swarm
        - this async generator yields events from the queue
        """
        await SwarmRunRegistry.register(self)
        driver = asyncio.create_task(
            self._run(
                user_request=user_request,
                subagents=subagents,
                planner_prompt=planner_prompt,
                reviewer_prompt=reviewer_prompt,
            )
        )
        try:
            while True:
                evt = await self._events.get()
                if evt is None:
                    break
                yield evt
        finally:
            self.cancel()
            driver.cancel()
            try:
                await driver
            except Exception:
                pass
            await SwarmRunRegistry.unregister(self.run_id)

    async def _emit(self, etype: str, agent_id: str, task_id: str, data: dict[str, Any]) -> None:
        self._seq += 1
        evt = {
            "type": etype,
            "run_id": self.run_id,
            "agent_id": agent_id,
            "task_id": task_id,
            "seq": self._seq,
            "ts": _utc_iso(),
        }
        if data:
            evt.update(data)
        await self._events.put(evt)

    async def _run(
        self,
        *,
        user_request: str,
        subagents: dict[str, Subagent],
        planner_prompt: str | None,
        reviewer_prompt: str | None,
    ) -> None:
        ok = True
        error = ""
        started_ms = _monotonic_ms()

        try:
            # Preconditions
            if "planner" not in subagents or "reviewer" not in subagents:
                raise ValueError('subagents must include "planner" and "reviewer"')

            # 1) Planner: produce graph JSON
            plan_task = TaskSpec(
                id="__plan__",
                title="Plan and produce task graph",
                agent="planner",
                deps=(),
                prompt=planner_prompt or self._default_planner_prompt(user_request),
                acceptance=("Output a valid JSON TaskGraph version=1",),
                meta={"internal": True},
            )
            await self._emit(
                "task_update",
                "orchestrator",
                plan_task.id,
                {"status": TaskStatus.RUNNING.value, "title": plan_task.title, "agent": "planner", "deps": []},
            )
            plan_chunks: list[str] = []

            async def emit_plan_text(chunk: str) -> None:
                plan_chunks.append(chunk)
                await self._emit("agent_text", "planner", plan_task.id, {"text": chunk})

            planner = subagents["planner"]
            planner_res = await planner.run_task(
                task=plan_task,
                graph=TaskGraph(version=1, goal="(planning)", summary="", tasks={}),
                prior_results={},
                emit_text=emit_plan_text,
                call_tool=lambda name, args, mutates_fs=None: self._call_tool(
                    agent_id="planner", task_id=plan_task.id, name=name, args=args, mutates_fs=mutates_fs
                ),
                cancel_event=self._cancel,
            )
            plan_text = (planner_res.output or "").strip() or "".join(plan_chunks).strip()
            # Strictly parse and validate
            self.graph = TaskGraph.from_planner_json(plan_text, max_tasks=self.config.max_tasks)
            await self._emit("task_update", "orchestrator", plan_task.id, {"status": TaskStatus.DONE.value, "ok": True})

            await self._emit("swarm_start", "orchestrator", "__swarm__", {"graph": self.graph.to_summary_dict()})

            # 2) Execute tasks
            await self._execute_graph(subagents=subagents)

            # 3) Reviewer: synthesize final output
            review_task = TaskSpec(
                id="__review__",
                title="Synthesize final answer",
                agent="reviewer",
                deps=(),
                prompt=reviewer_prompt or self._default_reviewer_prompt(user_request, self.graph),
                acceptance=("Produce final response.",),
                meta={"internal": True},
            )
            await self._emit(
                "task_update",
                "orchestrator",
                review_task.id,
                {"status": TaskStatus.RUNNING.value, "title": review_task.title, "agent": "reviewer", "deps": []},
            )
            review_chunks: list[str] = []

            async def emit_review_text(chunk: str) -> None:
                review_chunks.append(chunk)
                await self._emit("agent_text", "reviewer", review_task.id, {"text": chunk})

            reviewer = subagents["reviewer"]
            review_res = await reviewer.run_task(
                task=review_task,
                graph=self.graph,
                prior_results=self.task_results.copy(),
                emit_text=emit_review_text,
                call_tool=lambda name, args, mutates_fs=None: self._call_tool(
                    agent_id="reviewer", task_id=review_task.id, name=name, args=args, mutates_fs=mutates_fs
                ),
                cancel_event=self._cancel,
            )
            final_text = (review_res.output or "").strip() or "".join(review_chunks).strip()
            await self._emit(
                "task_update", "orchestrator", review_task.id, {"status": TaskStatus.DONE.value, "ok": True}
            )
            await self._emit(
                "swarm_done",
                "orchestrator",
                "__swarm__",
                {
                    "ok": True,
                    "final": final_text,
                    "summary": self._summarize_run(),
                    "duration_ms": _monotonic_ms() - started_ms,
                },
            )
        except asyncio.CancelledError:
            ok = False
            error = "cancelled"
            await self._emit(
                "swarm_done",
                "orchestrator",
                "__swarm__",
                {
                    "ok": False,
                    "error": error,
                    "summary": self._summarize_run(),
                    "duration_ms": _monotonic_ms() - started_ms,
                },
            )
        except Exception as e:
            ok = False
            error = f"{type(e).__name__}: {e}"
            await self._emit(
                "swarm_done",
                "orchestrator",
                "__swarm__",
                {
                    "ok": False,
                    "error": error,
                    "summary": self._summarize_run(),
                    "duration_ms": _monotonic_ms() - started_ms,
                },
            )
        finally:
            await self._events.put(None)
            self._done_evt.set()

    async def _execute_graph(self, *, subagents: dict[str, Subagent]) -> None:
        assert self.graph is not None

        # init statuses
        for tid, t in self.graph.tasks.items():
            self.task_status[tid] = TaskStatus.QUEUED
            await self._emit(
                "task_update",
                "orchestrator",
                tid,
                {
                    "status": TaskStatus.QUEUED.value,
                    "title": t.title,
                    "agent": t.agent,
                    "deps": list(t.deps),
                },
            )

        pending = set(self.graph.tasks.keys())
        inflight: set[str] = set()
        ready_q: asyncio.Queue[str] = asyncio.Queue()
        state_changed = asyncio.Event()
        state_changed.set()  # initial scheduling pass

        def deps_state(tid: str) -> tuple[bool, str | None]:
            """
            Returns (ready, blocker_dep_id)
            - ready True if all deps are DONE
            - blocker_dep_id is set if any dep is FAILED/CANCELLED/BLOCKED
            """
            t = self.graph.tasks[tid]
            for dep in t.deps:
                st = self.task_status.get(dep)
                if st in (TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED):
                    return False, dep
                if st != TaskStatus.DONE:
                    return False, None
            return True, None

        async def scheduler_loop() -> None:
            while True:
                if self._cancel.is_set():
                    return

                state_changed.clear()
                progressed = False

                # 1) mark blocked tasks
                to_block = []
                for tid in list(pending):
                    ready, blocker = deps_state(tid)
                    if blocker is not None:
                        to_block.append((tid, blocker))
                for tid, blocker in to_block:
                    pending.remove(tid)
                    self.task_status[tid] = TaskStatus.BLOCKED
                    self._blocked_by[tid] = blocker
                    await self._emit(
                        "task_update", "orchestrator", tid, {"status": TaskStatus.BLOCKED.value, "blocked_by": blocker}
                    )
                    progressed = True

                # 2) enqueue ready tasks
                for tid in list(pending):
                    ready, blocker = deps_state(tid)
                    if ready:
                        pending.remove(tid)
                        await ready_q.put(tid)
                        progressed = True

                # stop condition: nothing pending, nothing inflight, queue empty
                if not pending and not inflight and ready_q.empty():
                    return

                if not progressed:
                    # wait until a worker finishes (or cancellation)
                    await asyncio.wait(
                        [asyncio.create_task(state_changed.wait()), asyncio.create_task(self._cancel.wait())],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

        async def worker_loop() -> None:
            while True:
                if self._cancel.is_set():
                    return
                try:
                    tid = await asyncio.wait_for(ready_q.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    # exit only if scheduler has nothing left to enqueue and no inflight work
                    if not pending and not inflight and ready_q.empty():
                        return
                    continue

                inflight.add(tid)
                try:
                    await self._run_one_task(task_id=tid, subagents=subagents)
                finally:
                    inflight.discard(tid)
                    state_changed.set()

        worker_count = max(1, int(self.config.max_parallel_tasks))
        async with asyncio.TaskGroup() as tg:
            tg.create_task(scheduler_loop())
            for _ in range(worker_count):
                tg.create_task(worker_loop())

        # If cancelled, mark anything never scheduled as cancelled.
        if self._cancel.is_set():
            for tid in list(pending):
                self.task_status[tid] = TaskStatus.CANCELLED
                await self._emit("task_update", "orchestrator", tid, {"status": TaskStatus.CANCELLED.value})

    async def _run_one_task(self, *, task_id: str, subagents: dict[str, Subagent]) -> None:
        assert self.graph is not None
        t = self.graph.tasks[task_id]

        if self._cancel.is_set():
            self.task_status[task_id] = TaskStatus.CANCELLED
            await self._emit("task_update", "orchestrator", task_id, {"status": TaskStatus.CANCELLED.value})
            return

        agent = subagents.get(t.agent)
        if agent is None:
            self.task_status[task_id] = TaskStatus.FAILED
            await self._emit(
                "task_update",
                "orchestrator",
                task_id,
                {"status": TaskStatus.FAILED.value, "error": f"missing subagent '{t.agent}'"},
            )
            self.task_results[task_id] = TaskResult(ok=False, error=f"missing subagent '{t.agent}'")
            return

        # concurrency control: global + per-agent
        agent_sem = self._agent_sems.get(t.agent)
        await self._task_sem.acquire()
        if agent_sem:
            await agent_sem.acquire()

        started = _monotonic_ms()
        self.task_status[task_id] = TaskStatus.RUNNING
        await self._emit("task_update", "orchestrator", task_id, {"status": TaskStatus.RUNNING.value})

        chunks: list[str] = []

        async def emit_text(chunk: str) -> None:
            chunks.append(chunk)
            await self._emit("agent_text", t.agent, task_id, {"text": chunk})

        async def call_tool(name: str, args: dict[str, Any], mutates_fs: bool | None = None) -> dict[str, Any]:
            return await self._call_tool(agent_id=t.agent, task_id=task_id, name=name, args=args, mutates_fs=mutates_fs)

        try:
            res = await agent.run_task(
                task=t,
                graph=self.graph,
                prior_results=self.task_results.copy(),
                emit_text=emit_text,
                call_tool=call_tool,
                cancel_event=self._cancel,
            )
            if not isinstance(res, TaskResult):
                raise TypeError("Subagent.run_task must return TaskResult")

            if not res.output:
                res.output = "".join(chunks)

            # normalize artifacts
            norm_artifacts: list[Artifact] = []
            for a in res.artifacts or []:
                if isinstance(a, Artifact):
                    norm_artifacts.append(a)
                elif isinstance(a, dict):
                    norm_artifacts.append(Artifact.from_dict(a))
                else:
                    raise ValueError("TaskResult.artifacts must contain Artifact or dict items")
            res.artifacts = norm_artifacts

            self.task_results[task_id] = res
            if res.ok:
                self.task_status[task_id] = TaskStatus.DONE
                await self._emit(
                    "task_update",
                    "orchestrator",
                    task_id,
                    {"status": TaskStatus.DONE.value, "ok": True, "duration_ms": _monotonic_ms() - started},
                )
            else:
                self.task_status[task_id] = TaskStatus.FAILED
                await self._emit(
                    "task_update",
                    "orchestrator",
                    task_id,
                    {
                        "status": TaskStatus.FAILED.value,
                        "ok": False,
                        "error": res.error or "task failed",
                        "duration_ms": _monotonic_ms() - started,
                    },
                )
        except asyncio.CancelledError:
            self.task_status[task_id] = TaskStatus.CANCELLED
            await self._emit("task_update", "orchestrator", task_id, {"status": TaskStatus.CANCELLED.value})
        except Exception as e:
            self.task_status[task_id] = TaskStatus.FAILED
            err = f"{type(e).__name__}: {e}"
            self.task_results[task_id] = TaskResult(ok=False, error=err, output="".join(chunks))
            await self._emit(
                "task_update",
                "orchestrator",
                task_id,
                {"status": TaskStatus.FAILED.value, "error": err, "duration_ms": _monotonic_ms() - started},
            )
        finally:
            if agent_sem:
                agent_sem.release()
            self._task_sem.release()

    async def _call_tool(
        self, *, agent_id: str, task_id: str, name: str, args: dict[str, Any], mutates_fs: bool | None
    ) -> dict[str, Any]:
        tool_call_id = f"{agent_id}:{task_id}:{self._seq + 1}"
        # decide mutates_fs
        if mutates_fs is None:
            if self._tool_mutates_fs is not None:
                try:
                    mutates_fs = bool(self._tool_mutates_fs(name, args))
                except Exception:
                    mutates_fs = True
            else:
                mutates_fs = _guess_mutates_fs(name, args)

        start = _monotonic_ms()
        await self._emit(
            "agent_tool_start",
            agent_id,
            task_id,
            {"tool_call_id": tool_call_id, "tool": name, "args": args, "mutates_fs": bool(mutates_fs)},
        )

        async def do_call() -> dict[str, Any]:
            if self._tool_call is None:
                raise RuntimeError("SwarmOrchestrator requires tool_call callback for tool execution")
            return await self._tool_call(name, args)

        try:
            if mutates_fs:
                async with self._fs_lock:
                    if self._cancel.is_set():
                        raise asyncio.CancelledError()
                    result = await do_call()
            else:
                if self._cancel.is_set():
                    raise asyncio.CancelledError()
                result = await do_call()

            took = _monotonic_ms() - start
            await self._emit(
                "agent_tool_result",
                agent_id,
                task_id,
                {"tool_call_id": tool_call_id, "tool": name, "ok": True, "result": result, "took_ms": took},
            )
            return result
        except asyncio.CancelledError:
            took = _monotonic_ms() - start
            await self._emit(
                "agent_tool_result",
                agent_id,
                task_id,
                {"tool_call_id": tool_call_id, "tool": name, "ok": False, "error": "cancelled", "took_ms": took},
            )
            raise
        except Exception as e:
            took = _monotonic_ms() - start
            await self._emit(
                "agent_tool_result",
                agent_id,
                task_id,
                {
                    "tool_call_id": tool_call_id,
                    "tool": name,
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "took_ms": took,
                },
            )
            raise

    def _summarize_run(self) -> dict[str, Any]:
        statuses = {k: v.value if isinstance(v, TaskStatus) else str(v) for k, v in self.task_status.items()}
        failed = [tid for tid, st in statuses.items() if st == TaskStatus.FAILED.value]
        blocked = [tid for tid, st in statuses.items() if st == TaskStatus.BLOCKED.value]
        cancelled = [tid for tid, st in statuses.items() if st == TaskStatus.CANCELLED.value]
        done = [tid for tid, st in statuses.items() if st == TaskStatus.DONE.value]
        artifacts = []
        for tid, res in self.task_results.items():
            for a in res.artifacts or []:
                artifacts.append({"task_id": tid, "kind": a.kind, "title": a.title, "path": a.path})
        return {
            "status": statuses,
            "done": done,
            "failed": failed,
            "blocked": blocked,
            "cancelled": cancelled,
            "blocked_by": dict(self._blocked_by),
            "artifacts": artifacts,
        }

    def _default_planner_prompt(self, user_request: str) -> str:
        # Tight, explicit JSON schema. Yes, models still cheat, so we parse strictly anyway.
        return (
            "You are the Planner subagent in Swarm Mode.\n"
            "Your job: turn the user request into a dependency-aware task graph.\n\n"
            "OUTPUT RULES (STRICT):\n"
            "1) Output ONE JSON object and nothing else.\n"
            "2) It must follow this schema exactly (no extra keys):\n"
            "{\n"
            '  "version": 1,\n'
            '  "goal": "one sentence goal",\n'
            '  "summary": "short human summary (optional)",\n'
            '  "tasks": [\n'
            "    {\n"
            '      "id": "T1",\n'
            '      "title": "short title",\n'
            '      "agent": "planner|coder|researcher|news|social|tester|reviewer|...",\n'
            '      "deps": ["T0", "T2"],\n'
            '      "prompt": "the instruction for that agent",\n'
            '      "acceptance": ["a", "b"],\n'
            '      "meta": {"mutates_fs": true|false, "risk": "low|med|high"}\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "PLANNING GUIDELINES:\n"
            "- Prefer 4-12 tasks. Keep tasks small and testable.\n"
            "- Make deps minimal. Parallelize when safe.\n"
            "- Add at least one tester task that runs/validates.\n"
            "- Use agent names that exist (planner/coder/researcher/news/social/tester/reviewer).\n"
            "- If uncertain, include a short 'research' task before 'edit'.\n\n"
            f"USER REQUEST:\n{user_request}\n"
        )

    def _default_reviewer_prompt(self, user_request: str, graph: TaskGraph) -> str:
        # Provide structure; reviewer can be another model call.
        return (
            "You are the Reviewer subagent in Swarm Mode.\n"
            "Synthesize a final response from the task results.\n\n"
            "Rules:\n"
            "- The final answer is user-facing natural language.\n"
            "- Do NOT output raw JSON, task graphs, or schema objects.\n"
            "- Be honest about failures/blocked tasks.\n"
            "- Provide a demo script (commands + expected outputs).\n"
            "- List files changed/created if known.\n"
            "- Mention how to run tests.\n\n"
            f"USER REQUEST:\n{user_request}\n\n"
            f"TASK GRAPH:\n{json.dumps(graph.to_summary_dict(), indent=2)}\n"
        )
