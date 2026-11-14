"""Choose an isolated Code project while preserving deliberate project selection."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_projects

log = logging.getLogger(__name__)


def unspecified_project_root(root: Path, *, _is_thomas_source: Callable[[Any], bool]) -> Path:
    """Where a Code conversation goes when the user chose no project.

    Never Thomas's own source. That used to be the fallback, so any turn
    arriving without a project -- including one whose JSON failed to parse and
    was treated as an empty body -- silently bound the product tree and returned
    200, which is how a worker's deliverable ends up written beside the code
    that wrote it.

    A configured root that is some other repository is a deliberate choice and
    is still honoured. But it must actually be bindable: in an installed copy
    the computed root is the package's parent directory, which is not a
    repository at all, and failing there would leave someone unable to start
    anything. Scratch is the answer in both cases.
    """
    if not _is_thomas_source(root):
        try:
            return forge_code_projects.validate_project_root(root, fallback=root)
        except forge_code_projects.ForgeCodeInspectionUnavailable:
            raise
        except forge_code_projects.ForgeCodeProjectError:
            pass
    return forge_code_projects.default_scratch_project(root)


def new_task_project_root(root: Path, task: str, *, _is_thomas_source: Callable[[Any], bool]) -> Path:
    """Where a NEW Code task goes when nobody picked a project: its own folder.

    This is ``_unspecified_project_root`` with the shared drawer taken out of it.
    That drawer was one ~/.thomas/code_scratch for everybody, and it is where a
    task landed whenever the catalog root was Thomas's own source (every dev
    install) or was not a repository at all (every packaged install) -- which is
    to say, always. Measured on this workspace: 106 tasks bound to that single
    directory, index.html written by five different tasks each silently replacing
    the last, four of the owner's builds gone and the only surviving trace an
    orphaned stylesheet whose page no longer exists. Making the overwrite visible
    was not enough; the tasks have to stop landing on top of each other.

    A catalog root that IS a separate repository is still honoured, unchanged:
    that is somebody deliberately pointing Thomas at a project, not the absence
    of a choice.

    Only NEW tasks reach here. A conversation that is already bound is loaded
    from the registry first, so nothing existing moves.

    Falling back to the shared scratch when a folder cannot be made is
    deliberate when creation fails without an inconclusive git inspection.
    An inconclusive git inspection is different: it must stop project selection.
    """
    if not _is_thomas_source(root):
        try:
            return forge_code_projects.validate_project_root(root, fallback=root)
        except forge_code_projects.ForgeCodeInspectionUnavailable:
            raise
        except forge_code_projects.ForgeCodeProjectError:
            pass
    try:
        return forge_code_projects.project_for_new_task(task)
    except forge_code_projects.ForgeCodeInspectionUnavailable:
        raise
    except forge_code_projects.ForgeCodeProjectError:
        log.warning("a per-task Code project could not be created; using shared scratch", exc_info=True)
        return forge_code_projects.default_scratch_project(root)


def _chosen_project(requested: Any, *, picked: bool = False) -> Any:
    """Drop a "choice" that is only a leftover handed back to us.

    The Code UI saves whatever root it was given and sends it as ``project_root``
    on the next NEW task. Originally that root was always ~/.thomas/code_scratch,
    so the value is already sitting in browsers -- and arriving as an explicit
    project_root it is indistinguishable from a deliberate pick. It cannot be
    one: the picker offers real projects and the drawer is not among them, so
    there is no click that produces it.

    Task-born folders get the same treatment, for the same reason, measured
    2026-08-05: task A's own folder came back as task B's ``project_root``
    (nothing was picked -- the client had simply kept it), so B built inside A
    and A's finished run listed B's page under "THOMAS MADE 2 THINGS". Unlike
    the drawer, a task folder CAN be clicked -- it appears in the picker -- so
    it is dropped only when the request carries no ``project_choice: "picked"``,
    the flag every real pick now sends. Folders the user made or chose
    themselves carry no task-born stamp and pass through untouched, flag or no
    flag.

    Only new tasks pass through here. A conversation already bound to one of
    these folders is resolved from the registry and still opens it.
    """
    if not requested:
        return None
    if forge_code_projects.is_shared_scratch(requested):
        return None
    if not picked and forge_code_projects.is_task_born_project(requested):
        return None
    return requested
