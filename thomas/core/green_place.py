"""Where greens live, and whether a folder is one.

A green is the private copy a self-fix is made in (``thomas/server/green_checkout.py``
makes, keeps and removes them). The server is not the only one that must know
where they are: a tool a Build team runs in a green must say so to the tests it
starts, and tools sit below the server, so the answer lives here, in core.

The green id is how a green's processes say it. ``scripts/cage/shell_runner.py``
gives every command it runs in a green ``THOMAS_AGENT_ID`` and ``AGENT_ID`` of
``thomas-green`` (it imports nothing of Thomas's, so it spells the id itself), and
``tests/conftest.py`` stands its real-data tripwire down for a run that carries
it: in a green the watched folder is the caged Thomas's own, which it keeps
writing while the green's tests run.

That stand-down is why :func:`green_of` decides by where the folder is and by the
record the server writes when it makes a green, in the green's own git folder
outside its work tree -- never by anything inside the folder asked about. A
project's files cannot move the project into the green root, or put a record
beside it there. Nor can the folder a check starts from: a root named by a
relative path would be read against it, so such a root names no green.

A test that needs a green root should set ``THOMAS_GREEN_ROOT``: patching
``green_checkout.green_root`` moves the server's greens but not :func:`green_of`.
"""

from __future__ import annotations

import os
from pathlib import Path

GREEN_ROOT_ENV = "THOMAS_GREEN_ROOT"
GREEN_AGENT_ID = "thomas-green"
# Written by green_checkout.create_green into the green's git folder, outside its work tree.
METADATA_NAME = "thomas-green.json"


def green_root() -> Path:
    """``<Thomas data dir>/green`` unless ``THOMAS_GREEN_ROOT`` says otherwise.

    Not C:\\ProgramData: the file-access ladder refuses ProgramData at every level
    as an OS system directory, so a self-fix there could not write a single file
    (measured live 2026-09-22). The cage's account reaches this folder through
    Windows' default "bypass traverse checking" right plus the grants
    ``green_checkout._secure_root`` gives it here; it gets nothing else in your profile.
    """
    raw = str(os.environ.get(GREEN_ROOT_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser()
    from thomas.core.config import resolve_thomas_data_dir

    return resolve_thomas_data_dir() / "green"


def _root_named_absolutely() -> bool:
    """Whether the setting the green root comes from is an absolute path, so the working folder cannot move it.

    The same order :func:`green_root` reads: ``THOMAS_GREEN_ROOT``, else ``THOMAS_DATA_DIR``, else the platform's
    data folder, which comes from what the system sets (``LOCALAPPDATA`` or the home folder), not from Thomas.
    """
    for key in (GREEN_ROOT_ENV, "THOMAS_DATA_DIR"):
        raw = str(os.environ.get(key) or "").strip()
        if raw:
            return Path(raw).expanduser().is_absolute()
    return True


def green_of(folder: str | Path) -> str:
    """The execution id of the green *folder* is in, or "" when it is in none.

    In a green means: the folder, links resolved, is ``<green root>/work/<id>`` or
    inside it, and the server's record ``<green root>/git/<id>/thomas-green.json``
    exists. A look-alike layout anywhere else, a stray folder in ``work``, a file
    of that name in the folder itself, or a green root named by a relative path is
    not a green. Anything that cannot be read answers "" -- not a green -- which
    keeps the tripwire armed.
    """
    try:
        if not _root_named_absolutely():
            return ""
        root = green_root().resolve()
        here = Path(folder).resolve()
    except (OSError, RuntimeError, ValueError):
        return ""
    work = root / "work"
    if here == work or not here.is_relative_to(work):
        return ""
    execution_id = here.relative_to(work).parts[0]
    try:
        recorded = (root / "git" / execution_id / METADATA_NAME).is_file()
    except OSError:
        return ""
    return execution_id if recorded else ""


__all__ = ["GREEN_AGENT_ID", "GREEN_ROOT_ENV", "METADATA_NAME", "green_of", "green_root"]
