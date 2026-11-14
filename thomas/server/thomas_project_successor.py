"""Carry an exhausted repair into a new team without copying away its unfinished work."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import green_checkout
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.routes import autopilot_goal

log = logging.getLogger(__name__)


def successor_id(project_root: Path, catalog_root: Path, cid: str) -> str:
    """Read the old project's durable successor link from work or the catalog."""
    for root in (project_root, catalog_root):
        conversation = forge_code_store.load_conversation(root, cid)
        project = conversation.get("thomas_project") if isinstance(conversation, dict) else None
        successor = project.get("successor") if isinstance(project, dict) else None
        if isinstance(successor, dict) and successor.get("conversation_id"):
            return str(successor["conversation_id"])
    return _started_successor(project_root, catalog_root, cid)


def _started_successor(project_root: Path, catalog_root: Path, cid: str) -> str:
    """Recover a bound successor when its start succeeded but the old link was not written."""
    for summary in forge_code_store.list_conversations(project_root):
        candidate_id = str(summary.get("id") or "")
        if not candidate_id or candidate_id == cid:
            continue
        candidate = forge_code_store.load_conversation(project_root, candidate_id)
        record = candidate.get("thomas_project") if isinstance(candidate, dict) else None
        if not isinstance(record, dict) or record.get("continued_from") != cid:
            continue
        binding = forge_code_projects.conversation_metadata(catalog_root, candidate_id)
        if binding and Path(str(binding.get("project_root") or "")).resolve() == project_root.resolve():
            return candidate_id
    return ""


def successor_greens() -> set[str]:
    """Reserve a recorded successor's green between Build runs, even after Chat restarts."""
    from thomas.server import thomas_project

    catalog_root = thomas_project._catalog_root()
    root = green_checkout.green_root()
    work = root / "work"
    if not work.is_dir():
        return set()
    reserved = set()
    for folder in work.iterdir():
        if not folder.is_dir():
            continue
        conversations = folder / ".thomas" / "evolve" / "agent" / "conversations"
        for file in conversations.glob("*.json"):
            try:
                value = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            project = value.get("thomas_project") if isinstance(value, dict) else None
            successor = project.get("successor") if isinstance(project, dict) else None
            cid = successor.get("conversation_id") if isinstance(successor, dict) else None
            if (
                cid
                and (root / "git" / folder.name).is_dir()
                and thomas_project.project_phase(folder, catalog_root, str(cid))[0] != "ended"
            ):
                reserved.add(folder.name)
                break
    return reserved


async def carry_exhausted(
    app: Any, project_root: Path, catalog_root: Path, cid: str, *, why: str, detail: str, sid: str
) -> dict[str, Any] | None:
    """Start a successor in the same green; keep the old record retryable if its start fails."""
    from thomas.server import thomas_project

    previous = await asyncio.to_thread(forge_code_store.load_conversation, catalog_root, cid)
    if isinstance(previous, dict) and isinstance(previous.get("thomas_project"), dict):
        recorded = previous["thomas_project"].get("successor")
        if isinstance(recorded, dict) and recorded.get("conversation_id"):
            return recorded
    conversation = await asyncio.to_thread(forge_code_store.load_conversation, project_root, cid)
    if not isinstance(conversation, dict):
        return None
    project = conversation.get("thomas_project")
    if not isinstance(project, dict) or not project.get("repairs_spent"):
        return None
    successor = project.get("successor")
    if isinstance(successor, dict) and successor.get("conversation_id"):
        return successor
    green = await asyncio.to_thread(green_checkout.find_green, str(project.get("execution_id") or ""))
    if green is None or green.work != project_root:
        return None
    existing = await asyncio.to_thread(_started_successor, project_root, catalog_root, cid)
    if existing:
        successor = {"conversation_id": existing, "execution_id": green.execution_id}
        project["successor"] = successor
        await asyncio.to_thread(forge_code_store.write_conversation, project_root, conversation)
        if isinstance(previous, dict) and isinstance(previous.get("thomas_project"), dict):
            previous["thomas_project"]["successor"] = successor
            await asyncio.to_thread(forge_code_store.write_conversation, catalog_root, previous)
        return successor
    goal = autopilot_goal.goal_text(conversation.get("turns") or [])
    if not goal:
        return None
    from thomas.server.routes.autopilot_sent_back import findings_notes, sent_back_rounds

    inherited = [dict(round_) for round_ in sent_back_rounds(conversation)]
    inherited.append({"round": len(inherited) + 1, "why": why, "detail": detail, "sid": sid})
    request = (
        f"{goal}\n\nThis is a fresh project continuing the unfinished change already in this project folder. "
        "Do not rebuild it from scratch. Review and repair the existing files before handing it in.\n"
        f"Earlier hand-in: {sid or 'none'}; earlier conversation: {cid}.\n\n"
        f"{findings_notes(inherited)}"
    )
    metadata = await asyncio.to_thread(forge_code_projects.conversation_metadata, catalog_root, cid)
    bound = (metadata or {}).get("settings") or {}
    prior_project = previous.get("thomas_project") if isinstance(previous, dict) else None
    if not bound and isinstance(prior_project, dict):
        bound = prior_project.get("bound_settings") or {}
    # A handed-in conversation can be rebound by each repair; older records nest `requested` each time.
    while isinstance(bound, dict) and isinstance(bound.get("requested"), dict):
        bound = bound["requested"]
    settings = bound if isinstance(bound, dict) else {}
    port = app.get(APP_LOCAL_PORT)
    if not port:
        return None
    try:
        started = await thomas_project.start_thomas_project(
            app,
            request=request,
            settings=dict(settings),
            port=port,
            green=green,
            meta={
                "continued_from": cid,
                "unfinished_review": {"why": why, "detail": detail, "sid": sid},
                "chat_session_id": project.get("chat_session_id"),
                "inherited_repairs": inherited,
            },
        )
    except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError):
        log.exception("could not carry exhausted repair for %s; the green remains for retry", cid)
        return None
    successor = {"conversation_id": started["conversation_id"], "execution_id": green.execution_id}
    project["successor"] = successor
    await asyncio.to_thread(forge_code_store.write_conversation, project_root, conversation)
    if isinstance(previous, dict) and isinstance(previous.get("thomas_project"), dict):
        previous["thomas_project"]["successor"] = successor
        await asyncio.to_thread(forge_code_store.write_conversation, catalog_root, previous)
    return successor
