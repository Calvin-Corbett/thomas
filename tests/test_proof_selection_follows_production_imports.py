"""Covering tests remain selected through production import chains."""

from pathlib import Path

import pytest

from thomas.server.proof import selection


@pytest.mark.parametrize("statement", ["from .implementation import value", "from pkg import implementation"])
@pytest.mark.parametrize("cap", [0, 1, 360])
def test_production_intermediaries_keep_covering_tests(statement: str, cap: int) -> None:
    sources = {
        "pkg/implementation.py": "value = 1",
        "pkg/api.py": statement,
        "pkg/__init__.py": "from .api import value",
        "tests/test_api.py": "from pkg.api import value",
        "tests/test_package.py": "from pkg import value",
        "tests/test_unrelated.py": "import unrelated",
    }
    picked = selection.select_from(sources, ["pkg/implementation.py"], cap=cap)
    assert set(picked.files + picked.left_out) == {"tests/test_api.py", "tests/test_package.py"}


@pytest.mark.parametrize("conftest_changed", [False, True])
def test_root_conftest_keeps_all_fixture_consumers(conftest_changed: bool) -> None:
    sources = {
        "pkg/implementation.py": "value = 1",
        "pkg/api.py": "from .implementation import value",
        "conftest.py": "from pkg.api import value",
        "tests/test_api.py": "def test_value(fixture_value): pass",
        "tests/nested/test_other.py": "def test_other(fixture_value): pass",
    }
    changed = ["conftest.py" if conftest_changed else "pkg/implementation.py"]
    picked = selection.select_from(sources, changed, cap=1)
    assert set(picked.files + picked.left_out) == {"tests/test_api.py", "tests/nested/test_other.py"}


@pytest.mark.parametrize("prefix", ["src", "extensions/example/src"])
@pytest.mark.parametrize("deleted", [False, True])
@pytest.mark.parametrize("cap", [0, 1, 360])
def test_src_layout_keeps_direct_and_transitive_importers(prefix: str, deleted: bool, cap: int) -> None:
    sources = {
        f"{prefix}/pkg/api.py": "from .implementation import value",
        f"{prefix}/pkg/__init__.py": "from .api import value",
        "tests/test_direct.py": "from pkg.implementation import value",
        "tests/test_api.py": "from pkg.api import value",
        "tests/test_package.py": "from pkg import value",
        "tests/test_unrelated.py": "import unrelated",
    }
    changed = f"{prefix}/pkg/implementation.py"
    if not deleted:
        sources[changed] = "value = 1"
    picked = selection.select_from(sources, [changed], cap=cap)
    assert set(picked.files + picked.left_out) == {
        "tests/test_direct.py",
        "tests/test_api.py",
        "tests/test_package.py",
    }
    assert len(picked.files) == min(cap, 3)


def test_checkout_selection_reads_only_the_tests_folder(tmp_path: Path) -> None:
    # Reading the whole checkout chose 1,892 to 1,961 files and took 20 to 83 minutes a selection (2026-10-27).
    sources = {
        "pkg/implementation.py": "value = 1",
        "pkg/api.py": "from .implementation import value",
        "tests/test_api.py": "from pkg.api import value",
        "tests/test_direct.py": "from pkg.implementation import value",
        "tests/test_unrelated.py": "import unrelated",
    }
    for relative, text in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert selection.select(tmp_path, ["pkg/implementation.py"]).files == ("tests/test_direct.py",)
    assert selection.select_from(sources, ["pkg/implementation.py"]).files == (
        "tests/test_direct.py",
        "tests/test_api.py",
    )
