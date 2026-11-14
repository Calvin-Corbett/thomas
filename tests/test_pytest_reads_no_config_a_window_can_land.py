"""Every config file the installed pytest reads stays off a window, in any spelling, and the window's lane sends a
change with one to its card (2026-10-14 review, C1 and C2).

These ask pytest itself which names it reads, so a name a later pytest adds fails here before it can land, check each
at three depths and in other cases, and hand the lane a change with each spelling the review found landing. The lane's
own world, stand-ins and fixtures (tests/test_a_checked_change_lands_inside_your_window.py): its own git repo and tmp
cage folder (tests/conftest.py points the cage root at tmp).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.config.findpaths import locate_config
from scripts.cage import card_catalogue, window_rules

from tests.test_a_checked_change_lands_inside_your_window import (  # noqa: F401 - fixtures
    SID,
    World,
    _hand_in,
    blue,
    pins,
    world,
)

_INI = "[pytest]\nminversion = 1\n"
# Each with content its form accepts. The known names, and names a later pytest might read.
_CANDIDATES = {
    "pytest.toml": '[pytest]\nminversion = "1"\n',
    ".pytest.toml": '[pytest]\nminversion = "1"\n',
    "pytest.ini": _INI,
    ".pytest.ini": _INI,
    "pyproject.toml": '[tool.pytest.ini_options]\nminversion = "1"\n',
    "tox.ini": _INI,
    "setup.cfg": "[tool:pytest]\nminversion = 1\n",
    "pytest.cfg": _INI,
    ".pytest.cfg": _INI,
    "pytest.yaml": "pytest:\n  minversion: 1\n",
    "conftest.ini": _INI,
}


def _never(path: str) -> str:
    return window_rules.why_never(path, "A", added_diff="", enforced=(), closure=frozenset(), catalogue=card_catalogue)


def test_every_config_name_pytest_reads_is_on_the_never_list(tmp_path: Path) -> None:
    read: list[str] = []
    for name, text in _CANDIDATES.items():
        folder = tmp_path / name.replace(".", "_")
        (folder / "tests" / "deep").mkdir(parents=True)
        (folder / "tests" / name).write_text(text, encoding="utf-8")
        _root, found, _cfg, _ignored = locate_config(folder / "tests" / "deep", [folder / "tests" / "deep"])
        if found is not None and found.name == name:
            read.append(name)
    assert {"pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg"} <= set(read), "the probe works"
    for name in read:
        for path in (f"tests/{name}", f"tests/sub/{name.upper()}", f"thomas/tools/{name}", f"Tests/{name.title()}"):
            assert "runs as you" in _never(path), f"pytest reads {name}, and {path} could land in a window"


@pytest.mark.parametrize(
    "path", ["thomas/tools/x.PS1", "thomas/tools/x.Cmd", "thomas/tools/x.BAT", "thomas/tools/x.VBS"]
)
def test_a_launcher_in_another_case_stays_off_a_window(path: str) -> None:
    assert "runs as you" in _never(path)
    assert "runs as you" in _never(path.casefold()), "the lower-case spelling is the rule being matched"


def test_a_plain_module_a_test_and_a_test_helper_may_land() -> None:
    assert _never("thomas/tools/fix_me.py") == ""
    assert _never("tests/test_fix_me.py") == ""
    # Test helpers land in a window since 2026-10-25 ("all changes should be through express lane"), in any case.
    assert _never("tests/helper.py") == "" and _never("Tests/Helper.py") == ""


@pytest.mark.parametrize(
    "path",
    [
        "tests/.pytest.ini",
        "tests/pytest.toml",
        "tests/.pytest.toml",
        "tests/PYTEST.INI",
        "tests/sub/TOX.INI",
        "tests/Setup.CFG",
        "thomas/tools/PYTEST.INI",
        "tests/Conftest.py",
        "tests/CONFTEST.PY",
        "thomas/tools/conftest.py",
        "thomas/tools/PyProject.toml",
    ],
)
def test_the_lane_sends_a_change_with_a_pytest_config_in_any_spelling_to_its_card(world: World, path: str) -> None:
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n", path: _INI})
    world.open()

    assert world.run(passes=3) is None and sub.exists() and world.link.jobs == []
    assert SID not in world.lane.owned() and path in world.lane.waiting()[0]["wait"]
