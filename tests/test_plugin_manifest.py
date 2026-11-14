"""Plugin manifests name which paths a plugin owns, and which changes can be checked as that plugin alone.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.core import plugin_manifest as pm

CHECKS = """name = "checks"
code = ["thomas/server/precard/**", "thomas/server/proof/**"]
tests = ["tests/test_*precard*.py"]
needs = ["thomas/core/green_place.py"]
"""


def _root(tmp_path: Path, **manifests: str) -> Path:
    (tmp_path / "plugins").mkdir()
    for name, text in manifests.items():
        (tmp_path / "plugins" / f"{name}.toml").write_text(text, encoding="utf-8")
    return tmp_path


def test_globs_match_whole_segments() -> None:
    assert pm.matches("thomas/server/precard/**", "thomas/server/precard/check.py")
    assert pm.matches("thomas/server/precard/**", "thomas/server/precard/sub/x.py")
    assert not pm.matches("thomas/server/precard/**", "thomas/server/precard_extra.py")
    assert pm.matches("tests/test_*precard*.py", "tests/test_a_precard_runs.py")
    assert not pm.matches("tests/test_*precard*.py", "tests/sub/test_precard.py")


def test_a_manifest_loads_with_its_lists_as_tuples(tmp_path: Path) -> None:
    (checks,) = pm.load(_root(tmp_path, checks=CHECKS))
    assert checks.name == "checks"
    assert checks.code == ("thomas/server/precard/**", "thomas/server/proof/**")
    assert checks.needs == ("thomas/core/green_place.py",)
    assert checks.provides == () and checks.door == () and checks.source == "plugins/checks.toml"


def test_claims_answers_for_exact_paths_and_globs_alike() -> None:
    claimed = pm.claims(("thomas/server/app.py", "thomas/server/precard/**", "tests/test_*precard*.py"))
    assert claimed("thomas/server/app.py") and claimed("thomas/server/precard/sub/x.py")
    assert claimed("tests/test_a_precard_runs.py")
    assert not claimed("thomas/server/app_core.py") and not claimed("thomas/server/precard_extra.py")
    assert not pm.claims(())("thomas/server/app.py")


def test_a_manifest_answers_what_it_claims(tmp_path: Path) -> None:
    (checks,) = pm.load(_root(tmp_path, checks=CHECKS))
    assert checks.in_code("thomas/server/proof/runner.py") and not checks.in_code("tests/test_a_precard_runs.py")
    assert checks.in_tests("tests/test_a_precard_runs.py") and not checks.in_tests("thomas/server/proof/runner.py")
    assert checks.in_needs("thomas/core/green_place.py") and not checks.in_door("thomas/server/proof/runner.py")


def test_a_manifest_names_the_door_outside_code_comes_in_by(tmp_path: Path) -> None:
    door = 'door = ["thomas/server/precard/__init__.py"]\n'
    (checks,) = pm.load(_root(tmp_path, checks=CHECKS + door))
    assert checks.door == ("thomas/server/precard/__init__.py",)


def test_no_plugins_folder_is_no_plugins(tmp_path: Path) -> None:
    assert pm.load(tmp_path) == ()


@pytest.mark.parametrize(
    "text, why",
    [
        ('name = "other"\ncode = ["a/**"]\ntests = []\n', "file name"),
        ('name = "checks"\ncode = []\ntests = []\n', "code"),
        ('name = "checks"\ncode = ["a/**"]\ntests = "tests/x.py"\n', "tests"),
    ],
)
def test_a_bad_manifest_is_refused(tmp_path: Path, text: str, why: str) -> None:
    with pytest.raises(pm.ManifestError, match=why):
        pm.load(_root(tmp_path, checks=text))


def test_two_plugins_claiming_one_path_is_an_error(tmp_path: Path) -> None:
    other = 'name = "other"\ncode = ["thomas/server/precard/check.py"]\ntests = []\n'
    manifests = pm.load(_root(tmp_path, checks=CHECKS, other=other))
    with pytest.raises(pm.ManifestError, match="claimed by checks and other"):
        pm.owner(manifests, "thomas/server/precard/check.py")


def test_a_change_inside_one_plugin_is_scoped_to_it(tmp_path: Path) -> None:
    manifests = pm.load(_root(tmp_path, checks=CHECKS))
    got = pm.scope(manifests, ["thomas/server/precard/check.py", "tests/test_a_precard_runs.py"])
    assert got is not None and got.name == "checks"


@pytest.mark.parametrize(
    "changed",
    [
        [],
        ["thomas/server/precard/check.py", "thomas/server/app.py"],  # one path outside every plugin
        ["thomas/server/precard/check.py", "thomas/core/kernel/plugins.py"],  # the kernel
        ["thomas/server/precard/check.py", "plugins/checks.toml"],  # a manifest
        ["thomas/server/precard/check.py", "tests/conftest.py"],  # the harness
        ["thomas/server/precard/check.py", "pyproject.toml"],
        ["thomas/core/green_place.py"],  # a need is not the plugin's own code
    ],
)
def test_anything_else_is_not_scoped(tmp_path: Path, changed: list[str]) -> None:
    assert pm.scope(pm.load(_root(tmp_path, checks=CHECKS)), changed) is None


def test_a_change_to_the_door_is_not_scoped_because_outside_code_can_feel_it(tmp_path: Path) -> None:
    door = 'door = ["thomas/server/precard/__init__.py"]\n'
    manifests = pm.load(_root(tmp_path, checks=CHECKS + door))
    assert pm.scope(manifests, ["thomas/server/precard/__init__.py"]) is None
    assert pm.scope(manifests, ["thomas/server/precard/check.py"]) is not None  # behind the door


def test_a_changelog_fragment_never_stops_a_scope_and_never_makes_one(tmp_path: Path) -> None:
    manifests = pm.load(_root(tmp_path, checks=CHECKS))
    fragment = "changelog.d/a-change.md"
    got = pm.scope(manifests, ["thomas/server/precard/check.py", fragment])
    assert got is not None and got.name == "checks"
    assert pm.scope(manifests, [fragment]) is None  # no plugin's code changed: nothing to check it as
    assert pm.scope(manifests, ["thomas/server/app.py", fragment]) is None
