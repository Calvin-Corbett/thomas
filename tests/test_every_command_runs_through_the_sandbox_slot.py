"""Every command runs through the sandbox slot, and the direct process launches that remain can only get fewer.

``thomas/tools/sandbox_slot.py`` is where a command is run, caged when the cage is on and here when it is off.
``thomas/core/contained_process.py`` is the slot's own contained local run and ``thomas/tools/cage_shell.py`` is the cage
itself; those three are the only files allowed to start a process on their own account. Every other file that calls
``subprocess.run``, ``os.system``, ``asyncio.create_subprocess_exec`` and the rest is recorded in
``tests/process_launches_recorded.txt`` with how many launches it holds. A line in that file may go down and may be
removed. It may not go up, and a file that is not in it may not launch anything.

Many of the recorded launches are legitimate (git, build tools). The number is what matters: it only goes down, and
every landing that moves a launch onto the slot lowers :data:`CEILING` and its line in the record.

The scan reads ``git ls-files`` rather than walking the folder, so an untracked scratch file cannot hide a launch.
Tests are not scanned: they start processes on purpose to test them.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = Path(__file__).with_name("process_launches_recorded.txt")
SCANNED_ROOTS = ("thomas/", "scripts/")
EXEMPT = (
    "thomas/tools/sandbox_slot.py",
    "thomas/core/contained_process.py",
    "thomas/tools/cage_shell.py",
)
#: The sum of the record. Lower it when a landing removes a launch; it never goes up.
CEILING = 501
FIX = "FIX: run the command through the sandbox slot (thomas/tools/sandbox_slot.py), do not raise the ceiling."

_LAUNCHERS: dict[str, tuple[str, ...]] = {
    "subprocess": ("run", "Popen", "call", "check_call", "check_output"),
    "os": ("system", "popen"),
    "asyncio": ("create_subprocess_exec", "create_subprocess_shell"),
}
_PREFIXES: dict[str, tuple[str, ...]] = {"os": ("spawn", "exec")}


def _is_launcher(module: str, attr: str) -> bool:
    return attr in _LAUNCHERS.get(module, ()) or attr.startswith(_PREFIXES.get(module, ("\0",)))


def _tracked_python() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.split("\0") if p.startswith(SCANNED_ROOTS) and p not in EXEMPT]


class _Names:
    """What a file's names stand for: the modules we watch, and the names that start a process."""

    def __init__(self, tree: ast.AST) -> None:
        self.modules: dict[str, str] = {}  # local name -> module
        self.funcs: set[str] = set()  # local names that start a process
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    root = a.name.split(".")[0]
                    if root in _LAUNCHERS and (a.asname is None or a.name == root):
                        self.modules[a.asname or root] = root
            elif isinstance(node, ast.ImportFrom) and node.module in _LAUNCHERS and node.level == 0:
                for a in node.names:
                    if a.name == "*":
                        self.funcs.update(_LAUNCHERS[node.module])
                    elif _is_launcher(node.module, a.name):
                        self.funcs.add(a.asname or a.name)
        grew = True
        while grew:  # an alias of an alias is still an alias
            grew = False
            for node in ast.walk(tree):
                targets: list[ast.expr] = []
                value: ast.AST | None = None
                if isinstance(node, ast.Assign):
                    targets, value = list(node.targets), node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    targets, value = [node.target], node.value
                if value is None:
                    continue
                for t in targets:
                    if not isinstance(t, ast.Name):
                        continue
                    if isinstance(value, ast.Name) and value.id in self.modules and t.id not in self.modules:
                        self.modules[t.id] = self.modules[value.id]
                        grew = True
                    if self.hands_on_launcher(value) and t.id not in self.funcs:
                        self.funcs.add(t.id)
                        grew = True

    def is_launcher_ref(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.funcs
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            mod = self.modules.get(node.value.id)
            return mod is not None and _is_launcher(mod, node.attr)
        return False

    def is_getattr_launcher(self, node: ast.AST) -> bool:
        """``getattr(subprocess, "run")``: a launcher fetched by name."""
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"):
            return False
        if len(node.args) < 2 or not isinstance(node.args[0], ast.Name):
            return False
        mod, name = self.modules.get(node.args[0].id), node.args[1]
        return (
            mod is not None
            and isinstance(name, ast.Constant)
            and isinstance(name.value, str)
            and _is_launcher(mod, name.value)
        )

    def hands_on_launcher(self, node: ast.AST) -> bool:
        """The value is a launcher, or a wrapper built around one (``partial(subprocess.run, check=True)``)."""
        if self.is_launcher_ref(node) or self.is_getattr_launcher(node):
            return True
        if isinstance(node, ast.Call) and not self.is_launcher_ref(node.func):
            return any(self.hands_on_launcher(a) for a in [*node.args, *(k.value for k in node.keywords)])
        return False


def launch_lines(source: str) -> list[int]:
    """The line of every direct process launch in ``source``.

    A launch is a call of a launcher, of a name assigned from one, or of a launcher imported under another name. A launcher
    handed on without being called (``to_thread(subprocess.run, ...)``) counts once, where it is handed on. An assignment
    that only aliases a launcher is not a launch until the alias is called.
    """
    tree = ast.parse(source)
    names = _Names(tree)
    lines: list[int] = []
    skip: set[int] = set()  # nodes already counted as a call, or that only alias
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (names.is_launcher_ref(node.func) or names.is_getattr_launcher(node.func)):
            lines.append(node.lineno)
            skip.update(id(n) for n in ast.walk(node.func))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            if names.hands_on_launcher(node.value):
                skip.update(id(n) for n in ast.walk(node.value))
    for node in ast.walk(tree):
        if id(node) not in skip and isinstance(node, (ast.Name, ast.Attribute)) and names.is_launcher_ref(node):
            if isinstance(node.ctx, ast.Load):
                lines.append(node.lineno)
    return sorted(lines)


def scan() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for rel in _tracked_python():
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            lines = launch_lines(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        if lines:
            found[rel] = lines
    return found


def recorded() -> dict[str, int]:
    out: dict[str, int] = {}
    for raw in RECORD.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            path, _, count = raw.rpartition(" ")
            out[path] = int(count)
    return out


DIRECT_LAUNCHES = recorded()


def test_the_record_is_sorted_and_has_no_empty_entry() -> None:
    lines = [ln for ln in RECORD.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines == sorted(lines), "tests/process_launches_recorded.txt must stay sorted"
    assert all(n > 0 for n in DIRECT_LAUNCHES.values()), "an entry with no launches left should be removed"
    assert not set(DIRECT_LAUNCHES) & set(EXEMPT), "the slot's own files are exempt and do not belong in the record"


def test_the_allowlist_never_grows() -> None:
    total = sum(DIRECT_LAUNCHES.values())
    assert total <= CEILING, f"the record holds {total} launches against a ceiling of {CEILING}. {FIX}"


def test_the_ceiling_follows_the_measured_total_down() -> None:
    measured = sum(len(v) for v in scan().values())
    assert measured + 5 >= CEILING, (
        f"CEILING is {CEILING} but the tree launches {measured}; lower CEILING and the lines that fell, "
        "so no room is left for a new launch"
    )


def test_no_new_direct_launch_outside_the_slot() -> None:
    extra = {rel: lines for rel, lines in scan().items() if len(lines) > DIRECT_LAUNCHES.get(rel, 0)}
    detail = "; ".join(
        f"{rel} launches {len(lines)} (recorded {DIRECT_LAUNCHES.get(rel, 0)}) at line(s) {', '.join(map(str, lines))}"
        for rel, lines in sorted(extra.items())
    )
    assert not extra, f"a process is started directly: {detail}. {FIX}"


def test_the_list_does_not_go_stale() -> None:
    found = scan()
    stale = {rel: n for rel, n in DIRECT_LAUNCHES.items() if len(found.get(rel, [])) < n}
    assert not stale, f"these files launch fewer processes now; lower their counts or remove them: {stale}"


def test_the_scanner_sees_a_direct_call() -> None:
    assert len(launch_lines("import subprocess\nsubprocess.run(['x'])\n")) == 1
    for call in ("check_output", "check_call", "call", "Popen"):
        assert len(launch_lines(f"import subprocess\nsubprocess.{call}(['x'])\n")) == 1
    assert len(launch_lines("import os\nos.system('x')\nos.popen('y')\nos.spawnl(0, 'a')\nos.execv('a', [])\n")) == 4
    assert launch_lines("def f(slot):\n    return slot.run('x')\n") == []


def test_the_scanner_sees_an_alias_import() -> None:
    assert len(launch_lines("from subprocess import run as r\nr(['x'])\n")) == 1
    assert len(launch_lines("import subprocess as sp\nsp.run(['x'])\n")) == 1
    assert len(launch_lines("from os import system\nsystem('x')\n")) == 1


def test_the_scanner_sees_an_assigned_alias_or_wrapper() -> None:
    assert len(launch_lines("import subprocess\nrunner = subprocess.run\nrunner(['x'])\n")) == 1
    src = "import subprocess\nfrom functools import partial\nr = partial(subprocess.run, check=True)\nr(['x'])\n"
    assert len(launch_lines(src)) == 1
    assert len(launch_lines("import subprocess as sp\nm = sp\nm.check_output(['x'])\n")) == 1
    assert len(launch_lines("import subprocess\nf = getattr(subprocess, 'run')\nf(['x'])\n")) == 1
    assert len(launch_lines("import subprocess\ngetattr(subprocess, 'run')(['x'])\n")) == 1
    assert launch_lines("import subprocess\nresult = subprocess.run(['x'])\nresult(1)\n") == [2]


def test_the_scanner_sees_a_call_inside_a_nested_function() -> None:
    src = (
        "import subprocess\n\ndef outer():\n    def inner():\n        return subprocess.run(['x'])\n    return inner\n"
    )
    assert launch_lines(src) == [5]
    assert launch_lines(
        "import subprocess\nclass A:\n    async def f(self):\n        g = lambda: subprocess.Popen(1)\n"
    ) == [4]


def test_the_scanner_sees_asyncio_subprocesses() -> None:
    assert len(launch_lines("import asyncio\nasync def f():\n    await asyncio.create_subprocess_exec('x')\n")) == 1
    assert len(launch_lines("import asyncio\nasync def f():\n    await asyncio.create_subprocess_shell('x')\n")) == 1
    assert len(launch_lines("from asyncio import create_subprocess_exec as c\nasync def f():\n    await c('x')\n")) == 1


def test_the_scanner_sees_a_launcher_handed_on_uncalled() -> None:
    src = "import asyncio, subprocess\nasync def f():\n    await asyncio.to_thread(subprocess.run, ['x'])\n"
    assert launch_lines(src) == [3]


def test_the_scanner_ignores_a_string_or_a_comment() -> None:
    src = "'''subprocess.run is used here.'''\n# subprocess.run(['x'])\nX = \"subprocess.run('x')\"\nimport subprocess\nY = subprocess.PIPE\n"
    assert launch_lines(src) == []
    assert (
        launch_lines(
            "import subprocess\n\ndef f():\n    '''os.system('x')'''\n    return subprocess.CalledProcessError\n"
        )
        == []
    )
