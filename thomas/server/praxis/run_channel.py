"""Local authenticated channel between a Build lead and server-owned agents."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import stat
import time
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas.core.praxis.plan import plan_problems
from thomas.core.praxis.progress import interval_concurrency
from thomas.core.praxis.timelines import build_report as build_timeline_report
from thomas.server.praxis.quota import QuotaDecision, park_child

if TYPE_CHECKING:
    from thomas.server.praxis.recovery import PraxisRunJournal

log = logging.getLogger(__name__)
ChildRunner = Callable[..., AsyncIterator[dict[str, Any]]]
READ_KINDS = frozenset({"research", "review", "verify"})
_PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
# One delete call names at most this many paths, and says why in at most _WHY_CHARS characters.
MAX_DELETE_PATHS = 200
_WHY_CHARS = 1000


def _is_link(path: Path) -> bool:
    """A symlink, a junction, or any other Windows reparse point: never followed, never deleted."""
    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & reparse)


def _names_git(relative: Path) -> bool:
    # Windows drops a name's trailing dots and spaces, and ignores case: ".GIT." is ".git".
    return any(part.rstrip(". ").casefold() == ".git" for part in relative.parts)


def _delete_target(root: Path, raw: object) -> Path | str:
    """The file ``raw`` names inside ``root``, or the sentence that refuses it.

    Every check runs on the lexical path (``..`` collapsed, nothing followed) and the one that is
    deleted is that same path, so what was checked is what goes. A link anywhere along it is refused
    outright rather than followed; the resolved path is checked again for a name only the file system
    knows (a Windows short name for ``.git``).
    """
    if not isinstance(raw, str) or not raw.strip():
        return "refused: a path must be non-empty text"
    if Path(raw).is_absolute() or Path(raw).anchor:
        return "refused: an absolute path; give a path relative to this project's folder"
    if ":" in raw:
        return "refused: a path with ':' can name a drive or a hidden stream; give a plain path in this project"
    lexical = Path(os.path.normpath(root / raw))
    if lexical == root:
        return "refused: that is this project's folder itself"
    if not lexical.is_relative_to(root):
        return "refused: that is outside this project's folder"
    relative = lexical.relative_to(root)
    if _names_git(relative):
        return "refused: that is inside a .git folder"
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if _is_link(cursor):
            return "refused: that is, or goes through, a symlink or junction"
    if not lexical.exists():
        return "refused: no such file"
    resolved = lexical.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        return "refused: that is outside this project's folder"
    if _names_git(resolved.relative_to(root)):
        return "refused: that is inside a .git folder"
    if lexical.is_dir():
        return "refused: that is a folder; only files can be deleted"
    if not lexical.is_file():
        return "refused: that is not a regular file"
    return lexical


def _delete_one(root: Path, raw: object) -> str:
    try:
        target = _delete_target(root, raw)
    except (OSError, ValueError) as exc:  # ValueError: an embedded NUL, for one
        return f"refused: that path could not be checked ({exc})"
    if isinstance(target, str):
        return target
    try:
        target.unlink()
    except OSError as exc:
        return f"refused: the file could not be deleted ({exc.strerror or exc})"
    return "deleted"


class RunChannel:
    def __init__(
        self,
        run_id: str,
        run_child: ChildRunner,
        *,
        instructions: str = "",
        journal: PraxisRunJournal | None = None,
        state_observer: Callable[[str, str], None] | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.run_id = run_id
        self.token = secrets.token_urlsafe(32)
        self._run_child = run_child
        self._children: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._changed = asyncio.Condition()
        self._closed = False
        self._suspending = False
        self._instructions = instructions
        self._journal = journal
        self._state_observer = state_observer
        self._project_root = project_root.resolve() if project_root is not None else None

    def _checkpoint(self, child_id: str) -> None:
        if self._journal is not None:
            self._journal.checkpoint(self.run_id, self._children[child_id])

    def _observe_state(self, child_id: str, prior: str | None = None) -> None:
        state = self._children[child_id]["state"]
        if self._state_observer is not None and state != prior:
            self._state_observer(child_id, state)

    def attach_state_observer(self, observer: Callable[[str, str], None]) -> None:
        """Attach after admission when coordinator owners are minted child IDs."""
        if self._state_observer is not None:
            raise RuntimeError("state observer already attached")
        self._state_observer = observer
        for child_id in self._children:
            self._observe_state(child_id)

    def authorized(self, token: str) -> bool:
        return not self._closed and bool(token) and hmac.compare_digest(self.token, token)

    async def admit_external_builder(self, *, plan_id: str, title: str, brief: str, path: str) -> dict[str, str]:
        """Journal a Build-owned writer before its subprocess starts work."""
        if self._closed or self._journal is None or self._project_root is None:
            raise ValueError("external builder channel is unavailable")
        if not plan_id or not title or not brief or not path or len(title) > 200 or len(brief) > 12000:
            raise ValueError("external builder needs a bounded plan, title, brief, and path")
        if any(row["plan_id"] == plan_id for row in self._children.values()):
            raise ValueError("external builder plan id already exists")
        target = (self._project_root / path).resolve()
        if Path(path).is_absolute() or not target.is_relative_to(self._project_root) or target == self._project_root:
            raise ValueError("external builder path escapes the project")
        child_id = "agent_" + secrets.token_hex(12)
        row = {
            "agent_id": child_id,
            "plan_id": plan_id,
            "title": title,
            "kind": "builder",
            "execution_origin": "external_builder",
            "path": path,
            "state": "starting",
            "dependencies": [],
            "events": [],
            "model_used": None,
            "model_choice": {},
            "started_at": None,
            "ended_at": None,
            "activity_intervals": [],
            "attempt_started_at": None,
            "attempts": 0,
        }
        self._journal.admit(self.run_id, self._instructions, [{**row, "brief": brief, "dependencies": []}])
        self._children[child_id] = row
        self._observe_state(child_id)
        return {"agent_id": child_id, "plan_id": plan_id, "title": title, "state": "starting"}

    async def report_external_builder(self, child_id: str, event: dict[str, Any]) -> dict[str, str]:
        """Accept only bounded lifecycle reports from the authenticated Build subprocess."""
        if not isinstance(event, dict):
            raise ValueError("external builder event must be an object")
        row = self._children.get(child_id)
        if row is None or row.get("execution_origin") != "external_builder":
            raise ValueError("unknown external builder")
        if row["state"] in {"completed", "failed", "stopped", "interrupted"}:
            raise ValueError("external builder already settled")
        kind = event.get("type")
        if kind not in {"started", "model_runtime", "integrated", "failed", "cancelled"}:
            raise ValueError("unsupported external builder event")
        previous = row["state"]
        if kind == "started":
            if previous != "starting":
                raise ValueError("external builder already started")
            row["state"] = "running"
            row["attempts"] += 1
            row["started_at"] = time.perf_counter()
            row["attempt_started_at"] = row["started_at"]
            recorded = {"type": "started"}
        elif kind == "model_runtime":
            model = str(event.get("model_used") or "")
            if previous != "running" or not _MODEL.fullmatch(model):
                raise ValueError("invalid external builder model receipt")
            row["model_used"] = model
            recorded = {"type": "model_runtime", "model_used": model, "source": "build_reported"}
        elif kind == "integrated":
            fingerprint = str(event.get("fingerprint") or "")
            target = (self._project_root / row["path"]).resolve()
            if previous != "running" or not target.is_relative_to(self._project_root) or not target.is_file():
                raise ValueError("external builder integrated file receipt did not match disk")
            content = target.read_bytes()
            actual = f"sha256:{hashlib.sha256(content).hexdigest()}:{len(content)}"
            if fingerprint != actual:
                raise ValueError("external builder integrated file receipt did not match disk")
            row["state"] = "completed"
            row["ended_at"] = time.perf_counter()
            recorded = {"type": "done", "fingerprint": fingerprint, "path": row["path"]}
        else:
            if previous not in {"starting", "running"}:
                raise ValueError("invalid external builder settlement")
            row["state"] = "stopped" if kind == "cancelled" else "failed"
            row["ended_at"] = time.perf_counter()
            recorded = {"type": "error", "error": str(event.get("error") or kind)[:1000]}
        row["events"].append(recorded)
        if row["state"] in {"completed", "failed", "stopped"} and row.get("attempt_started_at") is not None:
            row["activity_intervals"].append((row["attempt_started_at"], row["ended_at"]))
        self._checkpoint(child_id)
        self._observe_state(child_id, previous)
        async with self._changed:
            self._changed.notify_all()
        return {"agent_id": child_id, "state": row["state"]}

    async def delete_files(self, paths: Any, *, why: str) -> dict[str, Any]:
        """Delete files inside this run's project folder: one result per path, a bad path refused by name.

        Build's Claude lead has no shell unless guardrails are open, so before this it could empty a file
        but never remove it. Confined like :meth:`admit_external_builder`'s path, and recorded as a
        journaled receipt row so the run's history shows what went and why.
        """
        if self._closed:
            raise ValueError("deleting files is unavailable: this run has ended")
        if self._project_root is None:
            raise ValueError("deleting files is unavailable: this run has no project folder")
        if not isinstance(paths, list) or not paths:
            raise ValueError("paths must be a nonempty list of paths inside this project")
        if len(paths) > MAX_DELETE_PATHS:
            raise ValueError(f"at most {MAX_DELETE_PATHS} paths per call; this call named {len(paths)}")
        reason = str(why or "").strip()
        if not reason or len(reason) > _WHY_CHARS:
            raise ValueError(f"say why these files are being deleted, in at most {_WHY_CHARS} characters")
        results = [
            {"path": raw if isinstance(raw, str) else repr(raw), "result": _delete_one(self._project_root, raw)}
            for raw in paths
        ]
        deleted = sum(row["result"] == "deleted" for row in results)
        receipt = "delete_" + secrets.token_hex(12)
        row = {
            "agent_id": receipt,
            "plan_id": receipt,
            "title": f"Deleted {deleted} file(s), refused {len(results) - deleted}",
            "kind": "delete",
            "execution_origin": "file_delete",
            "path": "",
            "state": "completed" if deleted else "failed",
            "dependencies": [],
            "events": [{"type": "deleted", "why": reason, "results": results}],
            "model_used": None,
            "model_choice": {},
            "started_at": None,
            "ended_at": None,
            "activity_intervals": [],
            "attempt_started_at": None,
            "attempts": 0,
        }
        self._children[receipt] = row
        if self._journal is not None:
            try:
                self._journal.admit(self.run_id, self._instructions, [{**row, "brief": reason}])
                self._checkpoint(receipt)
            except sqlite3.Error:
                # The files are already gone: the lead must still get its results, and this run's
                # status still shows the receipt. Only a restart would lose it.
                log.warning("could not journal delete receipt %s for run %s", receipt, self.run_id, exc_info=True)
        return {"agent_id": receipt, "deleted": deleted, "refused": len(results) - deleted, "results": results}

    async def spawn(self, units: list[dict[str, Any]], *, why_parallel: str = "") -> list[dict[str, Any]]:
        if self._closed:
            raise RuntimeError("run ended")
        if not isinstance(units, list) or not units:
            raise ValueError("units must be a nonempty list")
        if self._instructions:
            problems = plan_problems({"units": units, "why_parallel": why_parallel}, instructions=self._instructions)
            if problems:
                raise ValueError("plan_refused: " + ", ".join(problems))
        admitted = []
        for unit in units:
            if not isinstance(unit, dict) or unit.get("kind", "review") not in READ_KINDS:
                raise ValueError("run channel currently accepts research, review, and verification units")
            title = str(unit.get("title") or "").strip()
            brief = str(unit.get("brief") or "").strip()
            if not title or not brief or len(title) > 200 or len(brief) > 12000:
                raise ValueError("each unit needs a bounded title and brief")
            choice = unit.get("model_choice")
            if choice is not None and (
                not isinstance(choice, dict)
                or not choice
                or set(choice) - {"profile", "model_id"}
                or any(
                    not isinstance(value, str) or not (_PROFILE if key == "profile" else _MODEL).fullmatch(value)
                    for key, value in choice.items()
                )
            ):
                raise ValueError("invalid Build child model choice")
        declared = [str(unit.get("id") or "") for unit in units if unit.get("id")]
        if len(declared) != len(set(declared)) or any(
            dep not in declared for unit in units for dep in (unit.get("depends_on") or [])
        ):
            raise ValueError("plan_refused: invalid_dependencies")
        plan_ids: dict[str, str] = {}
        for unit in units:
            child_id = "agent_" + secrets.token_hex(12)
            title, brief = str(unit["title"]).strip(), str(unit["brief"]).strip()
            kind = str(unit.get("kind") or "review")
            plan_id = str(unit.get("id") or child_id)
            plan_ids[plan_id] = child_id
            row = {
                "agent_id": child_id,
                "plan_id": plan_id,
                "title": title,
                "kind": kind,
                "execution_origin": "server",
                "state": "starting",
                "events": [],
                "model_used": None,
                "model_choice": dict(unit.get("model_choice") or {}),
                "started_at": None,
                "ended_at": None,
                "activity_intervals": [],
                "attempt_started_at": None,
                "attempts": 0,
            }
            self._children[child_id] = row
            admitted.append({"agent_id": child_id, "plan_id": plan_id, "title": title, "state": "starting"})
        for unit, handle in zip(units, admitted, strict=True):
            self._children[handle["agent_id"]]["dependencies"] = [
                plan_ids[dep] for dep in (unit.get("depends_on") or [])
            ]
        if self._journal is not None:
            self._journal.admit(
                self.run_id,
                self._instructions,
                [
                    {
                        **self._children[handle["agent_id"]],
                        "brief": unit["brief"],
                        "dependencies": self._children[handle["agent_id"]]["dependencies"],
                    }
                    for unit, handle in zip(units, admitted, strict=True)
                ],
            )
        for handle in admitted:
            self._observe_state(handle["agent_id"])
        for unit, handle in zip(units, admitted, strict=True):
            child_id = handle["agent_id"]
            dependencies = [plan_ids[dep] for dep in (unit.get("depends_on") or [])]
            self._tasks[child_id] = asyncio.create_task(
                self._run_after_dependencies(
                    child_id,
                    dependencies,
                    str(unit.get("kind") or "review"),
                    str(unit["title"]).strip(),
                    str(unit["brief"]).strip(),
                ),
                name=f"praxis:{child_id}",
            )
        return admitted

    async def _run_after_dependencies(
        self, child_id: str, dependencies: list[str], kind: str, title: str, brief: str
    ) -> None:
        if dependencies:
            try:
                await asyncio.gather(*(self._tasks[parent] for parent in dependencies), return_exceptions=True)
            except asyncio.CancelledError:
                if self._suspending:
                    raise
                self._children[child_id]["state"] = "stopped"
                self._checkpoint(child_id)
                self._observe_state(child_id, "starting")
                async with self._changed:
                    self._changed.notify_all()
                raise
            failed = [parent for parent in dependencies if self._children[parent]["state"] != "completed"]
            if failed:
                row = self._children[child_id]
                row["state"] = "failed"
                row["events"].append({"type": "error", "error": "dependency did not complete"})
                self._checkpoint(child_id)
                self._observe_state(child_id, "starting")
                async with self._changed:
                    self._changed.notify_all()
                return
        await self._run(child_id, kind, title, brief)

    async def _run(self, child_id: str, kind: str, title: str, brief: str) -> None:
        row = self._children[child_id]
        try:
            while True:
                if row["state"] == "quota_wait":
                    await asyncio.sleep(max(0.0, float(row.get("resume_at") or time.time()) - time.time()))
                    previous_state = row["state"]
                    row["state"] = "starting"
                    self._checkpoint(child_id)
                    self._observe_state(child_id, previous_state)
                row["attempts"] += 1
                previous_state = row["state"]
                row["state"] = "running"
                started = time.perf_counter()
                row["started_at"] = row["started_at"] or started
                row["attempt_started_at"] = started
                self._checkpoint(child_id)
                self._observe_state(child_id, previous_state)
                retryable = False
                parked = False
                try:
                    choice = row.get("model_choice") or {}
                    source = (
                        self._run_child(child_id, kind, title, brief, choice)
                        if choice
                        else self._run_child(child_id, kind, title, brief)
                    )
                    async with aclosing(source) as stream:
                        async for event in stream:
                            previous_state = row["state"]
                            row["events"].append(dict(event))
                            row["model_used"] = event.get("model_used") or row["model_used"]
                            if event.get("type") == "error":
                                retryable = event.get("provider_status") != 401 and bool(event.get("retryable"))
                                quota = event.get("quota")
                                if (
                                    event.get("provider_status") != 401
                                    and isinstance(quota, dict)
                                    and quota.get("kind") == "quota"
                                ):
                                    reset = quota.get("retry_at")
                                    park_child(
                                        row,
                                        QuotaDecision(
                                            "quota",
                                            str(event.get("provider_credential") or ""),
                                            float(reset) if reset is not None else time.time() + 300,
                                            str(quota.get("reason") or "provider_quota"),
                                        ),
                                    )
                                    parked = True
                                else:
                                    row["state"] = "retrying" if retryable else "failed"
                            elif event.get("type") == "done" and row["state"] == "running":
                                row["state"] = "completed"
                            self._checkpoint(child_id)
                            self._observe_state(child_id, previous_state)
                            async with self._changed:
                                self._changed.notify_all()
                            if event.get("type") in {"error", "done"}:
                                break
                    if row["state"] == "running":
                        row["state"] = "failed"
                        row["events"].append({"type": "error", "error": "agent stream ended without a terminal result"})
                        self._checkpoint(child_id)
                        self._observe_state(child_id, "running")
                except OSError as exc:
                    previous_state = row["state"]
                    retryable = True
                    row["state"] = "retrying"
                    row["events"].append({"type": "error", "error": str(exc), "retryable": True})
                    self._checkpoint(child_id)
                    self._observe_state(child_id, previous_state)
                finally:
                    row["activity_intervals"].append((started, time.perf_counter()))
                    async with self._changed:
                        self._changed.notify_all()
                if parked:
                    continue
                if not retryable:
                    break
                delay = min(300.0, float(2 ** min(row["attempts"] - 1, 8)))
                row["events"].append({"type": "retry", "attempt": row["attempts"] + 1, "delay_s": delay})
                self._checkpoint(child_id)
                async with self._changed:
                    self._changed.notify_all()
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            if self._suspending:
                raise
            previous_state = row["state"]
            row["state"] = "stopped"
            self._checkpoint(child_id)
            self._observe_state(child_id, previous_state)
            raise
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            previous_state = row["state"]
            row["state"] = "failed"
            row["events"].append({"type": "error", "error": str(exc)})
            self._checkpoint(child_id)
            self._observe_state(child_id, previous_state)
        finally:
            row["ended_at"] = time.perf_counter()
            async with self._changed:
                self._changed.notify_all()

    def status(self, ids: list[str] | None = None, *, after: dict[str, int] | None = None) -> dict[str, Any]:
        selected = ids if ids is not None else list(self._children)
        cursors = after or {}
        now = time.perf_counter()
        timeline = build_timeline_report(list(self._children.values()), now=now)
        active_s = {row["agent_id"]: row["active_s"] for row in timeline["agents"]}
        rows = []
        for child_id in selected:
            row = self._children.get(child_id)
            if row is None:
                continue
            position = max(0, int(cursors.get(child_id, 0)))
            rows.append(
                {
                    "agent_id": child_id,
                    "plan_id": row["plan_id"],
                    "title": row["title"],
                    "kind": row["kind"],
                    "execution_origin": row.get("execution_origin", "server"),
                    "path": row.get("path"),
                    "state": row["state"],
                    "model_used": row["model_used"],
                    "model_source": "build_reported"
                    if row.get("execution_origin") == "external_builder"
                    else "server_observed",
                    "attempts": row["attempts"],
                    "active_s": active_s.get(child_id, 0.0),
                    "events": row["events"][position:],
                    "cursor": len(row["events"]),
                }
            )
        intervals = {
            f"{child_id}:{index}": interval
            for child_id, row in self._children.items()
            for index, interval in enumerate(row["activity_intervals"])
        }
        intervals.update(
            {
                f"{child_id}:active": (row["attempt_started_at"], now)
                for child_id, row in self._children.items()
                if row["state"] == "running" and row["started_at"] is not None
            }
        )
        return {
            "run_id": self.run_id,
            "agents": rows,
            "metrics": {
                "active_agents": sum(row["state"] == "running" for row in self._children.values()),
                **interval_concurrency(intervals),
                "dependency_overlap": timeline["dependency_overlap"],
            },
        }

    async def wait(self, ids: list[str], *, after: dict[str, int] | None = None, timeout: float = 30) -> dict[str, Any]:
        if not 0 <= timeout <= 300:
            raise ValueError("wait must be between 0 and 300 seconds")
        cursors = after or {}

        def changed() -> bool:
            return any(
                len(self._children[child_id]["events"]) > int(cursors.get(child_id, 0))
                or self._children[child_id]["state"] in {"completed", "failed", "stopped", "interrupted"}
                for child_id in ids
                if child_id in self._children
            )

        if not changed() and timeout:
            async with self._changed:
                try:
                    await asyncio.wait_for(self._changed.wait_for(changed), timeout)
                except asyncio.TimeoutError:
                    pass
        return self.status(ids, after=cursors)

    async def stop_child(self, child_id: str) -> dict[str, Any]:
        if self._children.get(child_id, {}).get("execution_origin") == "external_builder":
            raise ValueError("Stop the Build run to cancel an external builder")
        task = self._tasks.get(child_id)
        if task is None:
            raise ValueError("unknown child")
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return {"agent_id": child_id, "state": self._children[child_id]["state"]}

    async def close(self) -> None:
        self._closed = True
        await asyncio.gather(*(self.stop_child(child_id) for child_id in self._tasks), return_exceptions=True)
        await self._settle_external("stopped", "Build run stopped")

    def revoke(self) -> None:
        """Stop the helpers now without awaiting, keeping unfinished journal continuations."""
        self._closed = True
        self._suspending = True
        for task in self._tasks.values():
            if not task.done():
                task.cancel()

    async def suspend(self) -> None:
        """Revoke the channel while retaining unfinished journal continuations."""
        self.revoke()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        await self._settle_external("interrupted", "builder process interrupted; rerun Build to resume")

    async def _settle_external(self, state: str, reason: str) -> None:
        for child_id, row in self._children.items():
            if row.get("execution_origin") != "external_builder" or row["state"] in {
                "completed",
                "failed",
                "stopped",
                "interrupted",
            }:
                continue
            previous = row["state"]
            row["state"] = state
            row["ended_at"] = time.perf_counter()
            if row.get("attempt_started_at") is not None:
                row["activity_intervals"].append((row["attempt_started_at"], row["ended_at"]))
            row["events"].append({"type": "error", "error": reason})
            self._checkpoint(child_id)
            self._observe_state(child_id, previous)
        async with self._changed:
            self._changed.notify_all()


class RunChannelRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, RunChannel] = {}
        # Set by whatever owns the registry when a run must be waited for. Called with a run id as the run's channel
        # opens, and it hands back a function that says the channel is over.
        self.holder: Callable[[str], Callable[[], None]] | None = None
        self._holds: dict[str, Callable[[], None]] = {}

    def _hold(self, run_id: str) -> None:
        if self.holder is not None:
            self._holds[run_id] = self.holder(run_id)

    def _release(self, run_id: str) -> None:
        release = self._holds.pop(run_id, None)
        if release is not None:
            release()

    def open(
        self,
        run_id: str,
        run_child: ChildRunner,
        *,
        instructions: str = "",
        journal: PraxisRunJournal | None = None,
        state_observer: Callable[[str, str], None] | None = None,
        project_root: Path | None = None,
    ) -> RunChannel:
        if run_id in self._runs:
            raise ValueError("run channel already exists")
        channel = RunChannel(
            run_id,
            run_child,
            instructions=instructions,
            journal=journal,
            state_observer=state_observer,
            project_root=project_root,
        )
        self._hold(run_id)
        self._runs[run_id] = channel
        return channel

    def adopt(self, run_id: str, channel: RunChannel) -> None:
        """Take in a channel built from the journal after a restart, which counts as open like any other."""
        self._hold(run_id)
        self._runs[run_id] = channel

        # Nobody closes a recovered channel when its children are done, so its life is the children's.
        def over(_task: object = None) -> None:
            if all(task.done() for task in channel._tasks.values()):
                self._release(run_id)

        for task in channel._tasks.values():
            task.add_done_callback(over)

    def get(self, run_id: str, token: str) -> RunChannel | None:
        channel = self._runs.get(run_id)
        return channel if channel is not None and channel.authorized(token) else None

    async def close(self, run_id: str) -> None:
        channel = self._runs.pop(run_id, None)
        try:
            if channel is not None:
                await channel.close()
        finally:
            self._release(run_id)

    async def suspend(self, run_id: str) -> None:
        channel = self._runs.pop(run_id, None)
        try:
            if channel is not None:
                await channel.suspend()
        finally:
            self._release(run_id)
