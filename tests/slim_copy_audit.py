"""The miss detector of a slim proof copy (spec 2026-10-29 section 3, Misses).

A slim copy leaves out tracked files. A test that reads one of them, or lists a folder that holds one, sees a different
tree from a full checkout: that is a miss, and a miss voids the scoped run. The check names the left-out files in
``THOMAS_SLIM_ABSENT`` (a file, one absolute path per line) and where to log in ``THOMAS_SLIM_MISS_LOG``; without both,
nothing is watched. ``Path.exists()`` and ``os.stat()`` raise no audit event: shadow parity is the net for those.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ENV_ABSENT = "THOMAS_SLIM_ABSENT"
ENV_LOG = "THOMAS_SLIM_MISS_LOG"
_EVENTS = ("open", "os.listdir", "os.scandir")
_state: dict = {"active": False, "hooked": False, "absent": frozenset(), "folders": frozenset(), "log": ""}


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(os.fsdecode(path)))


def _record(path: str, event: str) -> None:
    test = str(os.environ.get("PYTEST_CURRENT_TEST") or "").split(" (", 1)[0]
    caller = sys._getframe(2)  # 0 this, 1 _hook, 2 the code that touched the path
    where = f"{caller.f_code.co_filename}:{caller.f_lineno}"
    # One file per process: on Windows an append is a seek and then a write, so workers sharing a file overwrite lines.
    fd = os.open(f"{_state['log']}.{os.getpid()}", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps([path, event, test, where]) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _hook(event: str, args: tuple) -> None:
    if not _state["active"] or event not in _EVENTS or not args:
        return
    if not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    try:
        path = _norm(args[0])
    except (TypeError, ValueError):
        return
    if event == "open":
        if path in _state["absent"]:
            _record(path, event)
    elif path in _state["folders"] and not _only_finding_a_name():
        _record(path, event)


def _only_finding_a_name() -> bool:
    """pytest's collector lists each folder above a named test file and keeps only what it was named, the import
    system lists a package's folder to find a module, which fails loudly if the copy left it out, and
    ``importlib.metadata`` lists the folders on the path for installed packages, which a repo holds none of: none of
    them sees a different tree. Nor does the manifest loader: a copy holds its own plugin's manifest by design, and a
    change to any manifest takes the full check. Only the direct caller counts, and pathlib is looked through because
    it is only how the loader lists: a test listing a folder is a miss."""
    caller = sys._getframe(2)  # 0 this, 1 _hook, 2 the code that called os.listdir/os.scandir (C adds no frame)
    while caller is not None and str(caller.f_globals.get("__name__", "")) in ("pathlib", "pathlib._local", "glob"):
        caller = caller.f_back
    name = str(caller.f_globals.get("__name__", "")) if caller is not None else ""
    return name.startswith(("_pytest.", "importlib.")) or name == "thomas.core.plugin_manifest"


def install() -> None:
    """Watch for misses when both variables name files; otherwise do nothing."""
    absent, log = os.environ.get(ENV_ABSENT), os.environ.get(ENV_LOG)
    if not absent or not log:
        return
    lines = Path(absent).read_text(encoding="utf-8").splitlines()
    paths = frozenset(_norm(line.strip()) for line in lines if line.strip())
    _state.update(absent=paths, folders=frozenset(os.path.dirname(p) for p in paths), log=log)
    if not _state["hooked"]:
        sys.addaudithook(_hook)  # audit hooks cannot be removed: stop() turns this one off
        _state["hooked"] = True
    _state["active"] = True


def stop() -> None:
    _state["active"] = False


def misses(log: Path) -> list[list[str]]:
    """The ``[path, event, test, where]`` records every process logged for *log*; none when nothing did."""
    log = Path(log)
    parts = sorted(log.parent.glob(f"{log.name}.*"))
    return [json.loads(line) for part in parts for line in part.read_text("utf-8").splitlines() if line.strip()]
