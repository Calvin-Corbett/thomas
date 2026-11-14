"""A plugin's proof set: what a slim copy must hold to check a change inside it.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 3.
"""

from __future__ import annotations

from thomas.core import plugin_proof
from thomas.core.plugin_manifest import PluginManifest

FILES = {
    "thomas/__init__.py": "",
    "thomas/core/__init__.py": "",
    "thomas/core/kernel/__init__.py": "",
    "thomas/core/green_place.py": "from thomas.core import tiny\n",
    "thomas/core/tiny.py": "",
    "thomas/server/__init__.py": "",
    "thomas/server/app.py": "import thomas.server.huge\n",
    "thomas/server/huge.py": "",
    "thomas/server/precard/__init__.py": "",
    "thomas/server/precard/check.py": "from thomas.core import green_place\n",
    "thomas/server/precard/check.css": "",
    "tests/__init__.py": "",
    "tests/conftest.py": "",
    "tests/test_a_precard_runs.py": "from thomas.server.precard import check\n",
    "plugins/checks.toml": "",
}
CHECKS = PluginManifest(
    name="checks",
    code=("thomas/server/precard/**",),
    tests=("tests/test_*precard*.py",),
    needs=("thomas/core/green_place.py",),
    source="plugins/checks.toml",
)


def test_the_proof_set_holds_the_plugin_its_needs_their_imports_and_the_harness() -> None:
    got = plugin_proof.proof_set(CHECKS, FILES, FILES.__getitem__)
    assert "thomas/server/precard/check.css" in got  # code claims non-Python files too
    assert "thomas/core/tiny.py" in got  # imported by a need
    assert {"tests/conftest.py", "plugins/checks.toml", "thomas/server/__init__.py"} <= set(got)
    assert "thomas/server/app.py" not in got and "thomas/server/huge.py" not in got
    assert got == sorted(got)


def test_a_proof_copy_holds_the_architecture_test_the_selection_names_every_time() -> None:
    files = {**FILES, "tests/test_architecture.py": ""}
    assert "tests/test_architecture.py" in plugin_proof.proof_set(CHECKS, files, files.__getitem__)


def test_a_quoted_dotted_name_counts_as_an_import() -> None:
    files = {**FILES, "tests/conftest.py": 'importlib.import_module("thomas.server.huge")\n'}
    assert "thomas/server/huge.py" in plugin_proof.proof_set(CHECKS, files, files.__getitem__)


def test_asking_sys_modules_about_a_module_is_not_an_import() -> None:
    files = {**FILES, "tests/conftest.py": 'import sys\nif sys.modules.get("thomas.server.huge"):\n    pass\n'}
    assert "thomas/server/huge.py" not in plugin_proof.proof_set(CHECKS, files, files.__getitem__)


def test_a_dotted_name_in_a_file_that_never_imports_by_name_is_only_text() -> None:
    # scripts/cage/checker_run.py: BOOT_IMPORTS boots a different tree in a child process, not this copy.
    boot = 'BOOT = ("thomas.server.huge",)\nrun([python, "-c", "import " + ", ".join(BOOT)])\n'
    files = {**FILES, "tests/conftest.py": boot}
    assert "thomas/server/huge.py" not in plugin_proof.proof_set(CHECKS, files, files.__getitem__)


def test_a_module_launched_with_dash_m_counts_without_an_importer() -> None:
    files = {**FILES, "tests/conftest.py": 'subprocess.run([sys.executable, "-m", "thomas.server.huge"])\n'}
    assert "thomas/server/huge.py" in plugin_proof.proof_set(CHECKS, files, files.__getitem__)


def test_imports_of_any_repo_package_are_followed_not_just_thomas() -> None:
    files = {
        **FILES,
        "tests/test_a_precard_runs.py": "from scripts.cage import checker\nfrom tests.helpers import make\n",
        "scripts/__init__.py": "",
        "scripts/cage/checker.py": "",  # scripts/cage has no __init__: a namespace package
        "tests/helpers.py": "",
    }
    got = plugin_proof.proof_set(CHECKS, files, files.__getitem__)
    assert {"scripts/cage/checker.py", "scripts/__init__.py", "tests/helpers.py"} <= set(got)


def test_a_quoted_dotted_name_of_any_repo_package_counts() -> None:
    files = {**FILES, "tests/conftest.py": 'patch("scripts.tool.run")\n', "scripts/tool.py": ""}
    assert "scripts/tool.py" in plugin_proof.proof_set(CHECKS, files, files.__getitem__)


def test_a_plugin_whose_tests_lean_only_on_helpers_has_no_strays() -> None:
    files = {**FILES, "tests/test_a_precard_runs.py": "from tests.helpers import make\n", "tests/helpers.py": ""}
    assert plugin_proof.strays(CHECKS, files, files.__getitem__) == {}


def test_thomas_that_only_a_test_pulls_in_is_a_stray_named_with_its_test() -> None:
    files = {
        **FILES,
        "tests/test_a_precard_runs.py": "from tests.world import x\n",
        "tests/world.py": "import thomas.server.app\n",
    }
    assert plugin_proof.strays(CHECKS, files, files.__getitem__) == {
        "thomas/server/app.py": "tests/test_a_precard_runs.py",
        "thomas/server/huge.py": "tests/test_a_precard_runs.py",
    }


def test_a_file_that_does_not_parse_is_kept_without_its_imports() -> None:
    files = {**FILES, "thomas/server/precard/broken.py": "def (:\n"}
    assert "thomas/server/precard/broken.py" in plugin_proof.proof_set(CHECKS, files, files.__getitem__)
