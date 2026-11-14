"""Every model client comes from the models slot, and the sites that still build one directly can only get fewer.

``thomas/core/llm_slot.py`` is the one place that constructs ``LLMClient``. No call site in product code builds one
directly any more (the last one lived in the legacy chat engine, which is deleted), so the list below is empty and its
ceiling is zero. A new direct construction anywhere else fails this test.

The scan reads ``git ls-files`` rather than walking the folder, so an untracked scratch file cannot hide a call and a
checkout with stray files cannot add one. Tests are not scanned: they build clients on purpose to test them.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLOT = "thomas/core/llm_slot.py"
SCANNED_ROOTS = ("thomas/", "scripts/")
CEILING = 0

#: file -> direct constructions it still holds. Empty, and it must stay empty.
DIRECT_SITES: dict[str, int] = {}


def _tracked_python() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.split("\0") if p.startswith(SCANNED_ROOTS) and p != SLOT]


def _mentions_client(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == "LLMClient":
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == "LLMClient":
            return True
        if isinstance(sub, ast.Constant) and sub.value == "LLMClient":
            return True
    return False


def count_direct_constructions(source: str) -> int:
    """Calls of ``LLMClient`` itself, or of a name in the same file that is an alias of it.

    An alias is an assignment from it, an ``import ... as`` of it, or a class that subclasses it.
    """
    tree = ast.parse(source)
    aliases: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is not None and _mentions_client(value):
            aliases.update(t.id for t in targets if isinstance(t, ast.Name) and t.id != "LLMClient")
    for node in ast.walk(tree):
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            aliases.update(a.asname for a in node.names if a.asname and a.name.split(".")[-1] == "LLMClient")
    names = aliases | {"LLMClient"}
    grew = True
    while grew:  # a subclass of a subclass builds a client too
        grew = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name not in names:
                if any(_mentions_client(b) or (isinstance(b, ast.Name) and b.id in names) for b in node.bases):
                    names.add(node.name)
                    grew = True
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            called = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if called in names:
                total += 1
    return total


def scan() -> dict[str, int]:
    found: dict[str, int] = {}
    for rel in _tracked_python():
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            n = count_direct_constructions(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        if n:
            found[rel] = n
    return found


def test_the_allowlist_never_grows() -> None:
    assert sum(DIRECT_SITES.values()) <= CEILING, (
        "the direct-construction list grew; move the site onto the slot instead"
    )
    assert all(n > 0 for n in DIRECT_SITES.values()), "an entry with no sites left should be removed"


def test_no_new_direct_construction_outside_the_slot() -> None:
    found = scan()
    extra = {rel: n for rel, n in found.items() if n > DIRECT_SITES.get(rel, 0)}
    assert not extra, f"LLMClient built directly outside {SLOT}; use models.open(...) instead: {extra}"


def test_the_list_does_not_go_stale() -> None:
    found = scan()
    stale = {rel: n for rel, n in DIRECT_SITES.items() if found.get(rel, 0) < n}
    assert not stale, f"these sites moved onto the slot; lower their counts or remove them: {stale}"


def test_the_scanner_sees_a_direct_call_and_an_alias() -> None:
    assert count_direct_constructions("from x import LLMClient\nc = LLMClient(cfg)\n") == 1
    assert count_direct_constructions("import x\nk = getattr(m, 'LLMClient', None)\nc = k(cfg)\n") == 1
    assert count_direct_constructions("def f(models):\n    return models.open(cfg)\n") == 0


def test_the_scanner_sees_an_import_alias() -> None:
    src = "from thomas.core.llm_client import LLMClient as C\nc = C(cfg)\n"
    assert count_direct_constructions(src) == 1
    assert count_direct_constructions("from thomas.core import llm_client as m\nc = m.LLMClient(cfg)\n") == 1
    assert count_direct_constructions("import thomas.core.llm_client\nc = thomas.core.llm_client.LLMClient(cfg)\n") == 1


def test_the_scanner_sees_a_subclass() -> None:
    src = "from x import LLMClient\nclass X(LLMClient):\n    pass\nc = X(cfg)\n"
    assert count_direct_constructions(src) == 1
    src = "import x\nclass A(x.LLMClient): ...\nclass B(A): ...\nc = B(cfg)\n"
    assert count_direct_constructions(src) == 1
    assert count_direct_constructions("class X:\n    pass\nc = X(cfg)\n") == 0
