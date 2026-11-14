#!/usr/bin/env python3
"""One answer to "which board?" for every coordination tool on its default path.

Every linked git worktree carries its own checked-out ``plans/thomas/WORKBOARD.md``
and its own copy of every script that reads it. The message tool and the board
lock anchored themselves to the PRIMARY checkout through git's shared common
directory, while the inbox gate, its Bash hook, the startup router and the
commit barrier anchored to ``Path(__file__).parents[3]`` -- whichever worktree
held the running copy. A coordinator in the primary checkout and a worker in a
linked worktree therefore sent on one board and were gated on another: the
worker's startup inbox read empty, its gates never saw the blocker, and its
read receipts were keyed to a board path nobody else used.

The rule: the coordination root is the primary checkout of the git repository
whose checkout holds the running script copy -- the parent of ``git rev-parse
--git-common-dir``, which is the same directory for the primary checkout and
for every worktree linked to it. When git cannot answer (git missing, not a
repository, an unusual layout, or a tree that is not itself a checkout but sits
inside one) the root is the tree itself, exactly as before. Resolving never
raises: this sits under the inter-agent delivery path, and an exception at
import time would make every message command unimportable rather than merely
worktree-local.

Claims are not coordination traffic. They stay on the checkout's own board,
where ``claim.py`` and the claim gates keep them; only messages, their read
receipts, the P0 barrier and the session binding a commit is checked against
move to the coordination root.
"""

from __future__ import annotations

import functools
import os
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path

_THIS_TREE = Path(__file__).resolve().parents[3]
BOARD_RELATIVE_PATH = Path("plans") / "thomas" / "WORKBOARD.md"
COORDINATION_RELATIVE_PATH = Path("runtime") / "coordination"
INBOX_GATE_SCRIPT = "scripts/forge/gates/workboard_inbox.py"


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _ask_git(local_root: Path) -> Path | None:
    """git's answer for ``local_root``, or None when git could not be asked (missing, timed out)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir"],
            cwd=str(local_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    lines = out.stdout.strip().splitlines() if out.returncode == 0 else []
    if len(lines) != 2:
        return local_root
    try:
        toplevel, common = Path(lines[0]).resolve(), Path(lines[1])
        # A tree that is not itself a checkout (a copy nested in some other repository) keeps its own root:
        # git would otherwise answer for the enclosing repository.
        if _same_path(toplevel, local_root) and common.name == ".git" and common.parent.exists():
            return common.parent.resolve()
    except (OSError, ValueError):
        pass
    return local_root


@functools.lru_cache(maxsize=64)
def _answered(local_root: Path) -> Path:
    answer = _ask_git(local_root)
    if answer is None:
        raise LookupError(local_root)  # lru_cache keeps no result for a call that raised
    return answer


def _primary_checkout(local_root: Path) -> Path:
    """Ask git once per tree and process (the hook pays for every Bash call); a failed ask is asked again."""
    try:
        return _answered(local_root)
    except LookupError:
        return local_root


def coordination_root(anchor: Path | str | None = None) -> Path:
    """The primary checkout of the repository whose checkout is ``anchor`` (default: this script tree)."""
    if anchor is None:
        return _primary_checkout(_THIS_TREE)
    try:
        local_root = Path(anchor).resolve()
    except (OSError, ValueError):
        return Path(anchor)
    return _primary_checkout(local_root)


def default_workboard(root: Path | None = None) -> Path:
    """The one board every checkout of the project coordinates on."""
    return (Path(root) if root is not None else coordination_root()) / BOARD_RELATIVE_PATH


def coordination_dir(root: Path | None = None) -> Path:
    """Locks, presence and receipts live beside the board, never in a linked worktree."""
    return (Path(root) if root is not None else coordination_root()) / COORDINATION_RELATIVE_PATH


def coordination_board(workboard_path: Path) -> Path:
    """The board that coordination traffic about ``workboard_path``'s checkout lives on.

    A checkout's own ``plans/thomas/WORKBOARD.md`` maps to its coordination root's board: for a linked worktree
    that is the primary checkout's board, anywhere else it is the same file and comes back unchanged. Any other
    path (a scratch board in a test, a data-dir board for a one-off job) is judged where it is.
    """
    path = Path(workboard_path)
    if [part.casefold() for part in path.parts[-3:]] != ["plans", "thomas", "workboard.md"]:
        return path
    try:
        checkout = path.resolve().parents[2]
    except (OSError, ValueError):
        return path
    root = coordination_root(checkout)
    return path if _same_path(root, checkout) else default_workboard(root)


def board_argument(workboard_path: Path) -> str:
    """The ``--workboard`` argument every printed remediation command carries.

    A command that omits the board it was judged on sends the agent to whatever
    board its own checkout resolves, which is the split this module closes. The
    path is absolute and quoted so a checkout under a directory with spaces
    still yields a runnable command.
    """
    try:
        absolute = str(Path(workboard_path).resolve())
    except OSError:
        absolute = str(workboard_path)
    quoted = f'"{absolute}"' if os.name == "nt" else shlex.quote(absolute)
    return f" --workboard {quoted}"


def with_inbox_board(
    commands: Sequence[tuple[str, Sequence[str]]], board: Path
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """``commands`` with ``--workboard <board>`` added to every run of the inbox gate.

    The commit tool judges unread P0 mail on ``board``. An inbox gate subprocess left on its own default would
    report on whatever board its script copy resolves, not necessarily the one that judged the commit.
    """
    try:
        absolute = str(Path(board).resolve())
    except OSError:
        absolute = str(board)

    def runs_inbox_gate(command: Sequence[str]) -> bool:
        return any(str(token).replace("\\", "/").endswith(INBOX_GATE_SCRIPT) for token in command)

    return tuple(
        (name, (*command, "--workboard", absolute) if runs_inbox_gate(command) else tuple(command))
        for name, command in commands
    )
