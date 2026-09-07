"""Where the work is, as opposed to where Thomas is installed.

Praxis (workboard, claims, presence, executions) used to root itself at
``Path(__file__).parents[2]`` - the Thomas checkout - no matter which project
a task was about. This resolver answers for the project instead. Thomas's own
checkout is one possible answer, not the default.

Lives in ``thomas.core`` so nothing here imports upward; callers in
``thomas.agent`` and ``thomas.server`` delegate down to it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

ENV_ROOT = "THOMAS_PROJECT_ROOT"
_MAX_DEPTH = 40


def find_project_root(start_dir: Path, *, max_depth: int = _MAX_DEPTH) -> Path:
    """Nearest ancestor with ``.git``; inside the data dir, the data dir; else the folder itself."""

    start = Path(start_dir).resolve()
    for directory in (start, *start.parents)[: max(1, int(max_depth))]:
        try:
            if (directory / ".git").exists():
                return directory
        except OSError:
            continue
    data = user_praxis_root()
    if start == data or data in start.parents:
        return data
    return start


def user_praxis_root(env: Mapping[str, str] | None = None) -> Path:
    """The user's own coordination root: the Thomas data dir. A one-off job (a
    document, a deliverable) is not a project; its board lives here, not in the
    checkout Thomas happens to be installed in."""

    from thomas.core.config import resolve_thomas_data_dir

    return resolve_thomas_data_dir(env=env)


def coordination_root(repo_root: str | Path | None, workspace: str) -> Path:
    """Where a delegated job coordinates: the live repo for workspace == "project",
    the user's own board for an isolated one-off."""

    if str(workspace or "").strip().lower() == "project":
        return resolve_project_root(explicit=repo_root)
    return user_praxis_root()


def resolve_project_root(
    start_dir: str | Path | None = None,
    *,
    explicit: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Explicit argument, then ``THOMAS_PROJECT_ROOT``, then the git root above ``start_dir``.

    ``start_dir`` defaults to the current working directory.
    """

    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    environment = os.environ if env is None else env
    from_env = str(environment.get(ENV_ROOT) or "").strip()
    if from_env:
        return Path(from_env).expanduser().resolve()
    return find_project_root(Path(start_dir) if start_dir is not None else Path.cwd())
