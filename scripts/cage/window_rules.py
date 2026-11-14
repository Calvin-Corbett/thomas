"""Which files never land inside a window, whatever else is true of their change (spec 2026-10-12, sections 3 and 8.2).

On 2026-10-25 you asked for every change to go through the window ("all changes should be through express lane") and
chose to keep cards only for the window's own guard. So a change with any of these files waits for a card:

- a deletion; every config file pytest reads, at any depth and in any case (it decides how the checker runs the tests);
  and every other file ``card_catalogue.file_class`` ranks 0-1 (it runs as you outside Thomas: root files and the
  launchers you start), except a test helper under tests/;
- every file ``card_catalogue.danger_class`` puts under gates or the cage and approvals. A new way to the network is
  no longer held back by path: the second look reads every change for it;
- what the Express charter refuses (``charter.path_problem``: the cage, the commit tools and the gates, configuration
  and release metadata, runtime state and binaries, file names Python runs on its own, odd spellings), except the
  checks themselves (thomas/server/precard, proof, ratchet, green_*, thomas_project*, self_change_status), which the
  window now lands; the approval and sign-in files and the kernel among them still wait (``_APPROVAL_GUARD``);
- every file a process that runs as you loads: the promoter, the keepalive, the checker and the window's control
  (their import closure, read from git's own tree and from the modules this process has loaded). Without this, a
  window could land a change to code the window's own guard runs on its next start;
- the window's own files and the notes agents read as instructions: .claude/, .thomas/, .githooks/;
  thomas/server/window_*.py and self_change_cards.py; and every AGENTS.md, CLAUDE.md, GUARDRAILS.md, SOUL.md,
  IDENTITY.md and SKILL.md, and every .md at the root but a changelog.d fragment.

Only an exact single version-line replacement in pyproject.toml's [project] or thomas/__init__.py, to the next patch
number, may escape their path exclusions and, since 2026-10-27, that file's own place on the enforcement list. The
complete Git diff must prove it; every other enforcement path, and the cage and network checks, still apply.

These are path and pattern rules. They cannot see every way code reaches the network or your files (spec 8.9); the
window rests on the checker and the second look as well.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import ModuleType

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli dependency.
    import tomli as tomllib

from scripts.cage import self_change_checks as checks
from scripts.cage.referee import charter

ENTRY_POINTS = (
    "scripts/cage/promoter_service.py",
    "scripts/cage/cage_keepalive.py",
    "scripts/cage/checker_service.py",
    "scripts/cage/window_control.py",
)
_PACKAGES = frozenset({"thomas", "scripts"})
_ALSO_NEVER = re.compile(
    r"^(\.claude|\.thomas|\.githooks)/"
    r"|^thomas/server/(window_[a-z0-9_]*|self_change_cards)\.py$"
    r"|(^|/)(agents|claude|guardrails|soul|identity|skill)\.md$"
    r"|^[^/]*\.md$"
)
# The part of the charter's approval_or_checks list that is the window's guard rather than the checks: the express
# switch and lane, the kernel, your desk, sign-in and elevation, trusted cards, protected writes and the commit seal.
_APPROVAL_GUARD = re.compile(
    r"^thomas/(server/(express|routes/express)|core/kernel|tools/(owner_desk|filesystem))"
    r"|(^|/)(dial_elevation[^/]*|windows_auth|native_auth|trusted_card|cage_shell|setting_request|chat_inline_actions"
    r"|owner_wait|protection_tier|commit_integrity|express_switch|self_edit_controls)\.(py|js)$"
)
_CHARTER_WORDS = {
    "path_spelling": "its path is spelled in a way the window does not take",
    "referee_or_cage": "it is part of the cage, the commit tools or the gates",
    "owner_process_closure": "a process that runs as you loads it",
    "approval_or_checks": "it is part of an approval or of the checks",
    "config_or_release": "it is configuration or release metadata",
    "runtime_or_binary": "it is runtime state or a binary",
    "autoexec_name": "Python runs a file of that name on its own",
}
_UNPARSABLE = (SyntaxError, ValueError, RecursionError, MemoryError)
# Every config file pytest reads, wherever it sits: pytest takes the one nearest the files it is given, and its addopts
# can load a plugin (2026-10-14 review, C1). ``card_catalogue.file_class`` names five of them, in lower case only; it
# only orders a card's files, so the window keeps its own list rather than change the pinned catalogue.
_PYTEST_READS = frozenset(
    {
        "conftest.py",
        "pytest.toml",
        ".pytest.toml",
        "pytest.ini",
        ".pytest.ini",
        "tox.ini",
        "setup.cfg",
        "pyproject.toml",
    }
)


_VERSION_PATHS = frozenset({"pyproject.toml", "thomas/__init__.py"})


def _version_only(path: str, diff: str) -> bool:
    """Prove a single version replacement from a complete, ordinary Git file diff."""
    lines = diff.split("\n")
    if (
        path not in _VERSION_PATHS
        or len(lines) < 8
        or lines.pop() != ""
        or lines[0] != f"diff --git a/{path} b/{path}"
        or not re.fullmatch(r"index [0-9a-f]{7,64}\.\.[0-9a-f]{7,64} 100644", lines[1])
        or lines[2:4] != [f"--- a/{path}", f"+++ b/{path}"]
    ):
        return False
    hunk = re.fullmatch(r"@@ -1(?:,([0-9]+))? \+1(?:,([0-9]+))? @@", lines[4])
    if not hunk:
        return False
    before: list[str] = []
    after: list[str] = []
    removed: list[int] = []
    added: list[int] = []
    old_eof = new_eof = False
    previous = ""
    for line in lines[5:]:
        if line == r"\ No newline at end of file":
            if previous not in {" ", "-", "+"}:
                return False
            old_eof |= previous in {" ", "-"}
            new_eof |= previous in {" ", "+"}
            previous = ""
            continue
        tag = line[:1]
        if tag not in {" ", "-", "+"}:
            return False
        if tag in {" ", "-"}:
            if old_eof:
                return False
            if tag == "-":
                removed.append(len(before))
            before.append(line[1:])
        if tag in {" ", "+"}:
            if new_eof:
                return False
            if tag == "+":
                added.append(len(after))
            after.append(line[1:])
        previous = tag
    if (
        len(removed) != 1
        or removed != added
        or old_eof != new_eof
        or len(before) != int(hunk[1] or "1")
        or len(after) != int(hunk[2] or "1")
    ):
        return False
    index = removed[0]
    name = "version" if path == "pyproject.toml" else "__version__"
    pattern = rf'{name} = "([0-9]+\.[0-9]+\.[0-9]+)"'
    old = re.fullmatch(pattern, before[index])
    new = re.fullmatch(pattern, after[index])
    if not old or not new or old[1] == new[1]:
        return False
    major, minor, patch = (int(part) for part in old[1].split("."))
    if new[1] != f"{major}.{minor}.{patch + 1}":  # the next patch only: a jump or a step back is a release decision
        return False
    for content, version in ((before, old[1]), (after, new[1])):
        source = "\n".join(content) + ("" if old_eof else "\n")
        try:
            if path == "pyproject.toml":
                if tomllib.loads(source).get("project", {}).get("version") != version:
                    return False
            elif not any(
                isinstance(node, ast.Assign)
                and node.lineno == index + 1
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "__version__"
                and isinstance(node.value, ast.Constant)
                and node.value.value == version
                for node in ast.parse(source).body
            ):
                return False
        except (*_UNPARSABLE, tomllib.TOMLDecodeError, AttributeError, TypeError):
            return False
    return True


def why_never(
    path: str,
    status: str,
    *,
    added_diff: str,
    enforced: Iterable[str],
    closure: frozenset[str],
    catalogue: ModuleType,
) -> str:
    """Why *path* (changed with git *status*) never lands inside a window, or "" when it may."""
    if status == "D":
        return "it deletes a file"
    if status == "M" and path in _VERSION_PATHS and _version_only(path, added_diff):
        # A proven next-patch version line no longer counts its own file's place on the enforcement list (your
        # decision, 2026-10-27): every change to Thomas's code bumps it, so no such change could land in a window.
        others = [entry for entry in enforced if entry != path]
        danger = catalogue.danger_class(path, added_diff=added_diff, enforcement_paths=others)
        return f"it touches {danger}, which always has its own card" if danger else ""
    # Windows opens a path without regard to case, so its spelling must not change which rule applies (C2).
    folded = path.casefold()
    name = folded.rsplit("/", 1)[-1]
    test_helper = folded.startswith("tests/") and name.endswith(".py")
    if name in _PYTEST_READS or (
        min(catalogue.file_class(path, status), catalogue.file_class(folded, status)) <= 1 and not test_helper
    ):
        return "it runs as you outside Thomas (a root file, a launcher, or a config file pytest reads)"
    danger = catalogue.danger_class(path, added_diff=added_diff, enforcement_paths=enforced)
    if danger and danger != catalogue.DANGER_NETWORK:
        return f"it touches {danger}, which always has its own card"
    code = charter.path_problem(path, closure)
    if code == "approval_or_checks" and not _APPROVAL_GUARD.search(folded):
        code = ""  # the checks themselves land in a window now; only the approval guard waits
    if code:
        return _CHARTER_WORDS.get(code, code)
    if _ALSO_NEVER.search(path.casefold()):
        return "it is part of the pipeline or the window, or a note agents read as instructions"
    return ""


def _dotted(path: str) -> str:
    return path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")


def _is_import_call(node: ast.Call) -> bool:
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "__import__") or (
        isinstance(func, ast.Attribute) and func.attr == "import_module"
    )


def _imports(tree: ast.AST, package: str) -> list[str]:
    """Every module name *tree* may import, at any depth: lazy imports in functions and import_module("...") too."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            names.append(module)
            names.extend(f"{module}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Call) and _is_import_call(node) and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names.append(first.value)
    return [name for name in names if name]


def static_closure(repo: Path, rev: str, entries: Iterable[str]) -> frozenset[str]:
    """Every repo file the *entries* may load at *rev*, read from git's own tree and never run.

    Both spellings of every module walked are included, ``x.py`` and ``x/__init__.py``, whether or not the file
    exists: a change that adds the other one would be loaded too. An upper bound, as it should be."""
    tracked = set(checks.run_git(repo, "ls-tree", "-r", "--name-only", rev).stdout.splitlines())
    found: set[str] = set()
    seen: set[str] = set()
    todo = [_dotted(entry) for entry in entries]
    while todo:
        name = todo.pop()
        parts = name.split(".")
        if name in seen or parts[0] not in _PACKAGES:
            continue
        seen.add(name)
        todo.extend(".".join(parts[:i]) for i in range(1, len(parts)))  # a package's __init__ runs first
        candidates = ("/".join(parts) + ".py", "/".join(parts) + "/__init__.py")
        found.update(candidates)
        path = next((candidate for candidate in candidates if candidate in tracked), None)
        if path is None:
            continue
        try:
            tree = ast.parse(checks.run_git(repo, "show", f"{rev}:{path}").stdout)
        except _UNPARSABLE:
            continue
        package = name if path.endswith("/__init__.py") else ".".join(parts[:-1])
        todo.extend(_imports(tree, package))
    return frozenset(found)


def loaded_closure(repo: Path, modules: Mapping[str, object]) -> frozenset[str]:
    """Every repo file this process has loaded, from its modules' own ``__file__``."""
    root = Path(repo).resolve()
    found: set[str] = set()
    for module in list(modules.values()):
        file = getattr(module, "__file__", None)
        if not isinstance(file, str) or not file:
            continue
        try:
            found.add(Path(file).resolve().relative_to(root).as_posix())
        except (ValueError, OSError):
            continue
    return frozenset(found)


class Rules:
    """The never list for one checkout. The static closure is kept per commit; the loaded one is read each time."""

    def __init__(
        self, repo: Path, *, entries: Iterable[str] = ENTRY_POINTS, modules: Mapping[str, object] | None = None
    ) -> None:
        self.repo = Path(repo)
        self.entries = tuple(entries)
        self._modules = modules
        self._static: tuple[str, frozenset[str]] = ("", frozenset())

    def closure(self, rev: str) -> frozenset[str]:
        if self._static[0] != rev:
            self._static = (rev, static_closure(self.repo, rev, self.entries))
        loaded = loaded_closure(self.repo, sys.modules if self._modules is None else self._modules)
        return self._static[1] | loaded

    def excluded(
        self,
        parent: str,
        tree: str,
        changes: list[tuple[str, str]],
        *,
        catalogue: ModuleType,
        enforced: Iterable[str],
    ) -> list[tuple[str, str]]:
        """(path, why) for every file of the change *parent* -> *tree* that never lands inside a window."""
        closure = self.closure(parent)
        enforced = frozenset(enforced)
        out: list[tuple[str, str]] = []
        for status, path in changes:
            if status == "M" and path in _VERSION_PATHS:
                diff = checks.card_diff(self.repo, parent, tree, "--text", "--unified=2147483647", path=path)
            else:
                diff = "" if status == "D" else checks.file_diff(self.repo, parent, tree, path)
            why = why_never(path, status, added_diff=diff, enforced=enforced, closure=closure, catalogue=catalogue)
            if why:
                out.append((path, why))
        return out


__all__ = ["ENTRY_POINTS", "Rules", "loaded_closure", "static_closure", "why_never"]
