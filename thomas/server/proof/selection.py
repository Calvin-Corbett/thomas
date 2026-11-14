"""Which test files prove a change: its own, the architecture test, and every test file that imports what it changes.

You named the set by hand on 2026-09-25: "the patch's own test files, tests/test_architecture.py, and
every test file that imports a module the patch changes". :func:`select` returns that set, and says what it
left out.

The third part used to be a text search for each changed module's file stem. A stem like ``catalog``,
``quota`` or ``brain`` appears in hundreds of test files that never import the module. For 46162bf1 the
search chose 748 files, for 2a23ea2b 365 and for 820602fd 203. The 60-file cap then silently dropped the
real importers: 3 of 28, 14 of 53, and for 820602fd 10 of the 18 test files it broke. Those 18 all reached
``thomas.server.routes.chat_v2`` either by a real import (``from thomas.server.routes import chat_v2``,
sometimes inside a test function) or by its dotted name in a ``patch(...)`` target. So a test file is
chosen here by what it actually names:

* an ``import`` or ``from ... import`` of a changed module, at any depth in the file (read with
  :mod:`ast`), including ``from package import module``;
* the changed module's dotted name anywhere in its text, which is how ``patch("a.b.c.X")`` names it;
* a helper module under ``tests/`` (``tests/_fakes.py``, a support module) that the change touches or that
  reaches a changed module itself, imported by the test file;
* last, for a changed ``conftest.py``, every test file under its folder, because pytest loads it for all of
  them.

The order is also the order of priority: each tier is ranked by how many changed modules a file reaches.
Past :data:`CAP` the rest are not run, and :attr:`Selection.left_out` names them, so the card can say how
many test files were not run instead of claiming every importer ran.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from thomas.core.git_process import run_git

TESTS_DIR = "tests"
# Always run, whatever changed: the repo's own size and layering rules. Of the two hand-ins that reached
# your card unchecked on 2026-09-25, you said that "between them they took thomas/core/llm_client.py past
# the 800-line limit (tests/test_architecture.py failed on dev)". 820602fd took that file from 775 lines to
# 815. It carried 13 test files of its own and this was not one of them, so without this entry the proof
# would have run its 13, passed, and still let the change through. The plugin tests hold what may reach a plugin, what a
# plugin may reach and that everything belongs to one, and a change anywhere in the repo can break those.
ALWAYS = (
    "tests/test_architecture.py",
    "tests/test_nothing_reaches_past_a_plugins_door.py",
    "tests/test_plugins_stay_fenced.py",
    "tests/test_everything_is_a_plugin.py",
    "tests/test_the_shell_adds_no_routes.py",
    "tests/test_every_command_runs_through_the_sandbox_slot.py",
)
# A row's file is loaded by name from thomas/server/rows/default.toml, so no test imports it and the search below finds
# nothing. Every row answers to one proof all the same, so a change to a row's file runs it by where the file lives.
ROW_HOME = "thomas/server/rows/"
ROW_PROOF = "tests/test_every_row_keeps_its_promises.py"
# The most test files one proof runs. The real importers of 820602fd's 24 changed modules number about 83,
# plus its own 13 and the architecture test. The cap was 120 while each copy ran one pytest process (a real check of
# 60 files took 1,321 s); spec 2026-10-12 Part 1 item 8 raised it to 360 once the change's tests run once, across the
# machine-wide pool. A change that reaches more files than this is proven on the closest :data:`CAP`, and the card
# says how many were not run (:attr:`Selection.left_out`).
CAP = 360
# The two files a release moves its version in. thomas/__init__.py is the package itself, so a change to it reaches every
# test that imports Thomas: 1,992 of 2,085 files, for one line, in 10 of the 13 capped hand-ins with a file list.
VERSION_FILES = ("pyproject.toml", "thomas/__init__.py")
_VERSION_LINE = re.compile(r"""(?:__version__|version)\s*=\s*["'][^"']*["']""")
# sys.modules.get("a.b"), sys.modules["a.b"], "a.b" in sys.modules: a question, which loads and depends on nothing.
_ASKS_SYS_MODULES = re.compile(
    r"""sys\.modules(?:\.get\(\s*|\[\s*)["'][\w.]+["']|["'][\w.]+["']\s+(?:not\s+)?in\s+sys\.modules"""
)
_CONFTEST = "conftest.py"
_PARSED_MAX = 4096
_PARSED: dict[bytes, frozenset[str]] = {}


@dataclass(frozen=True)
class Selection:
    """The test files a proof runs, in order, and the ones it chose but did not run because of the cap."""

    files: tuple[str, ...]
    left_out: tuple[str, ...] = ()


def version_bumps(patch: str) -> frozenset[str]:
    """The :data:`VERSION_FILES` *patch* changes by one version line and nothing else: no import can feel that.

    The file alone proves nothing, since thomas/__init__.py holds real code too: only the diff does.
    """
    bumps = set()
    for section in re.split(r"(?m)^(?=diff --git )", patch.replace("\r\n", "\n")):
        head, _, hunks = section.partition("\n@@")
        path = next((rel for rel in VERSION_FILES if head.startswith(f"diff --git a/{rel} b/{rel}\n")), None)
        changed = [line for line in hunks.split("\n")[1:] if line[:1] in ("+", "-")]
        if path and [line[0] for line in changed] == ["-", "+"]:
            if all(_VERSION_LINE.fullmatch(line[1:].strip()) for line in changed):
                bumps.add(path)
    return frozenset(bumps)


def _reads_version(text: str) -> bool:
    return "__version__" in text or ("pyproject.toml" in text and "version" in text)


def _posix(rel: str) -> str:
    return str(rel).replace("\\", "/")


def _is_test_file(rel: str) -> bool:
    name = Path(rel).name
    return _posix(rel).startswith(f"{TESTS_DIR}/") and name.startswith("test_") and name.endswith(".py")


def _dotted(rel: str) -> str:
    """``thomas/server/green_handoff.py`` -> ``thomas.server.green_handoff``; "" for a file that is not Python."""
    path = _posix(rel)
    if not path.endswith(".py"):
        return ""
    parts = path[:-3].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else ""


def _module_names(rel: str) -> set[str]:
    """Keep repository and conventional src-layout import names."""
    dotted = _dotted(rel)
    names = {dotted} if dotted else set()
    parts = dotted.split(".")
    for index, part in enumerate(parts[:-1]):
        if part == "src":
            names.add(".".join(parts[index + 1 :]))
    return names


def _helper_names(rel: str) -> set[str]:
    """Keep helper aliases when a test directory is itself on Python's import path."""
    dotted = _dotted(rel)
    if dotted.startswith(f"{TESTS_DIR}."):
        parts = dotted.split(".")
        return {".".join(parts[index:]) for index in range(len(parts))}
    return _module_names(rel)


def _imported(text: str) -> frozenset[str]:
    """Every module name *text* imports, at any depth. ``from a.b import c`` gives ``a.b`` and ``a.b.c``."""
    key = hashlib.sha256(text.encode("utf-8", "surrogatepass")).digest()
    known = _PARSED.get(key)  # one read: checks select side by side, and another may clear the cache between two
    if known is not None:
        return known
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        names = frozenset()  # a file that does not parse is still searched for dotted names
    else:
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                found.add(module)
                separator = "" if module.endswith(".") else "."
                found.update(f"{module}{separator}{alias.name}" for alias in node.names)
        names = frozenset(found)
    if len(_PARSED) >= _PARSED_MAX:
        _PARSED.clear()
    _PARSED[key] = names
    return names


def _reached(text: str, imports: frozenset[str] | None, modules: Iterable[str]) -> set[str]:
    """Which of *modules* a file imports (the module itself or anything below it) or names by its dotted path.

    Importing ``a.b.c`` runs ``a/b/__init__.py`` too, so a changed package is reached through any submodule.
    """
    found: set[str] = set()
    ascii_text = text.isascii()
    spoken = ""  # the text without what only asks whether a module is loaded
    for module in modules:
        # Python normalizes Unicode identifiers; only ASCII can safely use this negative filter.
        if ascii_text and module.rsplit(".", 1)[-1] not in text:
            if imports is None or not any(name == module or name.startswith(module + ".") for name in imports):
                continue
        if imports is None:
            imports = _imported(text)
        below = f"{module}."
        if module in imports or any(name.startswith(below) for name in imports):
            found.add(module)
        elif "." in module:
            spoken = spoken or _ASKS_SYS_MODULES.sub("", text)
            if re.search(rf"(?<![\w.]){re.escape(module)}(?![\w])", spoken):
                found.add(module)  # a patch("...") target, an importlib string: a bare top-level name is too common
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _ranked(scores: dict[str, int]) -> list[str]:
    return [rel for rel, _ in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))]


def _conftest_scopes(changed: Iterable[str]) -> list[str]:
    """The folders a changed ``conftest.py`` under ``tests/`` applies to, as ``tests/...`` prefixes ending in /."""
    scopes = []
    for rel in changed:
        path = _posix(rel)
        if path == _CONFTEST:
            scopes.append(f"{TESTS_DIR}/")
        elif path.startswith(f"{TESTS_DIR}/") and Path(path).name == _CONFTEST:
            scopes.append(path[: -len(_CONFTEST)])
    return scopes


def select(root: Path, changed: Sequence[str], *, cap: int = CAP, bumps: Collection[str] = ()) -> Selection:
    """The test files that prove *changed* in the copy at *root*, repo-relative and in order, and what the cap cut.

    Only ``tests/`` is read, as before 2026-10-26. From then the whole checkout was read to follow imports through
    every production module: on 2026-10-27 one selection took 20 to 83 minutes and chose 1,892 to 1,961 test files,
    and no check finished. Over ``tests/`` alone the same logic took 12.9 s and chose 49 files for a change to
    ``precard/check.py`` and ``hand_in_hold.py``. :func:`select_from` still follows production modules a caller
    passes it.
    """
    root = Path(root)
    tests_dir = root / TESTS_DIR
    every = sorted(tests_dir.rglob("*.py")) if tests_dir.is_dir() else []
    sources = {path.relative_to(root).as_posix(): _read(path) for path in every}
    return select_from(sources, changed, cap=cap, bumps=bumps, shared_names=_shared_names(root, changed))


def _shared_names(root: Path, changed: Sequence[str]) -> frozenset[str]:
    """The names of changed files that are not Python which more than one tracked file in the checkout has.

    Git is asked only when the change holds such a file, and once. Nothing is shared when git cannot say: the name
    alone then selects, as it did before."""
    wanted = {Path(_posix(rel)).name for rel in changed if not _posix(rel).endswith(".py")}
    if not wanted:
        return frozenset()
    listed = run_git(["-C", str(root), "ls-files", "-z"], timeout=30)
    if not listed.ok:
        return frozenset()
    counts = Counter(name.rsplit("/", 1)[-1] for name in listed.output().split("\0") if name)
    return frozenset(name for name in wanted if counts[name] > 1)


def select_from(
    texts: Mapping[str, str],
    changed: Sequence[str],
    *,
    cap: int = CAP,
    bumps: Collection[str] = (),
    shared_names: Collection[str] = (),
) -> Selection:
    """:func:`select` over repo-relative Python source text, including production intermediaries.

    Callers without a checkout can supply sources read directly from a Git tree. *bumps* are the changed files that
    :func:`version_bumps` proved move only the version: they stand for the tests that read it, not for what imports them.
    *shared_names* are file names several files in the checkout have (``README.md``): a changed file with such a name
    selects a test only when the test names its folder too. On 2026-11-10 ``extensions/README.md`` alone chose 229 of
    a check's 235 test files, because 131 test files say ``README.md`` and the checkout holds 50 files of that name.
    """
    texts = {_posix(rel): str(text) for rel, text in texts.items() if _posix(rel).endswith(".py")}
    texts = dict(sorted(texts.items()))  # one order, however the caller read them
    changed = [_posix(rel) for rel in changed if _posix(rel) not in bumps]
    chosen: list[str] = [rel for rel in changed if _is_test_file(rel)]
    chosen += [rel for rel in ALWAYS if rel not in chosen]
    if any(rel.startswith(ROW_HOME) for rel in changed):
        chosen.append(ROW_PROOF)
    if bumps:
        chosen += [rel for rel, text in texts.items() if _is_test_file(rel) and _reads_version(text)]
    modules = {name for rel in changed if not rel.startswith(f"{TESTS_DIR}/") for name in _module_names(rel)}
    named = {rel for rel in changed if not rel.endswith(".py") and not rel.startswith(f"{TESTS_DIR}/")}
    # (name, folder): the folder is asked for only when several files share the name; "" asks for the name alone.
    pages = {(Path(rel).name, Path(rel).parent.name if Path(rel).name in shared_names else "") for rel in named}
    pages = {(name, folder) for name, folder in pages if len(name) >= 5}
    asset_mentions = {
        rel: sum(1 for name, folder in pages if name in text and (not folder or folder in text))
        for rel, text in texts.items()
    }
    imports: dict[str, frozenset[str]] = {}

    def reached(rel: str, targets: set[str]) -> set[str]:
        text = texts[rel]
        if rel not in imports and (
            not text.isascii()
            or any(name.rsplit(".", 1)[-1] in text for name in targets)
            or re.search(r"\bfrom(?:\s|\\\r?\n)*\.", text)
        ):
            raw = _imported(text)
            package = _dotted(rel).split(".")
            if Path(rel).name != "__init__.py":
                package = package[:-1]
            resolved = set()
            for name in raw:
                level = len(name) - len(name.lstrip("."))
                if not level:
                    resolved.add(name)
                elif level <= len(package):
                    prefix = package[: len(package) - level + 1]
                    tail = name[level:]
                    resolved.add(".".join([*prefix, *([tail] if tail else [])]))
            imports[rel] = frozenset(resolved)
        return _reached(text, imports.get(rel), targets)

    # Conftests also have explicit importers outside their fixture scopes.
    helpers = set(texts)

    def importer_closure(seeds: set[str]) -> dict[str, set[str]]:
        hits: dict[str, set[str]] = {rel: set() for rel in texts}
        reaching = seeds.copy()
        frontier = reaching.copy()
        while frontier:
            for rel in texts:
                hits[rel] |= reached(rel, frontier)
            discovered = {name for rel in helpers if hits[rel] for name in _helper_names(rel)} - reaching
            reaching |= discovered
            frontier = discovered
        return hits

    reaching = {name for rel in changed if rel.startswith(f"{TESTS_DIR}/") for name in _helper_names(rel)}
    direct_hits = {rel: reached(rel, modules) for rel in texts}
    reaching |= {name for rel in helpers if direct_hits[rel] for name in _helper_names(rel)}
    helper_hits = importer_closure(reaching)
    # Asset readers can be production modules or test helpers, not just tests. Keep their closure separate
    # so asset-only chains cannot displace importers of changed Python modules within the ranking.
    asset_hits = importer_closure({name for rel in helpers if asset_mentions[rel] for name in _helper_names(rel)})

    direct: dict[str, int] = {}
    through_helper: dict[str, int] = {}
    through_asset: dict[str, int] = {}
    for rel in texts:
        if not _is_test_file(rel) or rel in chosen:
            continue
        if score := len(direct_hits[rel]):
            direct[rel] = score
        elif score := len(helper_hits[rel]):
            through_helper[rel] = score
        elif score := len(asset_hits[rel]):
            through_asset[rel] = score
    # Direct asset-name readers remain after importers, including asset-seeded helper chains.
    mentions = {
        rel: score
        for rel, score in asset_mentions.items()
        if _is_test_file(rel) and rel not in chosen and rel not in direct and rel not in through_helper
        if rel not in through_asset and score
    }
    chosen += _ranked(direct) + _ranked(through_helper) + _ranked(through_asset) + _ranked(mentions)
    dependent_conftests = [
        rel
        for rel in texts
        if Path(rel).name == _CONFTEST
        and (direct_hits[rel] or helper_hits[rel] or asset_hits[rel] or asset_mentions[rel])
    ]
    scopes = _conftest_scopes([*changed, *dependent_conftests])
    chosen += [rel for rel in texts if _is_test_file(rel) and any(rel.startswith(s) for s in scopes)]

    present = [rel for rel in dict.fromkeys(chosen) if rel in texts]  # a file the change deleted is not run
    limit = max(0, cap)
    return Selection(tuple(present[:limit]), tuple(present[limit:]))


def proof_set(root: Path, changed: Sequence[str], *, cap: int = CAP) -> list[str]:
    """:func:`select`'s files alone, for a caller that does not report the cut."""
    return list(select(root, changed, cap=cap).files)


__all__ = [
    "ALWAYS",
    "CAP",
    "TESTS_DIR",
    "VERSION_FILES",
    "Selection",
    "proof_set",
    "select",
    "select_from",
    "version_bumps",
]
