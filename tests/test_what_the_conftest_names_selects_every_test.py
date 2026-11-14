"""A module tests/conftest.py depends on selects every test, so it depends on as few as it can.

Selection is right to run everything when a conftest reaches a changed module: a fixture every test uses may change.
The cost is real, though. thomas/server/green_checkout.py selected 1,994 of 2,085 test files in the 12 hand-ins that
touched it, because one fixture read a constant through it, and two modules did the same because the conftest only asks
whether they are loaded yet, which depends on nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.server.proof import selection

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/test_unrelated.py"


def _select(conftest: str) -> tuple[str, ...]:
    texts = {"tests/conftest.py": conftest, TEST: "def test_it() -> None:\n    pass\n"}
    return selection.select_from(texts, ["thomas/server/session.py"]).files


@pytest.mark.parametrize(
    "asks",
    [
        'if found := sys.modules.get("thomas.server.session"):\n    found.reset()\n',
        'sys.modules["thomas.server.session"].reset()\n',
        'if "thomas.server.session" in sys.modules:\n    pass\n',
        'if "thomas.server.session" not in sys.modules:\n    pass\n',
    ],
)
def test_asking_whether_a_module_is_loaded_does_not_depend_on_it(asks: str) -> None:
    assert TEST not in _select(f"import sys\n\n{asks}")


@pytest.mark.parametrize(
    "reaches",
    [
        "from thomas.server import session\n",
        'importlib.import_module("thomas.server.session")\n',
        'patch("thomas.server.session.reset")\n',
        'sys.modules.pop("thomas.server.session")\n',  # it will be imported again
        'monkeypatch.setitem(sys.modules, "thomas.server.session", fake)\n',
    ],
)
def test_anything_that_really_reaches_a_module_still_selects_every_test(reaches: str) -> None:
    assert TEST in _select(reaches)


def test_the_conftest_takes_the_green_root_setting_from_where_it_lives() -> None:
    assert "green_checkout" not in (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
