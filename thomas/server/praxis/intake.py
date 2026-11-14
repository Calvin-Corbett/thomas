"""Route a structured Chat code task into a real, durable Build conversation."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
from thomas.core.coding_agents import builtin_registry
from thomas.core.event_loop_offload import off_loop
from thomas.core.praxis.dispatch_validate import MAX_REPAIRS, validate_dispatch
from thomas.core.project_root import code_checkout as _default_repo_root
from thomas.core.project_root import coordination_root
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.marketplace.orchestrator.bot_roster import pick_bot_for_specialist
from thomas.server.chat_delegation_emitter import _DelegationEmitter
from thomas.server.chat_delegation_session import _normalize_record
from thomas.server.praxis.evaluation import evaluate_acceptance
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN, APP_PRAXIS_STOP_CODE_RUN

log = logging.getLogger(__name__)


def _verifier_receipts(report: dict[str, Any], project: Path) -> list[dict[str, Any]]:
    """Accept only persisted verifier receipts with an existing local evidence file."""
    raw = report.get("verifier_receipts")
    if not isinstance(raw, list):
        return []
    root = project.resolve()
    verified = []
    for receipt in raw:
        if not isinstance(receipt, dict) or receipt.get("source") != "verifier":
            continue
        ref = str(receipt.get("evidence_ref") or "").strip()
        if not ref:
            continue
        path = (root / ref).resolve()
        if path.is_relative_to(root) and path.is_file():
            verified.append(receipt)
    return verified


def _settle_build(
    finished: dict[str, Any], acceptance: list[dict[str, Any]], instructions: str, project: Path
) -> dict[str, Any]:
    report = finished.get("report")
    if not isinstance(report, dict):
        report = {}
    receipts = _verifier_receipts(report, project)
    verdict = evaluate_acceptance(
        acceptance,
        receipts,
        instructions=instructions,
        observed_evidence_refs=[str(receipt["evidence_ref"]) for receipt in receipts],
        require_child_reports=False,
    )
    if not acceptance:
        changed = {str(name) for name in (finished.get("changed_files") or [])}
        covered = {
            str(name)
            for receipt in receipts
            if receipt.get("status") == "pass"
            for name in (receipt.get("covered_files") if isinstance(receipt.get("covered_files"), list) else [])
        }
        root = project.resolve()
        files_exist = all(
            (root / name).resolve().is_relative_to(root) and (root / name).resolve().is_file() for name in changed
        )
        verified = (
            bool(changed)
            and files_exist
            and changed <= covered
            and bool(receipts)
            and all(receipt.get("status") == "pass" for receipt in receipts)
        )
        verdict["state"] = "completed" if verified else "completed_unverified"
    if report.get("open_risks"):
        verdict["state"] = "completed_unverified"
    verdict["verifier_receipts"] = len(receipts)
    return verdict


#: What Chat's delegation ran before it had a model or agent choice to forward.
DEFAULT_DELEGATION_MODEL_ID = "gpt-5.6-sol"


def build_choice(payload: dict[str, Any]) -> dict[str, str]:
    """The agent and model a Chat turn asked its Build hand-off to run on.

    ``build_agent`` is the Agent picker next to Chat's model picker; empty lets
    Build's registry choose, which keeps Thomas's own loop the default. The model
    is only ever an explicit ``build_model_id``: Chat's own model may be one Build
    cannot run (a local qwen), and forwarding it would turn a working hand-off
    into a refusal. Chat sends one with a pick — the chip's model, which the
    picker has checked that agent runs (chat_stream_actions.js).
    """
    return {
        "agent": str(payload.get("build_agent") or "").strip(),
        "model_id": str(payload.get("build_model_id") or "").strip(),
    }


def delegation_model_id(choice: dict[str, str]) -> str:
    """The model a hand-off runs: Chat's, else the picked agent's own default, else GPT-5.6 Sol.

    Always sending GPT-5.6 Sol with no model meant a Claude Code pick was refused
    every time (HTTP 400, "Claude Code cannot run gpt-5.6-sol"): the agent was
    forwarded and the one model it could never run went with it.
    """
    if choice.get("model_id"):
        return choice["model_id"]
    spec = builtin_registry().get(choice.get("agent") or "")
    return (spec.default_model if spec is not None else "") or DEFAULT_DELEGATION_MODEL_ID


async def submit_build_task(
    app: Any,
    *,
    session_id: str,
    title: str,
    instructions: str,
    emit_event: Any,
    port: int,
    acceptance: list[dict[str, Any]] | None = None,
    kind: str = "code",
    surface: str = "task",
    deliverable_format: str = "",
    project: dict[str, Any] | None = None,
    choice: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a Chat card now, then launch and read back its Build result.

    ``choice`` (:func:`build_choice`) carries Chat's agent and model picks to
    Build, which obeys an agent pick exactly or refuses it with a sentence.
    """
    picked = choice or {}
    requested_project = project or {"mode": "new"}
    known_projects: dict[str, Path] = {}
    source_ids: list[str] = []
    if requested_project.get("mode") == "existing":
        catalog_root = _default_repo_root()
        # Resolving every registered project folder is filesystem work, and this
        # runs inside a chat turn on the server's loop.
        roots = await off_loop("build_intake.project_roots", forge_code_projects.conversation_roots, catalog_root)
        known_projects = {str(path.resolve()): path for path in roots}
        source_root = forge_code_projects.thomas_source_repo_root()
        source_ids = [str(source_root)] if source_root is not None else []
    verdict = validate_dispatch(
        {
            "instructions": instructions,
            "surface": surface,
            "kind": kind,
            "deliverable_format": deliverable_format,
            "needs_build": True,
            "project": requested_project,
            "acceptance": acceptance or [],
        },
        known_project_ids=known_projects,
        thomas_source_project_ids=source_ids,
        # There is no repair loop here: chat sends one structured send_task and
        # this either dispatches it or does not. So the repair budget is not
        # untouched, it is already spent -- there is no second attempt to spend
        # it on. Left at the default of 0, `dispatch_anyway` could never become
        # True, the escape hatch was unreachable code, and an ordinary request
        # ("build dice.html and check the button") was refused outright with
        # `uncited_acceptance`. A validator that can refuse forever is Thomas
        # saying it cannot do something, which Rule 0 forbids. Saying the budget
        # is spent makes the designed behaviour reachable: the task goes out,
        # uncited acceptance items are dropped, and the end state degrades to
        # completed_unverified rather than the work never starting.
        repair_attempts=MAX_REPAIRS,
    )
    if not verdict.may_dispatch:
        raise ValueError("Build task needs correction: " + ", ".join(verdict.errors))
    start = app.get(APP_PRAXIS_START_CODE_RUN)
    if start is None:
        raise RuntimeError("Build is not available in this Thomas server")
    root = coordination_root(None, "isolated")
    bot = pick_bot_for_specialist("coding")
    profile = {"needs_build": True, "acceptance": acceptance or []}
    row = task_bot_runtime.create_execution(
        session_id=session_id,
        summary=title,
        intent="chat_task",
        scope=["coding"],
        visibility="background",
        bot_id=bot.id,
        backend_type="praxis_build",
        runtime_profile=profile,
        actor="thomas-worker",
        repo_root=root,
    )
    eid = str(row["execution_id"])
    for state in ("classified", "queued", "claimed", "executing"):
        row = task_bot_runtime.update_execution(
            eid,
            state=state,
            actor="thomas-worker",
            repo_root=root,
            progress_summary="Starting a Build session" if state == "executing" else None,
        )
    emitter = _DelegationEmitter(emit_event)
    await emitter.started(_normalize_record(row), specialist_id="coding", bot=bot)

    async def work() -> None:
        async def stop_if_requested(run_id: str = "") -> bool:
            if not task_bot_runtime.is_cancel_requested(eid, repo_root=root):
                return False
            stop = app.get(APP_PRAXIS_STOP_CODE_RUN)
            if run_id and stop is not None:
                await stop(run_id)
            cancelled = task_bot_runtime.cancel_execution(eid, actor="user", repo_root=root)
            await emitter.progress(_normalize_record(cancelled), specialist_id="coding", bot=bot, text="Stopped by you")
            return True

        try:
            body = {
                "message": instructions,
                "model_id": delegation_model_id(picked),
                "request_id": f"praxis:{eid}",
                "acceptance": acceptance or [],
            }
            if picked.get("agent"):
                body["agent"] = picked["agent"]
            if requested_project.get("mode") == "existing":
                body["project_root"] = str(known_projects[str(requested_project["id"])])
                body["project_choice"] = "picked"
            while True:
                if await stop_if_requested():
                    return
                status, result = await start(body, port=port)
                if status == 409 and result.get("code") == "agent_already_running":
                    row = task_bot_runtime.update_execution(
                        eid,
                        progress_summary="Waiting to start Build",
                        heartbeat=True,
                        actor="thomas-worker",
                        repo_root=root,
                    )
                    await emitter.progress(
                        _normalize_record(row), specialist_id="coding", bot=bot, text="Starting Build"
                    )
                    await asyncio.sleep(2)
                    continue
                if status >= 400 or not result.get("ok"):
                    raise RuntimeError(str(result.get("error") or f"Build start failed ({status})"))
                break
            project = Path(str(result["project_root"]))
            cid, run_id = str(result["conversation_id"]), str(result["run_id"])
            if await stop_if_requested(run_id):
                return
            linked = {
                **profile,
                "build_conversation_id": cid,
                "build_run_id": run_id,
                "build_project_root": str(project),
            }
            row = task_bot_runtime.update_execution(
                eid,
                runtime_profile=linked,
                progress_summary="Building the project",
                heartbeat=True,
                actor="thomas-worker",
                repo_root=root,
            )
            await emitter.progress(_normalize_record(row), specialist_id="coding", bot=bot, text="Building the project")
            while True:
                await asyncio.sleep(2)
                if await stop_if_requested(run_id):
                    return
                conversation = await asyncio.to_thread(forge_code_store.load_conversation, project, cid)
                turns = conversation.get("turns", []) if isinstance(conversation, dict) else []
                finished = next(
                    (
                        turn
                        for turn in turns
                        if turn.get("role") == "agent"
                        and turn.get("run_id") == run_id
                        and turn.get("returncode") is not None
                    ),
                    None,
                )
                if finished is None:
                    task_bot_runtime.update_execution(eid, heartbeat=True, actor="thomas-worker", repo_root=root)
                    continue
                if finished.get("ok") and finished.get("changed_files"):
                    settlement = _settle_build(finished, acceptance or [], instructions, project)
                    row = task_bot_runtime.update_execution(
                        eid,
                        runtime_profile={**linked, "build_acceptance": settlement},
                        actor="thomas-worker",
                        repo_root=root,
                    )
                    if settlement["state"] != "completed":
                        reason = "Build made changes; verification is incomplete"
                        row = task_bot_runtime.fail_execution(
                            eid,
                            actor="thomas-worker",
                            summary=reason,
                            blocker="build_unverified",
                            repo_root=root,
                        )
                        await emitter.failed(_normalize_record(row), specialist_id="coding", bot=bot, text=reason)
                        return
                    row = task_bot_runtime.complete_execution(
                        eid,
                        actor="thomas-worker",
                        summary="Build finished; open the project to review it",
                        verified_success=True,
                        repo_root=root,
                    )
                    await emitter.completed(_normalize_record(row), specialist_id="coding", bot=bot)
                else:
                    reason = str(finished.get("reason") or "Build ended without a verified project change")
                    row = task_bot_runtime.fail_execution(
                        eid,
                        actor="thomas-worker",
                        summary=reason,
                        blocker="build_incomplete",
                        repo_root=root,
                    )
                    await emitter.failed(_normalize_record(row), specialist_id="coding", bot=bot, text=reason)
                return
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
            log.exception("Praxis Build handoff failed for %s", eid)
            row = task_bot_runtime.fail_execution(
                eid,
                actor="thomas-worker",
                summary=str(exc),
                blocker="build_handoff_failed",
                repo_root=root,
            )
            await emitter.failed(_normalize_record(row), specialist_id="coding", bot=bot, text=str(exc))

    asyncio.create_task(work(), name=f"praxis-build:{eid}")
    return _normalize_record(row)
