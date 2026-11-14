"""Referee closure, part one (plan B1; invariant 21): the referee folder imports only the standard library and itself."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REFEREE = Path(__file__).resolve().parents[1] / "scripts" / "cage" / "referee"
SOURCES = sorted(REFEREE.glob("*.py"))
OWN = {p.stem for p in SOURCES}
STDLIB = set(sys.stdlib_module_names)
FORBIDDEN_CALLS = {"exec", "eval", "compile", "__import__"}
FORBIDDEN_MODULES = {"importlib", "runpy", "pickle", "marshal", "imp", "code", "codeop"}


def imports(tree: ast.AST):
    """(module name, relative level) for every import, including those inside functions."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield (node.module or ""), node.level


def test_the_referee_folder_is_not_empty():
    assert {"charter", "derive", "fragment", "gitenv", "grant", "nofollow", "presence", "presence_win"} <= OWN


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_referee_imports_only_stdlib_and_own_folder(path):
    """Invariant 21 (part one): no import edge leaves the standard library plus this folder."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for module, level in imports(tree):
        top = module.split(".")[0]
        if level == 1:
            assert not module or top in OWN, f"{path.name}: relative import of {module} is not in this folder"
        else:
            assert level == 0 and top in STDLIB, f"{path.name} imports {module}, which is not the standard library"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_the_referee_never_runs_submitted_code_or_loads_modules_dynamically(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & FORBIDDEN_CALLS, f"{path.name} calls {called & FORBIDDEN_CALLS}"
    assert not {m.split(".")[0] for m, _ in imports(tree)} & FORBIDDEN_MODULES


SPAWNERS = {
    "subprocess": {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"},
    "os": {"system", "popen", "startfile", "posix_spawn", "posix_spawnp"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
    "multiprocessing": {"Process"},
}
SPAWN_PREFIXES = {"os": ("spawn", "exec")}
NATIVE_PREFIXES = ("CreateProcess", "ShellExecute")  # ctypes calls, matched by attribute name on any object
PROCESS_OWNERS = {"gitenv.py", "isolate.py"}


def process_starts(tree: ast.AST) -> list[str]:
    """Every call in ``tree`` that can start a process, however the name was imported (aliases and from-imports)."""
    names: dict[str, str] = {}  # local name -> dotted name it stands for
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                {
                    (a.asname or a.name.split(".")[0]): a.name.split(".")[0] if not a.asname else a.name
                    for a in node.names
                }
            )
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.update({(a.asname or a.name): f"{node.module}.{a.name}" for a in node.names})
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts, func = [], node.func
        while isinstance(func, ast.Attribute):
            parts.append(func.attr)
            func = func.value
        if isinstance(func, ast.Name):
            parts.append(names.get(func.id, func.id))
        dotted = ".".join(reversed(parts))
        module, _, attr = dotted.rpartition(".")
        if (
            attr in SPAWNERS.get(module, ())
            or attr.startswith(SPAWN_PREFIXES.get(module, ("\0",)))
            or (parts and parts[0].startswith(NATIVE_PREFIXES))
        ):
            found.append(dotted)
    return found


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_only_the_git_wrapper_and_the_child_runner_start_processes(path):
    """The property: no call that starts a process outside gitenv.py and isolate.py. Importing for exceptions is fine."""
    starts = process_starts(ast.parse(path.read_text(encoding="utf-8")))
    assert not starts or path.name in PROCESS_OWNERS, f"{path.name} starts a process: {starts}"


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\nsubprocess.run(['x'])",
        "import subprocess as sp\nsp.check_output(['x'])",
        "from subprocess import Popen\nPopen(['x'])",
        "from subprocess import run as go\ngo(['x'])",
        "import os\nos.system('x')",
        "import os\nos.popen('x')",
        "import os\nos.execv('x', [])",
        "import os\nos.spawnl(0, 'x')",
        "from os import system\nsystem('x')",
        "import asyncio\nasyncio.create_subprocess_exec('x')",
        "import multiprocessing\nmultiprocessing.Process(target=print).start()",
        "import ctypes\nctypes.windll.shell32.ShellExecuteW(0, 'open', 'x', None, None, 1)",
        "import ctypes\nk = ctypes.WinDLL('kernel32')\nk.CreateProcessW(None, 'x')",
    ],
)
def test_the_process_detector_flags_every_way_to_start_one(source):
    assert process_starts(ast.parse(source)), source


def test_the_process_detector_ignores_names_that_start_nothing():
    quiet = (
        "import subprocess, os\n"
        "try:\n    pass\nexcept (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):\n    pass\n"
        "x = subprocess.DEVNULL\nos.path.join('a', 'b')\nos.getcwd()\nrun = lambda: 1\nrun()\n"
    )
    assert process_starts(ast.parse(quiet)) == []


def test_every_python_file_in_the_folder_is_covered():
    assert not [p for p in REFEREE.rglob("*.py") if p.parent != REFEREE], "a sub-folder would escape the checks above"
    assert not list(REFEREE.glob("*_part*.py"))
