"""Run-bound review, application and exact pre-image recovery for Edit Thomas."""

from __future__ import annotations

import asyncio
import difflib
import json
from pathlib import Path

from aiohttp import web

from thomas.forge.anvil import forge_code_redesign_undo as undo
from thomas.forge.anvil import forge_code_self_edit as isolation
from thomas.forge.anvil import forge_code_store
from thomas.forge.anvil.forge_code_self_edit_integration import apply_with_undo

from .evolve_agent_run_state import APP_EVOLVE_AGENT_LOCK, runs, slot_active
from .evolve_agent_self_edit_policy import validate_delta
from .evolve_agent_self_edit_runs import candidate_for, public_record, read_record, save_record


def apply_record(catalog: Path, record: dict) -> dict:
    if record["status"] == "applied":
        return public_record(record)
    if record["status"] != "ready":
        raise isolation.SelfEditSnapshotError("Only a reviewed, verified candidate can be applied")
    candidate = candidate_for(record)
    changed = isolation.candidate_delta_since(candidate.candidate_root, candidate.baseline)
    validate_delta(candidate, record["scope"], changed)
    if changed != record["changed_files"]:
        raise isolation.SelfEditSnapshotError("Candidate changed after review")
    receipt = isolation.CandidateCheckReceipt(**record["receipt"])
    commands = tuple(tuple(c) for c in record["commands"])
    journal = isolation.prepare_source_application(candidate, receipt, commands, tuple(changed))
    record.update(status="recovery_required", application_journal=str(journal), reason="Applying verified changes")
    save_record(catalog, record)
    apply_with_undo(
        candidate,
        receipt,
        commands,
        journal,
        tuple(changed),
        catalog_root=catalog,
        conversation_id=record["conversation_id"],
        run_id=record["run_id"],
    )
    record.update(
        status="applied",
        reason="Applied. Restart Thomas to load and test the changes.",
        python_changed=any(p.endswith(".py") for p in changed),
    )
    save_record(catalog, record)
    return public_record(record)


def recover_record(catalog: Path, record: dict) -> dict:
    if record["status"] == "applied":
        undo.restore_run_preimages(Path(record["source_root"]), catalog, record["conversation_id"], record["run_id"])
    elif record["status"] == "recovery_required":
        candidate = candidate_for(record)
        receipt = isolation.CandidateCheckReceipt(**record["receipt"])
        commands = tuple(tuple(c) for c in record["commands"])
        isolation.rollback_source_application(
            candidate, receipt, commands, Path(record["application_journal"]), tuple(record["changed_files"])
        )
    elif record["status"] == "undone":
        return public_record(record)
    else:
        raise isolation.SelfEditSnapshotError("There is no application to undo")
    record.update(
        status="undone", reason="The exact original files were restored. Restart to load them.", runtime_verified=False
    )
    save_record(catalog, record)
    return public_record(record)


def review_record(record: dict) -> str:
    candidate = candidate_for(record)
    changed = isolation.candidate_delta_since(candidate.candidate_root, candidate.baseline)
    validate_delta(candidate, record["scope"], changed)
    parts = []
    for name in changed:
        before, after = candidate.source_root / name, candidate.candidate_root / name
        old = before.read_text(encoding="utf-8").splitlines(True) if before.is_file() else []
        new = after.read_text(encoding="utf-8").splitlines(True) if after.is_file() else []
        parts.extend(difflib.unified_diff(old, new, fromfile=name, tofile=name + " (candidate)"))
    return "".join(parts)[:250_000]


def build_self_edit_handlers(app, *, require_api_access, catalog_root, load_conversation):
    def owned(cid, run_id):
        source, conv = load_conversation(cid)
        if not conv or not conv.get("self_edit"):
            raise isolation.SelfEditSnapshotError("This task is not an Edit Thomas task")
        record = read_record(catalog_root(), cid, run_id)
        if Path(record["source_root"]).resolve() != source.resolve():
            raise isolation.SelfEditSnapshotError("Task and source identities do not match")
        return record

    async def status(request):
        require_api_access(request)
        try:
            cid, run_id = request.match_info["cid"], request.query.get("run_id", "")
            record = owned(cid, run_id)
            result = public_record(record)
            if record["status"] == "running" and not slot_active(runs(app).get(cid)):
                result.update(status="failed", reason="The process ended before its result was recorded")
            if request.query.get("review") == "1":
                result["diff"] = await asyncio.to_thread(review_record, record)
            return web.json_response({"ok": True, **result})
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    async def action(request):
        require_api_access(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("A task and run are required")
            cid, run_id = str(body.get("conversation_id") or ""), str(body.get("run_id") or "")
            async with app[APP_EVOLVE_AGENT_LOCK]:
                record = owned(cid, run_id)
                if any(slot_active(slot) for slot in runs(app).values()):
                    raise isolation.SelfEditSnapshotError("Wait for active Build runs to finish")
                kind = request.match_info["action"]
                if kind == "apply":
                    result = await asyncio.to_thread(apply_record, catalog_root(), record)
                elif kind == "undo":
                    result = await asyncio.to_thread(recover_record, catalog_root(), record)
                elif kind == "discard" and record["status"] in {"ready", "failed"}:
                    await asyncio.to_thread(isolation.discard_candidate, Path(record["candidate_root"]))
                    record.update(status="discarded", reason="Private candidate discarded; live source was unchanged")
                    save_record(catalog_root(), record)
                    result = public_record(record)
                else:
                    raise ValueError("This action is not available for this run")
                saved = forge_code_store.update_self_edit_turn(Path(record["source_root"]), cid, run_id, result)
                if saved is None:
                    raise RuntimeError(
                        "Source action was recorded, but task history could not be updated; refresh status before retrying"
                    )
                return web.json_response({"ok": True, **result})
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)

    return {"self_edit_status": status, "self_edit_action": action}
