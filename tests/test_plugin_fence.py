"""The fence: a carved plugin imports only the kernel, its own code and its declared needs.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 2.
"""

from __future__ import annotations

import pytest

from thomas.core import plugin_fence as pf
from thomas.core.plugin_manifest import PluginManifest

TRACKED = {
    "thomas/__init__.py",
    "thomas/core/__init__.py",
    "thomas/core/kernel/__init__.py",
    "thomas/core/kernel/plugins.py",
    "thomas/core/green_place.py",
    "thomas/server/__init__.py",
    "thomas/server/app.py",
    "thomas/server/capacity_ledger.py",
    "thomas/server/precard/__init__.py",
    "thomas/server/precard/check.py",
    "thomas/server/precard/slot.py",
}
CHECKS = PluginManifest(
    name="checks", code=("thomas/server/precard/**",), tests=(), needs=("thomas/core/green_place.py",)
)


def test_imports_finds_every_depth_and_resolves_relative_ones() -> None:
    source = (
        "import os\nfrom thomas.core import green_place\nfrom . import slot\n"
        "def f():\n    import thomas.server.app\n    from ..capacity_ledger import admitted\n"
    )
    got = pf.imports("thomas/server/precard/check.py", source)
    assert [m for _, m in got] == [
        "thomas.core.green_place",
        "thomas.server.precard.slot",
        "thomas.server.app",
        "thomas.server.capacity_ledger.admitted",
    ]


def test_module_path_finds_modules_and_packages() -> None:
    assert pf.module_path("thomas.server.app", TRACKED) == "thomas/server/app.py"
    assert pf.module_path("thomas.server", TRACKED) == "thomas/server/__init__.py"
    assert pf.module_path("thomas.server.capacity_ledger.admitted", TRACKED) == "thomas/server/capacity_ledger.py"
    assert pf.module_path("thomas.nope", TRACKED) == "thomas/__init__.py"  # a name the package itself defines
    assert pf.module_path("thomas.nope", set()) is None


def test_the_kernel_its_own_code_and_its_needs_are_inside_the_fence() -> None:
    source = (
        "from thomas.core.kernel import plugins\nfrom thomas.core import green_place\n"
        "from thomas.server.precard import slot\n"
    )
    assert pf.violations(CHECKS, {"thomas/server/precard/check.py": source}, TRACKED) == []


def test_anything_else_is_a_violation_with_its_line() -> None:
    source = "import os\n\n\ndef f():\n    from thomas.server.capacity_ledger import admitted\n"
    assert pf.violations(CHECKS, {"thomas/server/precard/check.py": source}, TRACKED) == [
        "thomas/server/precard/check.py:5 imports thomas.server.capacity_ledger.admitted"
    ]


def test_a_plugin_outside_thomas_is_fenced_by_its_own_imports_too() -> None:
    tracked = {"scripts/__init__.py", "scripts/cage/run.py", "scripts/forge/gate.py", "thomas/__init__.py"}
    cage = PluginManifest(name="cage", code=("scripts/cage/**",), tests=())
    source = "from scripts.forge import gate\n"
    assert pf.violations(cage, {"scripts/cage/run.py": source}, tracked) == [
        "scripts/cage/run.py:1 imports scripts.forge.gate"
    ]


def test_reaches_says_what_outside_code_lands_on_inside_a_plugin() -> None:
    source = "from thomas.server.precard import check\nfrom thomas.server import precard\n\nprecard.slot.x()\n"
    got = pf.reaches(CHECKS, {"thomas/server/app.py": source}, TRACKED)
    assert {(path, target) for path, _line, _module, target in got} == {
        ("thomas/server/app.py", "thomas/server/precard/check.py"),
        ("thomas/server/app.py", "thomas/server/precard/__init__.py"),
        ("thomas/server/app.py", "thomas/server/precard/slot.py"),
    }


def test_files_outside_the_plugins_code_are_not_fenced() -> None:
    assert pf.violations(CHECKS, {"thomas/server/app.py": "import thomas.server.capacity_ledger\n"}, TRACKED) == []


# The other direction: what outside code may touch. A plugin's own tests can only be trusted alone when nothing outside
# depends on what sits behind its door.
DOORED = PluginManifest(
    name="checks",
    code=("thomas/server/precard/**",),
    tests=("tests/test_*precard*.py",),
    door=("thomas/server/precard/__init__.py", "thomas/server/precard/clocks.py"),
)
WITH_CLOCKS = TRACKED | {"thomas/server/precard/clocks.py"}


def _outsiders(source: str, path: str = "thomas/server/app.py") -> list[str]:
    return pf.outsiders(DOORED, {path: source}, WITH_CLOCKS)


def test_outside_code_may_use_the_door() -> None:
    assert _outsiders("from thomas.server.precard import PASSED, clocks\nfrom thomas.server import precard\n") == []
    assert (
        _outsiders("from thomas.server import precard\n\nprecard.check_for_hand_in('x')\nprecard.clocks.note()\n") == []
    )


def test_an_import_behind_the_door_is_named_with_its_line() -> None:
    assert _outsiders("import os\n\n\ndef f():\n    from thomas.server.precard import check\n") == [
        "thomas/server/app.py:5 reaches thomas.server.precard.check"
    ]
    assert _outsiders("from thomas.server.precard.slot import too_little_room\n") == [
        "thomas/server/app.py:1 reaches thomas.server.precard.slot.too_little_room"
    ]


@pytest.mark.parametrize(
    "source",
    [
        "from thomas.server import precard\n\nprecard.slot.too_little_room()\n",
        "from thomas.server import precard as p\n\np.slot.too_little_room()\n",
        "import thomas.server.precard as p\n\np.slot.too_little_room()\n",
    ],
)
def test_a_module_reached_through_the_package_counts_though_no_import_names_it(source: str) -> None:
    assert _outsiders(source) == ["thomas/server/app.py:3 reaches thomas.server.precard.slot"]


def test_the_plugins_own_files_and_tests_elsewhere_are_not_outsiders() -> None:
    behind = "from thomas.server.precard import check\n"
    assert _outsiders(behind, "thomas/server/precard/slot.py") == []
    assert _outsiders(behind, "tests/test_a_precard_runs.py") == []
    assert _outsiders(behind, "tests/test_an_integration_test.py") == []  # they stay in the full check


def test_a_plugin_with_no_door_has_nothing_to_hold() -> None:
    source = "from thomas.server.precard import check\n"
    assert pf.outsiders(CHECKS, {"thomas/server/app.py": source}, TRACKED) == []
