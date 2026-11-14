"""A negative text filter avoids parsing unrelated tests without changing selection."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import pytest

from thomas.server.proof import selection


def eager_reached(text: str, imports: frozenset[str] | None, modules: Iterable[str]) -> set[str]:
    imports = selection._imported(text)
    return {
        module
        for module in modules
        if module in imports
        or any(name.startswith(f"{module}.") for name in imports)
        or ("." in module and re.search(rf"(?<![\w.]){re.escape(module)}(?![\w])", text))
    }


def fixture_tree(monkeypatch: pytest.MonkeyPatch, texts: dict[str, str]) -> None:
    monkeypatch.setattr(
        selection, "select", lambda root, changed, **kwargs: selection.select_from(texts, changed, **kwargs)
    )
    monkeypatch.setattr(selection, "_PARSED", {})


def test_unrelated_ascii_tests_are_not_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    texts = {
        "tests/test_direct.py": "from pkg import changed\n",
        "tests/test_unrelated.py": "import unrelated\ndef test_ok(): pass\n",
    }
    fixture_tree(monkeypatch, texts)
    calls: list[str] = []
    original = selection._imported

    def record(text: str) -> frozenset[str]:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(selection, "_imported", record)
    picked = selection.select(Path("."), ["pkg/changed.py"])
    assert picked.files == ("tests/test_direct.py",)
    assert texts["tests/test_unrelated.py"] not in calls
    assert calls == [texts["tests/test_direct.py"]]


@pytest.mark.parametrize(
    "text",
    [
        "import pkg.changed as alias",
        "from pkg import changed as alias",
        "def load():\n    from pkg.changed import function",
        "import pkg.changed.descendant",
        'target = "pkg.changed"',
        'broken = (\n# patch("pkg.changed")',
        "from pkg import ｃｈａｎｇｅｄ",
    ],
)
def test_import_forms_keep_eager_selection(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    texts = {"tests/test_match.py": text, "tests/test_other.py": "import other"}
    fixture_tree(monkeypatch, texts)
    expected = eager_reached(text, None, {"pkg.changed"})
    assert expected == {"pkg.changed"}
    assert selection.select(Path("."), ["pkg/changed.py"]).files == ("tests/test_match.py",)


@pytest.mark.parametrize("cap", [1, 2, 360])
def test_helper_fixed_point_and_cap_match_eager_selection(monkeypatch: pytest.MonkeyPatch, cap: int) -> None:
    texts = {
        "tests/support.py": "from pkg import changed",
        "tests/middle.py": "from tests import support",
        "tests/test_direct.py": "from pkg import changed",
        "tests/test_indirect.py": "from tests import middle",
        "tests/test_other.py": "import other",
        "tests/conftest.py": "import other",
    }
    fixture_tree(monkeypatch, texts)
    lazy = selection.select(Path("."), ["pkg/changed.py"], cap=cap)
    monkeypatch.setattr(selection, "_reached", eager_reached)
    assert selection.select(Path("."), ["pkg/changed.py"], cap=cap) == lazy
    assert lazy.files == ("tests/test_direct.py", "tests/test_indirect.py")[:cap]
    if cap == 1:
        assert lazy.left_out == ("tests/test_indirect.py",)
    else:
        assert lazy.left_out == ()


def test_helper_closure_checks_each_new_frontier_once(monkeypatch: pytest.MonkeyPatch) -> None:
    texts = {"tests/h0.py": "from pkg import changed"}
    texts.update({f"tests/h{i}.py": f"from tests import h{i - 1}" for i in range(1, 12)})
    texts["tests/test_covering.py"] = "from tests import h11"
    visited: list[frozenset[str]] = []
    original = selection._reached

    def count_targets(text, imports, modules):
        visited.append(frozenset(modules))
        return original(text, imports, modules)

    monkeypatch.setattr(selection, "_reached", count_targets)
    picked = selection.select_from(texts, ["pkg/changed.py"])
    assert picked.files == ("tests/test_covering.py",)
    assert len(visited) == len(texts) * (len(texts) + 1)
    seen: set[str] = set()
    for offset in range(0, len(visited), len(texts)):
        frontier = visited[offset]
        assert all(targets == frontier for targets in visited[offset : offset + len(texts)])
        assert frontier.isdisjoint(seen)
        seen.update(frontier)


@pytest.mark.parametrize("via_helper", [False, True])
@pytest.mark.parametrize("scope", ["tests/", "tests/nested/"])
def test_unchanged_conftest_keeps_its_dependent_tests(via_helper: bool, scope: str) -> None:
    texts = {
        "tests/support.py": "from pkg import changed",
        f"{scope}conftest.py": "from tests import support" if via_helper else "from pkg import changed",
        f"{scope}test_covering.py": "def test_ok(fixture_value): pass",
        f"{scope}deeper/test_covering.py": "def test_ok(fixture_value): pass",
        "tests/elsewhere/test_other.py": "def test_other(): pass",
    }
    picked = selection.select_from(texts, ["pkg/changed.py"], cap=1)
    expected = {f"{scope}test_covering.py", f"{scope}deeper/test_covering.py"}
    if scope == "tests/":
        expected.add("tests/elsewhere/test_other.py")
    assert set(picked.files + picked.left_out) == expected


@pytest.mark.parametrize("statement", ["from . import support", "from .support import value"])
def test_relative_helper_import_keeps_covering_tests(statement: str) -> None:
    texts = {
        "tests/support.py": "from pkg import changed\nvalue = 1",
        "tests/test_covering.py": statement,
    }
    assert selection.select_from(texts, ["pkg/changed.py"]).files == ("tests/test_covering.py",)


@pytest.mark.parametrize("statement", ["from .. import support", "from ..support import value"])
def test_parent_relative_helper_import_keeps_covering_tests(statement: str) -> None:
    texts = {
        "tests/support.py": "from pkg import changed\nvalue = 1",
        "tests/nested/middle.py": statement,
        "tests/nested/test_covering.py": "from . import middle",
    }
    assert selection.select_from(texts, ["pkg/changed.py"]).files == ("tests/nested/test_covering.py",)


@pytest.mark.parametrize("continuation", [" ", "\\\n    ", "\\\r\n    "])
def test_relative_import_of_changed_package_does_not_need_leaf_in_source(continuation: str) -> None:
    statement = f"from{continuation}.. import value"
    compile(statement, "<relative import>", "exec")
    texts = {"tests/__init__.py": "value = 1", "tests/nested/test_covering.py": statement}
    assert selection.select_from(texts, ["tests/__init__.py"]).files == ("tests/nested/test_covering.py",)


def test_each_relevant_source_is_processed_once_across_helper_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    texts = {
        "tests/support.py": "from pkg import changed",
        "tests/middle.py": "from tests import support",
        "tests/test_indirect.py": 'from tests import middle\nlabel = "changed"',
        "tests/test_unrelated.py": "import other",
    }
    fixture_tree(monkeypatch, texts)
    calls: list[str] = []
    original = selection._imported

    def record(text: str) -> frozenset[str]:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(selection, "_imported", record)
    picked = selection.select(Path("."), ["pkg/changed.py"])
    assert picked.files == ("tests/test_indirect.py",)
    assert picked.left_out == ()
    assert set(calls) == set(texts.values()) - {texts["tests/test_unrelated.py"]}
    assert len(calls) == len(set(calls))


@pytest.mark.parametrize("changed", ["pkg/changed.py", "tests/test_base.py"])
@pytest.mark.parametrize("statement", ["from tests.test_base import helper", "from .test_base import helper"])
def test_test_module_helpers_keep_transitive_covering_tests(changed: str, statement: str) -> None:
    texts = {
        "tests/test_base.py": "from pkg import changed\ndef helper(): pass",
        "tests/test_middle.py": statement,
        "tests/test_covering.py": "from .test_middle import helper",
        "tests/test_unrelated.py": "import other",
    }
    picked = selection.select_from(texts, [changed])
    assert set(picked.files) == {"tests/test_base.py", "tests/test_middle.py", "tests/test_covering.py"}
    assert not picked.left_out


@pytest.mark.parametrize("helper", ["support", "test_base"])
@pytest.mark.parametrize(
    "statement",
    [
        "import {helper}",
        "import tests.{helper}",
        "from {helper} import value",
        "from tests.{helper} import value",
        "from .{helper} import value",
        "from . import {helper}",
    ],
)
@pytest.mark.parametrize("cap", [0, 1, 360])
def test_deleted_helper_keeps_its_direct_and_transitive_importers(helper: str, statement: str, cap: int) -> None:
    texts = {
        "tests/test_middle.py": statement.format(helper=helper),
        "tests/test_covering.py": "from .test_middle import value",
        "tests/test_unrelated.py": "import other",
    }
    picked = selection.select_from(texts, [f"tests/{helper}.py"], cap=cap)
    assert set((*picked.files, *picked.left_out)) == {"tests/test_middle.py", "tests/test_covering.py"}
    assert len(picked.files) == min(cap, 2)


@pytest.mark.parametrize("deleted", [False, True])
@pytest.mark.parametrize("helper", ["support", "test_base"])
@pytest.mark.parametrize("statement", ["import {helper}", "from {helper} import value"])
@pytest.mark.parametrize("cap", [0, 1, 360])
def test_nested_helper_keeps_bare_and_transitive_importers(
    deleted: bool, helper: str, statement: str, cap: int
) -> None:
    sources = {
        "tests/nested/middle.py": statement.format(helper=helper),
        "tests/nested/test_covering.py": "from .middle import value",
        "tests/test_unrelated.py": "import other",
    }
    path = f"tests/nested/{helper}.py"
    if not deleted:
        sources[path] = "value = 1"
    picked = selection.select_from(sources, [path], cap=cap)
    expected = {"tests/nested/test_covering.py"}
    if helper == "test_base" and not deleted:
        expected.add(path)
    assert set(picked.files + picked.left_out) == expected
    assert len(picked.files) == min(cap, len(expected))


@pytest.mark.parametrize("statement", ["import support", "from support import value", "from .support import value"])
def test_deleted_helper_is_selected_from_the_surviving_checkout(tmp_path: Path, statement: str) -> None:
    texts = {
        "tests/test_architecture.py": "def test_architecture(): pass",
        "tests/middle.py": statement,
        "tests/test_direct.py": statement,
        "tests/test_transitive.py": "from .middle import value",
        "tests/test_unrelated.py": "import unrelated",
    }
    for rel, text in texts.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert not (tmp_path / "tests/support.py").exists()
    picked = selection.select(tmp_path, ["tests/support.py"])
    assert set(picked.files) == {
        "tests/test_architecture.py",
        "tests/test_direct.py",
        "tests/test_transitive.py",
    }
    assert not picked.left_out


@pytest.mark.parametrize("cap", [0, 1, 360])
@pytest.mark.parametrize("cause", ["deleted", "changed", "production", "helper", "asset"])
@pytest.mark.parametrize(
    "statement",
    ["import conftest", "import tests.nested.conftest", "from tests.nested.conftest import value"],
)
def test_conftest_keeps_explicit_importers_outside_its_scope(
    tmp_path: Path, cap: int, cause: str, statement: str
) -> None:
    texts = {
        "tests/nested/test_scoped.py": "def test_scoped(): pass",
        "tests/middle.py": statement,
        "tests/test_direct.py": statement,
        "tests/test_transitive.py": "from .middle import value",
        "tests/test_unrelated.py": "import unrelated",
    }
    changed = "tests/nested/conftest.py"
    if cause != "deleted":
        texts[changed] = "value = 1"
    if cause in {"production", "helper"}:
        changed = "pkg/implementation.py" if cause == "production" else "tests/support.py"
        texts[changed] = "value = 1"
        module = changed.removesuffix(".py").replace("/", ".")
        texts["tests/nested/conftest.py"] = f"from {module} import value"
    elif cause == "asset":
        changed = "web/template.html"
        texts["tests/nested/conftest.py"] = 'value = open("web/template.html").read()'
    for rel, text in texts.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    expected = {"tests/nested/test_scoped.py", "tests/test_direct.py", "tests/test_transitive.py"}
    for picked in (selection.select_from(texts, [changed], cap=cap), selection.select(tmp_path, [changed], cap=cap)):
        assert set(picked.files + picked.left_out) == expected
        assert len(picked.files) == min(cap, len(expected))


def test_changed_conftest_still_selects_its_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_tree(
        monkeypatch,
        {
            "tests/conftest.py": "import unrelated",
            "tests/test_scoped.py": "def test_ok(): pass",
        },
    )
    assert selection.select(Path("."), ["tests/conftest.py"]).files == ("tests/test_scoped.py",)
