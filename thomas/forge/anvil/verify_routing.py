"""Which real check each changed file gets, chosen by what the file is.

The engine verifier used to send every changed path under ``tests/`` to pytest.
A JavaScript test (``tests/app.test.js``) then failed with pytest's exit 4,
"file or directory not found", and because that failure is deterministic every
fix pass got the same verdict until the pass budget was spent. The code beside
it (``app.js``) was never even syntax-checked.

Routing here:

- a Python test module (``test_*.py`` / ``*_test.py``) -> ``pytest`` on those files;
- a JavaScript test file -> ``node --test`` on those files, only when that is the
  project's own way to run tests (``package.json`` ``scripts.test`` is a
  ``node --test`` command, or there is no test script and the file uses the
  built-in ``node:test`` runner);
- any other test file (TypeScript, jest, vitest, a browser harness) -> no runner.
  It still gets the static checks every other file gets, and it is reported as
  UNCHECKED, never as a failure. Running a project's arbitrary ``npm test``
  script would widen what the engine may run, so it is not done.

Every path handed to a runner is validated by ``check.run``'s own rule
(``_project_path``: relative, inside the project, no shell characters), and the
runner is launched from an argv list, never a shell.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

_JS_SUFFIXES = (".js", ".mjs", ".cjs")
_TS_SUFFIXES = (".ts", ".mts", ".cts", ".tsx", ".jsx")
_JS_TEST_NAME_RE = re.compile(r"(?:^test[_-].+|.+[._-](?:test|spec))\.(?:[cm]?[jt]sx?)$")
_NODE_TEST_IMPORT_RE = re.compile(r"""(?:from\s+|require\s*\(\s*|import\s*\(\s*)['"]node:test['"]""")
_NODE_TEST_SCRIPT_RE = re.compile(r"^\s*node\s+(?:[^&|;]*\s)?--test\b")


def _norm(path: str) -> str:
    return str(path).replace("\\", "/")


def _in_test_dir(path: str) -> bool:
    p = _norm(path)
    parts = p.split("/")[:-1]
    return any(part in {"tests", "test", "__tests__"} for part in parts)


def is_bytecode_artifact(path: str) -> bool:
    """Compiled Python (``__pycache__/``, ``.pyc``/``.pyo``): generated, never the work, never checkable as text."""
    p = _norm(path)
    return "__pycache__/" in p or p.lower().endswith((".pyc", ".pyo"))


def is_python_test_module(path: str) -> bool:
    """A file pytest collects by default: ``test_*.py`` or ``*_test.py``."""
    base = _norm(path).rsplit("/", 1)[-1]
    return base.endswith(".py") and (base.startswith("test_") or base.endswith("_test.py"))


def is_script_test_file(path: str) -> bool:
    """A JavaScript or TypeScript file shaped like a test."""
    p = _norm(path)
    base = p.rsplit("/", 1)[-1]
    if not base.lower().endswith(_JS_SUFFIXES + _TS_SUFFIXES):
        return False
    return bool(_JS_TEST_NAME_RE.match(base)) or _in_test_dir(p)


def project_test_script(cwd: str | Path) -> str | None:
    """``package.json`` ``scripts.test``, or None when there is none or it cannot be read."""
    try:
        data = json.loads((Path(cwd) / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scripts = data.get("scripts") if isinstance(data, dict) else None
    script = scripts.get("test") if isinstance(scripts, dict) else None
    return script.strip() if isinstance(script, str) and script.strip() else None


def _uses_node_test(cwd: str | Path, path: str) -> bool:
    try:
        text = (Path(cwd) / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_NODE_TEST_IMPORT_RE.search(text))


@dataclass
class FileRouting:
    """The changed files, split by the check each one gets."""

    python_tests: list[str] = field(default_factory=list)
    node_tests: list[str] = field(default_factory=list)
    # (path, why it has no runner); these still get the static checks.
    unchecked_tests: list[tuple[str, str]] = field(default_factory=list)
    static: list[str] = field(default_factory=list)


def route_changed_files(cwd: str | Path, files: list[str]) -> FileRouting:
    """Split ``files`` by the real check each one gets (see the module docstring)."""
    from thomas.tools.check_run import CheckRefused, _project_path

    root = Path(cwd).resolve()
    routing = FileRouting()
    script = project_test_script(cwd)
    script_is_node_test = bool(script and _NODE_TEST_SCRIPT_RE.match(script))
    node = shutil.which("node")
    for f in files:
        if is_python_test_module(f):
            try:
                _project_path(_norm(f), root, what="test file")
            except CheckRefused as exc:
                routing.unchecked_tests.append((f, str(exc)))
                routing.static.append(f)
                continue
            routing.python_tests.append(f)
            continue
        if not is_script_test_file(f):
            routing.static.append(f)
            continue
        why = ""
        lower = f.lower()
        if not lower.endswith(_JS_SUFFIXES):
            why = "a TypeScript/JSX test; the engine has no allowed runner for it"
        elif script and not script_is_node_test:
            why = f"the project's test command ({script[:80]}) is not one the engine may run"
        elif not script and not _uses_node_test(cwd, f):
            why = "not a node:test file and the project names no test command"
        elif not node:
            why = "node is not installed"
        else:
            try:
                _project_path(_norm(f), root, what="test file")
            except CheckRefused as exc:
                why = str(exc)
        if why:
            routing.unchecked_tests.append((f, why))
            routing.static.append(f)
        else:
            routing.node_tests.append(f)
    return routing


def node_test_argv(files: list[str]) -> list[str]:
    """``node --test <files>`` as an argv list (never a shell)."""
    return [shutil.which("node") or "node", "--test", *[_norm(f) for f in files]]


__all__ = [
    "FileRouting",
    "is_bytecode_artifact",
    "is_python_test_module",
    "is_script_test_file",
    "node_test_argv",
    "project_test_script",
    "route_changed_files",
]
