"""Select tests from a candidate's Git tree, with ratchet-specific proof fallbacks.

The shared proof selector handles changed tests, Python imports, patch targets,
helpers and conftest scopes. The ratchet additionally selects tests naming changed
non-Python paths and its whole-app audit for server changes. Architecture runs
last when present so the limit reserves a place for it.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from thomas.server.proof import select_from
from thomas.server.ratchet.gitrepo import Repo

MAX_FILES = 300
SHARD_FILES = 30
ARCHITECTURE_TEST = "tests/test_architecture.py"
APP_TESTS = ("tests/test_server_csrf_audit.py",)
_PACKAGES = ("thomas/", "scripts/", "tests/")
_WORD_END = "([^A-Za-z0-9_]|$)"


@dataclass(frozen=True)
class ProofSet:
    files: tuple[str, ...]
    left_out: int = 0
    gone: tuple[str, ...] = ()  # changed tests present in the base but absent in the candidate

    def shards(self, size: int = SHARD_FILES) -> list[list[str]]:
        return [list(self.files[i : i + size]) for i in range(0, len(self.files), size)]


def is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith("tests/") and name.startswith("test_") and name.endswith(".py")


def module_name(path: str) -> str:
    """The importable Python module at *path*, or an empty string."""
    if not path.endswith(".py") or not path.startswith(_PACKAGES):
        return ""
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts and all(p.isidentifier() for p in parts) else ""


def import_patterns(module: str) -> list[str]:
    """Legacy POSIX extended regexes for direct imports of *module*.

    Selection uses the shared parser instead; this helper remains public for callers
    that need the old git-grep patterns.
    """
    head = f"^[[:space:]]*(from|import)[[:space:]]+{re.escape(module)}{_WORD_END}"
    parent, _, leaf = module.rpartition(".")
    if not parent:
        return [head]
    tail = (
        f"^[[:space:]]*from[[:space:]]+{re.escape(parent)}[[:space:]]+import[[:space:]]"
        f"(.*[^A-Za-z0-9_])?{leaf}{_WORD_END}"
    )
    return [head, tail]


def _text(blob: bytes) -> str:
    """A test file's text as ``git show`` read it: UTF-8, bad bytes replaced, every line ending a newline."""
    return blob.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def read_tests(repo: Repo, tree: str) -> tuple[list[str], dict[str, str]]:
    """Every path under ``tests/`` in *tree*, and the text of each ``.py`` file there: two git processes in all."""
    entries = []
    for row in repo.run("ls-tree", "-r", "-z", tree, "--", "tests").stdout.split("\0"):
        meta, tab, path = row.partition("\t")
        if tab:
            entries.append((meta.split(), path))
    oids = {path: meta[2] for meta, path in entries if len(meta) == 3 and meta[1] == "blob" and path.endswith(".py")}
    read = repo.blobs(list(oids.values()))
    return [path for _meta, path in entries], {path: _text(read[oid]) for path, oid in oids.items()}


def select(
    repo: Repo,
    tree: str,
    changed: Sequence[str],
    *,
    base: str = "",
    limit: int = MAX_FILES,
    without: Collection[str] = (),
) -> ProofSet:
    """Select candidate-tree tests, reserving the architecture test when present.

    With *base*, changed tests missing from the candidate are returned in ``gone``
    so the caller can run them against the base tree. Files in *without* are read
    as absent from the tree (``proof_need``: ones a repair is told to keep as dev has them).
    """
    tree = repo.out("rev-parse", f"{tree}^{{tree}}")
    paths, texts = read_tests(repo, tree)
    if without:
        paths = [path for path in paths if path not in without]
        texts = {path: text for path, text in texts.items() if path not in without}
    present = set(paths)
    # Leave the shared selector uncapped: ratchet applies its own priority and
    # reserves a slot for architecture only after adding its extra fallbacks.
    shared = select_from(texts, changed, cap=len(texts))
    ranked = [path for path in shared.files if path != ARCHITECTURE_TEST]
    for path in dict.fromkeys(p for p in changed if not module_name(p) and not is_test_file(p)):
        ranked.extend(test for test, text in texts.items() if is_test_file(test) and path in text)
    if any(path.startswith("thomas/server/") for path in changed):
        ranked.extend(path for path in APP_TESTS if path in present)
    wanted = list(dict.fromkeys(path for path in ranked if is_test_file(path) and path in present))
    has_architecture = ARCHITECTURE_TEST in present
    room = max(0, limit - int(has_architecture))
    chosen = wanted[:room]
    if has_architecture and limit > 0:
        chosen.append(ARCHITECTURE_TEST)
    gone = tuple(
        path
        for path in dict.fromkeys(changed)
        if base and is_test_file(path) and path not in present and repo.has_path(base, path)
    )
    return ProofSet(tuple(chosen), max(0, len(wanted) - room), gone)


__all__ = [
    "APP_TESTS",
    "ARCHITECTURE_TEST",
    "MAX_FILES",
    "SHARD_FILES",
    "ProofSet",
    "import_patterns",
    "is_test_file",
    "module_name",
    "read_tests",
    "select",
]
