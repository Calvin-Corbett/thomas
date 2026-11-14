"""Open the Build session that a chat-dispatched code task is watched through.

A code task is supposed to create a Build session you can open and follow,
attached to whichever agent picked it up. It did not. Chat dispatch ran the task
in ``~/.thomas/workspaces/exec-<id>`` -- a bare directory, not a project and not
a git repo -- while Build lists conversations under the project roots that
``forge_code_projects.conversation_roots()`` returns. Nothing wrote the record
that joins them, so Build stayed empty for the whole life of a real run.

This module is that missing join, and it is deliberately the same three calls
the Build-initiated path already makes in ``evolve_agent_conversation_routes``:
mint the task its own project, start a conversation in it, bind the conversation
so the catalog can find the project again. Binding is the load-bearing step --
``conversation_roots`` reads the registry that ``bind_conversation`` writes, so
an unbound conversation is one the person cannot open.

Only a coding task opens a session. A document or an image is a deliverable you
receive, not a build you watch, and minting a git project for one would put
empty folders in the person's data directory.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.core import project_root as _project_root
from thomas.forge.anvil import forge_code_projects, forge_code_store

log = logging.getLogger(__name__)

# The validated enum values that mean "this is something you watch get built".
# Dispatch is an executor, not an intent classifier: this reads a checked field,
# never the wording of the prompt.
BUILD_SPECIALISTS: frozenset[str] = frozenset({"coding"})


def open_build_session(
    *,
    specialist_id: str,
    targets_live_repo: bool,
    title: str,
    catalog_root: str | Path,
) -> dict[str, Any] | None:
    """Create the project and Build session for a code task.

    Returns ``{"project_root", "conversation_id"}``, or ``None`` when this task
    is not one you watch get built. A self-development task is excluded on
    purpose: it runs in green and is gated separately, so minting a project
    folder for it would be a side effect nobody asked for.

    Raises whatever ``forge_code_projects`` raises. The caller decides what a
    failure to open the session means; it must not take the task down with it.
    """
    if targets_live_repo:
        return None
    if str(specialist_id or "").strip().lower() not in BUILD_SPECIALISTS:
        return None

    project_root = forge_code_projects.project_for_new_task(title)
    conversation = forge_code_store.new_conversation(project_root, title=title or None)
    conversation_id = str(conversation.get("id") or "")
    forge_code_projects.bind_conversation(catalog_root, conversation_id, project_root)
    return {"project_root": str(project_root), "conversation_id": conversation_id}


@dataclass(frozen=True)
class WorkspacePlan:
    """Where a delegated task runs, and the Build session it is watched through.

    ``build_session_error`` carries the reason a session could not be opened. It
    is kept rather than discarded so the failure can be reported: a task that
    quietly runs somewhere other than where the person was told to look is the
    bug this module exists to end.
    """

    work_dir: Path
    is_project: bool = False
    project_root: str = ""
    conversation_id: str = ""
    build_session_error: str = ""
    # Set when a self-fix could not get its private copy. The task must fail
    # with this text; running it in the live checkout instead is the bug.
    refusal: str = ""


def prepare_workspace(
    *,
    specialist_id: str,
    targets_live_repo: bool,
    title: str,
    repo_root: str | Path,
    execution_id: str,
    task_workspace: Callable[[str], Path],
    catalog_root: str | Path | None = None,
    spare: Iterable[str] = (),
) -> WorkspacePlan:
    """Decide where this task runs, opening a Build session when it deserves one.

    Self-development runs in green, a private clone of what the live checkout has
    committed (``green_checkout``); its change reaches the running Thomas only
    through the commit-master and your approval. A code task gets its own project
    so Build can show it. Everything else keeps the plain per-task workspace it
    has always had.

    A Build session that cannot be opened must never take the task down with it:
    Rule 0 says nothing stops because of a thing nobody engineered past. The work
    falls back to the plain workspace and the reason travels with the plan.
    Green is the opposite case: without it a self-fix would edit the running
    copy, so the plan carries a refusal and the task fails. The sweep spares
    active Build runs and greens awaiting your verdict.
    """
    if targets_live_repo:
        from thomas.server import green_checkout

        try:
            # Spare greens used by Build and greens held for your verdict.
            from thomas.server import green_handoff

            green_checkout.sweep(skip={*spare, *green_handoff.held()})
        except OSError:
            log.warning("green sweep failed", exc_info=True)
        try:
            green = green_checkout.create_green(Path(repo_root), execution_id)
        except green_checkout.GreenUnavailable as exc:
            log.warning("No green for self-development task %s: %s", execution_id, exc)
            return WorkspacePlan(
                work_dir=Path(task_workspace(execution_id)),
                refusal=(
                    "Thomas could not make a private copy of his code to work in, so he changed "
                    f"nothing. Self-fixes are never made in the running copy. ({exc})"
                ),
            )
        return WorkspacePlan(work_dir=green.work)

    if catalog_root is None:
        # The same resolver Build's own listing uses. Computing this root a
        # second way is how one reader ends up walking a different tree from
        # the other and an empty answer reads as clean.
        catalog_root = _project_root.code_checkout()

    error = ""
    session: dict[str, Any] | None = None
    try:
        session = open_build_session(
            specialist_id=specialist_id,
            targets_live_repo=False,
            title=title,
            catalog_root=catalog_root,
        )
    except (forge_code_projects.ForgeCodeProjectError, OSError, ValueError) as exc:
        # Losing the session costs you the window into the run; losing the run
        # would cost you the work. Keep the work.
        log.warning("Could not open a Build session for %s: %s", execution_id, exc, exc_info=True)
        error = str(exc)

    if session:
        project_root = str(session.get("project_root") or "")
        conversation_id = str(session.get("conversation_id") or "")
        # So the run that follows is recorded on the session the person was just
        # told to watch. Without this the session opens and stays empty.
        from thomas.server.chat_delegation_build_transcript import remember_build_session

        remember_build_session(execution_id, project_root, conversation_id)
        return WorkspacePlan(
            work_dir=Path(project_root),
            is_project=True,
            project_root=project_root,
            conversation_id=conversation_id,
        )
    return WorkspacePlan(work_dir=Path(task_workspace(execution_id)), build_session_error=error)


async def prepare_workspace_async(*, app: Any = None, **kwargs: Any) -> WorkspacePlan:
    """Read active runs on the event loop, then prepare the workspace off it."""
    if app is not None and kwargs.get("targets_live_repo") is True:
        from thomas.server.chat_self_project import _greens_in_use
        from thomas.server.thomas_project_successor import successor_greens

        # Snapshot active runs on the loop; scan persisted successor links off it.
        active = _greens_in_use(app, reserved=set())
        kwargs["spare"] = active | await asyncio.to_thread(successor_greens)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(prepare_workspace, **kwargs))
