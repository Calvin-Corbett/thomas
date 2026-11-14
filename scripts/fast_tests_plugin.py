"""pytest plugin for ``scripts/fast_tests.py`` (``-p fast_tests_plugin``) and for the check before your card.

Three jobs, each switched on by an environment variable the wrapper sets, so the plugin does nothing alone:

* ``FAST_TESTS_SELECT`` (path to a JSON file ``{"files": [...], "dirs": [...]}``): ignore every file and folder that
  is not on the list. The wrapper hands pytest one directory instead of dozens of file arguments (each extra
  argument costs about a second of collection) and this hook narrows it back to the same set of files. ``.html``
  and ``.mjs`` harness files are ignored too unless they are named, so a directory run collects what a file-argument
  run collects.
* ``FAST_TESTS_PYC_PREFIX``: put compiled bytecode under that folder. ``tests/conftest.py`` and ``sitecustomize.py``
  set ``sys.dont_write_bytecode``, which makes ``PYTHONPYCACHEPREFIX`` alone write nothing, so the flag is cleared at
  session start (after conftest has run).
* ``FAST_TESTS_RUN_DIR``: write this process's per-test outcome and duration to ``results-<worker>.json`` there.

The check before your card loads this file, as the running server read it when it started, for every shard of every
check (``thomas/server/proof/runner.py``), and names the selection with ``--fast-tests-select`` on the command line,
never in the environment, where it would reach every nested run. A change here changes every check once the servers
restart.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SELECT_ENV = "FAST_TESTS_SELECT"
PYC_ENV = "FAST_TESTS_PYC_PREFIX"
RUN_DIR_ENV = "FAST_TESTS_RUN_DIR"
SELECT_OPTION = "--fast-tests-select"

_selection: dict[str, Any] | None = None
_loaded = False
_outcomes: dict[str, str] = {}
_durations: dict[str, float] = {}


def _norm(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _load_selection(source: str | None = None) -> dict[str, Any] | None:
    global _selection, _loaded
    if _loaded:
        return _selection
    _loaded = True
    source = source or os.environ.get(SELECT_ENV)
    if not source:
        return None
    raw = json.loads(Path(source).read_text(encoding="utf-8"))
    files = {_norm(item) for item in raw.get("files", [])}
    dirs = tuple(_norm(item) for item in raw.get("dirs", []))
    above = {_norm(os.path.dirname(item)) for item in files}
    for folder in list(above):
        parent = os.path.dirname(folder)
        while parent and parent != folder:
            above.add(parent)
            folder, parent = parent, os.path.dirname(parent)
    _selection = {"files": files, "dirs": dirs, "above": above}
    return _selection


def is_selected(path: str | os.PathLike[str], selection: dict[str, Any], *, is_dir: bool) -> bool:
    """True when ``path`` is on the list, inside a listed folder, or a folder that leads to a listed file."""
    here = _norm(path)
    if here in selection["files"]:
        return True
    if any(here == folder or here.startswith(folder + os.sep) for folder in selection["dirs"]):
        return True
    return is_dir and here in selection["above"]


def pytest_addoption(parser: Any) -> None:
    parser.addoption(
        SELECT_OPTION,
        dest="fast_tests_select",
        default=None,
        help="a JSON file {files, dirs}: collect only these (the check before your card names it here)",
    )


def pytest_ignore_collect(collection_path: Path, config: Any) -> bool | None:
    selection = _load_selection(config.getoption("fast_tests_select", None))
    if selection is None:
        return None
    return None if is_selected(collection_path, selection, is_dir=collection_path.is_dir()) else True


def pytest_sessionstart(session: Any) -> None:
    prefix = os.environ.get(PYC_ENV)
    if prefix:
        sys.dont_write_bytecode = False
        sys.pycache_prefix = prefix


def pytest_runtest_logreport(report: Any) -> None:
    if not os.environ.get(RUN_DIR_ENV):
        return
    _durations[report.nodeid] = _durations.get(report.nodeid, 0.0) + float(report.duration)
    if report.failed:
        _outcomes[report.nodeid] = "failed"
    elif report.when == "call" or (report.skipped and report.when == "setup"):
        _outcomes.setdefault(report.nodeid, "skipped" if report.skipped else "passed")


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    run_dir = os.environ.get(RUN_DIR_ENV)
    if not run_dir:
        return
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    target = Path(run_dir) / f"results-{worker}.json"
    target.write_text(json.dumps({"outcomes": _outcomes, "durations": _durations}), encoding="utf-8")
