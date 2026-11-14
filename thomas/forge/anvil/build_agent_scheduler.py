"""A product-owned batch of isolated builders with shared request admission."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from thomas.core.llm_request_admission import shared_provider_admission
from thomas.core.praxis.allowance import BuildAllowance
from thomas.tools.base import Tool, ToolResult

from .build_agent_workspace import _BOOKKEEPING, current_fingerprint, relative_file
from .build_team_ledger import TeamLedger
from .build_team_praxis import TeamPraxisBridge
from .build_team_tasks import run_owned_builders
from .run_channel_client import RunChannelClient

log = logging.getLogger(__name__)


def _one_line(text: str, limit: int = 300) -> str:
    """Collapsed whitespace, capped length: a note that stays one line in a stream or a tool result."""
    return " ".join(str(text or "").split())[:limit]


class BuildTeamScheduler(Tool):
    name = "task.team"
    category = "agents"
    description = (
        "Run a team of isolated file builders using the selected model, and wait for all results. "
        "Each assignment needs a title, complete instructions, and one distinct relative UTF-8 output file. "
        "All builders read private copies of current project files; they cannot run commands, browse, or delegate. "
        "Use this for independent implementation files; never split edits to the same file among builders. "
        "Splitting pays when the request breaks into two or more independent parts: one call, one assignment "
        "per part, each builder owning only its own files. "
        "Provider requests share an adaptive account queue; assignments start in machine-sized waves. "
        "Integration uses the parent's file permissions and refuses changed targets. "
        "An interrupted matching team resumes unfinished assignments without repeating integrated files. "
        "A failed builder's last written content is kept and reported, not dropped, so the lead can repair "
        "it instead of starting over. "
        "The lead still owns combined tests, preview, repair, and final verification."
    )
    parameters = {
        "type": "object",
        "properties": {
            "assignments": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "maxLength": 200},
                        "instructions": {"type": "string", "maxLength": 8000},
                        "path": {"type": "string", "maxLength": 400},
                        "context_files": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
                        "model_choice": {
                            "type": "object",
                            "description": "Optional exact connected model profile and model ID for this file writer.",
                            "properties": {"profile": {"type": "string"}, "model_id": {"type": "string"}},
                            "required": ["profile", "model_id"],
                        },
                    },
                    "required": ["title", "instructions", "path"],
                },
            }
        },
        "required": ["assignments"],
    }

    def __init__(
        self,
        writer: Any,
        *,
        project: Any,
        model: str,
        provider: str,
        emit: Any,
        deadline: float,
        resolve_model: Any = None,
        channel_client: Any = None,
    ) -> None:
        self._writer, self._project = writer, project.resolve()
        self._model, self._provider, self._emit, self._deadline = model, provider, emit, deadline
        self._resolve_model = resolve_model
        self._running = False
        self._channel_client = channel_client if channel_client is not None else RunChannelClient.from_environment()

    def _assignments(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        items = args.get("assignments")
        if not isinstance(items, list) or not items:
            raise ValueError("assignments must contain at least one builder")
        jobs, paths = [], set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("each assignment must be an object")
            job = {}
            for key, limit in (("title", 200), ("instructions", 8000), ("path", 400)):
                value = item.get(key)
                if not isinstance(value, str) or not value.strip() or len(value) > limit:
                    raise ValueError(f"each assignment needs {key} with 1 to {limit} characters")
                job[key] = value.strip()
            job["path"] = relative_file(self._project, job["path"])
            if "context_files" in item:
                context = item["context_files"]
                if not isinstance(context, list) or len(context) > 100 or any(not isinstance(p, str) for p in context):
                    raise ValueError("context_files must contain at most 100 exact files")
                job["context_files"] = [relative_file(self._project, p) for p in context]
            if "model_choice" in item:
                choice = item["model_choice"]
                if (
                    not isinstance(choice, dict)
                    or set(choice) != {"profile", "model_id"}
                    or any(
                        not isinstance(choice[key], str) or not choice[key].strip() for key in ("profile", "model_id")
                    )
                ):
                    raise ValueError("model_choice needs exact profile and model_id strings")
                job["model_choice"] = {key: choice[key].strip() for key in ("profile", "model_id")}
            key = job["path"].casefold()
            if any(key == held or key.startswith(held + "/") or held.startswith(key + "/") for held in paths):
                raise ValueError("team assignments must have distinct, non-overlapping output files")
            paths.add(key)
            jobs.append(job)
        return jobs

    def _kept_copy(self, ledger: TeamLedger, index: int, job: dict[str, str]) -> str | None:
        """The path of a failed child's own last-written content, or None when it never wrote anything to keep.

        A private builder's workspace is never deleted on failure (``BuildWorkspace`` only ever writes into
        it), but ``BuildWorkspace.create`` also SNAPSHOTS the pre-existing target into it before the child
        runs -- so a file present at ``.../workspace/<path>`` is not proof the child wrote anything; it could
        be that untouched snapshot. Only a fingerprint that differs from the child's own recorded
        ``base_file`` (or a path that had no base at all) is the child's real work, kept instead of dropped.
        """
        child_id = ledger.data["children"][index].get("child_id")
        if not child_id:
            return None
        workspace_root = self._project / _BOOKKEEPING / child_id / "workspace"
        if not (workspace_root / job["path"]).is_file():
            return None
        current = current_fingerprint(workspace_root, job["path"])
        base_file = self._child_base_fingerprint(child_id)
        if base_file is not None and current == base_file:
            return None
        return f"{_BOOKKEEPING}/{child_id}/workspace/{job['path']}"

    def _child_base_fingerprint(self, child_id: str) -> str | None:
        """The fingerprint ``BuildWorkspace.create`` recorded for the assigned path before the child ran, or
        None when no receipt exists or the path had no pre-existing file."""
        receipt = self._project / _BOOKKEEPING / child_id / "receipt.json"
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = data.get("base_file")
        return value if isinstance(value, str) else None

    def _failure_summary(self, ledger: TeamLedger, succeeded: int, total: int) -> str:
        base = f"Only {succeeded}/{total} builders integrated; inspect failures and verify the combined project."
        notes = [
            _one_line(
                f"{child['path']}: kept the builder's last content at {child['kept_copy']} "
                f"({child.get('error') or 'builder failed'})"
            )
            for child in ledger.data["children"]
            if child.get("state") == "failed" and child.get("kept_copy")
        ]
        return base if not notes else base + " " + " ".join(notes)

    def _progress(self, ledger: TeamLedger, notice: str = "", *, failed: bool = False) -> None:
        if notice:
            self._emit(
                {
                    "fc": "meta",
                    "team_id": ledger.data["team_id"],
                    "text": notice,
                    "is_error": failed,
                    "model": self._model,
                }
            )
        summary = ledger.progress_snapshot()
        counts = " · ".join(
            f"{state} {summary[state]}"
            for state in ("queued", "running", "integrated", "failed", "cancelled", "interrupted")
        )
        wording = "Team settled with failures: " if summary["state"] == "failed" else "Team: "
        text = (
            f"{wording}{summary['integrated']}/{summary['total']} files integrated · {counts}. "
            "The lead still checks the combined project."
        )
        self._emit(
            {
                "fc": "planning",
                "name": "team-progress",
                "team_id": ledger.data["team_id"],
                "text": text[:260],
                "is_error": failed,
                "model": self._model,
                "team_progress": summary,
            }
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        if self._running:
            return ToolResult(ok=False, error="A team is already running in this Build pass; wait for its results")
        try:
            jobs = self._assignments(args)
            selections = [
                self._resolve_model(job.get("model_choice")) if self._resolve_model else (self._model, self._provider)
                for job in jobs
            ]
            recovered = TeamLedger.recover(self._project)
        except (OSError, ValueError) as exc:
            return ToolResult(ok=False, error=str(exc))
        self._running = True
        admission = None
        receipt = None
        try:
            with TeamLedger.start_or_resume(self._project, jobs, self._model) as ledger:
                receipt = str(ledger.folder / "team.json")
                allowance = BuildAllowance.for_machine(len(jobs))
                praxis = TeamPraxisBridge(self._project, ledger)
                for index, child in enumerate(ledger.data["children"]):
                    if child["state"] == "integrated":
                        praxis.integrated(index)
                admissions = {self._provider: shared_provider_admission(self._provider, team=ledger.data["team_id"])}
                admission = admissions[self._provider]
                for _, provider in selections:
                    if provider not in admissions:
                        admissions[provider] = shared_provider_admission(provider, team=ledger.data["team_id"])
                self._progress(ledger)
                if recovered:
                    self._progress(
                        ledger, f"Recovered {len(recovered)} abandoned teams; matching unfinished work is resuming"
                    )

                slots = asyncio.Semaphore(allowance.concurrent)

                async def build(index: int, job: dict[str, str]) -> None:
                    if ledger.data["children"][index]["state"] == "integrated":
                        return
                    async with slots:
                        await build_owned(index, job)

                async def build_owned(index: int, job: dict[str, str]) -> None:
                    bridge_id = None
                    if self._channel_client is not None:
                        admitted = await self._channel_client.call(
                            "admit_builder",
                            {
                                "plan_id": f"{ledger.data['team_id']}:{index}",
                                "title": job["title"],
                                "brief": job["instructions"],
                                "path": job["path"],
                            },
                        )
                        bridge_id = admitted["agent"]["agent_id"]
                        await self._channel_client.call(
                            "report_builder",
                            {
                                "agent_id": bridge_id,
                                "event": {"type": "started"},
                            },
                        )
                    ledger.update(index, "running")
                    if bridge_id is not None:
                        ledger.update(index, "running", praxis_agent_id=bridge_id)
                    self._progress(ledger)

                    def observe(event: dict[str, Any]) -> None:
                        if event.get("type") == "model_runtime":
                            ledger.update(
                                index,
                                "running",
                                model_used=str(event.get("model_used") or ""),
                                profile_used=str(event.get("profile_used") or ""),
                                provider_used=str(event.get("provider_used") or ""),
                            )
                        if "child_id" not in ledger.data["children"][index]:
                            child_id = str(event["child_id"])
                            ledger.update(
                                index, "running", child_id=child_id, receipt=f"{_BOOKKEEPING}/{child_id}/receipt.json"
                            )
                            self._progress(ledger)

                    try:
                        model, provider = selections[index]
                        options = {"request_admission": admissions[provider], "observe": observe}
                        if "model_choice" in job:
                            options["model_choice"] = job["model_choice"]
                        result = await self._writer.execute_assigned(job, **options)
                        integrated_file = current_fingerprint(self._project, job["path"]) if result.ok else None
                        if result.ok and not integrated_file:
                            raise ValueError(f"builder reported success without an integrated file: {job['path']}")
                        if bridge_id is not None:
                            actual_model = ledger.data["children"][index].get("model_used")
                            if actual_model:
                                await self._channel_client.call(
                                    "report_builder",
                                    {
                                        "agent_id": bridge_id,
                                        "event": {"type": "model_runtime", "model_used": actual_model},
                                    },
                                )
                            await self._channel_client.call(
                                "report_builder",
                                {
                                    "agent_id": bridge_id,
                                    "event": {"type": "integrated", "fingerprint": integrated_file}
                                    if result.ok
                                    else {"type": "failed", "error": str(result.error or "builder failed")[:1000]},
                                },
                            )
                        state = "integrated" if result.ok else "failed"
                        details = {
                            "result": str(result.data or "")[:4000],
                            "error": str(result.error or "")[:2000],
                            "integrated_file": integrated_file,
                            "model_requested": model,
                            "model_used": ledger.data["children"][index].get("model_used"),
                        }
                        kept_copy = None if result.ok else self._kept_copy(ledger, index, job)
                        if kept_copy:
                            details["kept_copy"] = kept_copy
                        ledger.update(index, state, **details)
                        if result.ok:
                            praxis.integrated(index)
                        notice = f"{job['title']}: {state} ({job['path']})"
                        if kept_copy:
                            notice += f" — kept its last content at {kept_copy}: {result.error or 'builder failed'}"
                        self._progress(ledger, _one_line(notice), failed=not result.ok)
                    except asyncio.CancelledError:
                        if bridge_id is not None:
                            try:
                                await self._channel_client.call(
                                    "report_builder",
                                    {
                                        "agent_id": bridge_id,
                                        "event": {"type": "cancelled"},
                                    },
                                )
                            except (OSError, RuntimeError, ValueError):
                                pass
                        ledger.update(index, "cancelled", error="Team cancelled before this builder completed")
                        raise
                    except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError) as exc:
                        if bridge_id is not None:
                            try:
                                await self._channel_client.call(
                                    "report_builder",
                                    {
                                        "agent_id": bridge_id,
                                        "event": {"type": "failed", "error": str(exc)[:1000]},
                                    },
                                )
                            except (OSError, RuntimeError, ValueError):
                                pass
                        kept_copy = self._kept_copy(ledger, index, job)
                        details = {"error": str(exc)[:2000]}
                        if kept_copy:
                            details["kept_copy"] = kept_copy
                        ledger.update(index, "failed", **details)
                        notice = f"{job['title']}: failed: {exc}"
                        if kept_copy:
                            notice += f" — kept its last content at {kept_copy}"
                        self._progress(ledger, _one_line(notice), failed=True)

                def record_interruption(exc: BaseException) -> None:
                    for held in admissions.values():
                        held.close()
                    for child in ledger.data["children"]:
                        if child["state"] in {"queued", "running"}:
                            child.update(state="cancelled", error="Team stopped before completion")
                    state = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
                    ledger.finish(
                        state,
                        admission=admission.snapshot(),
                        admissions={key: held.snapshot() for key, held in admissions.items()},
                        allowance=allowance.snapshot(),
                        error=str(exc) or type(exc).__name__,
                    )
                    self._progress(ledger, failed=state == "failed")

                try:
                    await run_owned_builders(jobs, build, deadline=self._deadline, team_id=ledger.data["team_id"])
                except asyncio.CancelledError as exc:
                    record_interruption(exc)
                    raise
                except Exception as exc:
                    log.exception("Build team stopped before every helper completed")
                    record_interruption(exc)
                    raise
                finally:
                    for held in admissions.values():
                        held.close()
                succeeded = sum(child["state"] == "integrated" for child in ledger.data["children"])
                ok = succeeded == len(jobs)
                praxis_report = praxis.report()
                ledger.finish(
                    "completed" if ok else "failed",
                    admission=admission.snapshot(),
                    admissions={key: held.snapshot() for key, held in admissions.items()},
                    allowance=allowance.snapshot(),
                    praxis=praxis_report,
                    acceptance_state=praxis_report["acceptance_state"],
                )
                self._progress(
                    ledger,
                    "Files integrated; independent acceptance remains unverified until the lead checks the combined project",
                )
                self._progress(ledger, failed=not ok)
                return ToolResult(
                    ok=ok,
                    data={
                        "team_id": ledger.data["team_id"],
                        "integrated": succeeded,
                        "total": len(jobs),
                        "receipt": receipt,
                        "children": [
                            {
                                key: child.get(key)
                                for key in (
                                    "title",
                                    "path",
                                    "state",
                                    "error",
                                    "receipt",
                                    "model_requested",
                                    "model_used",
                                    "profile_used",
                                    "provider_used",
                                    "kept_copy",
                                )
                            }
                            for child in ledger.data["children"]
                        ],
                        "admission": admission.snapshot(),
                        "admissions": {key: held.snapshot() for key, held in admissions.items()},
                        "allowance": allowance.snapshot(),
                        "praxis": praxis_report,
                        "acceptance_state": praxis_report["acceptance_state"],
                    },
                    error=None if ok else self._failure_summary(ledger, succeeded, len(jobs)),
                )
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError, TimeoutError) as exc:
            location = f"; work and final receipt at {receipt}" if receipt else ""
            return ToolResult(
                ok=False,
                data={"receipt": receipt} if receipt else None,
                error=f"Team did not complete: {str(exc) or type(exc).__name__}{location}",
            )
        finally:
            if admission is not None:
                admission.close()
            self._running = False
