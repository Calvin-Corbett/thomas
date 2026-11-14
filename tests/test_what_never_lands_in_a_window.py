"""What never lands inside a window, whatever else is true of its change (spec sections 3 and 8.2 condition 4).

The closure tests build their own git repo in a tmp folder; one reads this checkout's own committed promoter. Nothing
is imported from a change: the closure is read from git's tree with ``ast``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.cage import window_rules as wr

from tests.green_support import git
from thomas.tools import trusted_card

REPO = Path(__file__).resolve().parents[1]
CATALOGUE = trusted_card.load_catalogue()
ENFORCED = CATALOGUE.load_enforcement_paths(REPO)


def _why(path: str, status: str = "M", diff: str = "", closure: frozenset[str] = frozenset()) -> str:
    return wr.why_never(path, status, added_diff=diff, enforced=ENFORCED, closure=closure, catalogue=CATALOGUE)


@pytest.mark.parametrize(
    ("path", "status", "words"),
    [
        ("thomas/tools/gone.py", "D", "deletes"),
        ("run-ui.ps1", "M", "runs as you"),
        ("tests/conftest.py", "M", "runs as you"),
        ("tests/data/pytest.ini", "A", "runs as you"),
        ("scripts/cage/new_rule.py", "A", "the cage and approvals"),
        ("scripts/crew/brief/commit.py", "M", "gates and enforcement"),
        ("thomas/_architecture.py", "M", "gates and enforcement"),
        ("thomas/core/kernel/host.py", "M", "approval or of the checks"),
        ("thomas/tools/owner_desk.py", "M", "approval or of the checks"),
        ("thomas/server/dial_elevation.py", "M", "the cage and approvals"),
        ("thomas/foo/__init__.py", "A", "runs a file of that name"),
        ("thomas/server/window_records.py", "A", "pipeline or the window"),
        ("thomas/server/self_change_cards.py", "M", "pipeline or the window"),
        ("README.md", "M", "runs as you"),
        ("thomas/server/GUARDRAILS.md", "M", "gates and enforcement"),
        ("docs/x/AGENTS.md", "M", "configuration or release metadata"),
        ("skills/x/SKILL.md", "A", "pipeline or the window"),
        (".claude/settings.json", "M", "pipeline or the window"),
    ],
)
def test_these_files_never_land_in_a_window(path: str, status: str, words: str) -> None:
    why = _why(path, status)
    assert why, f"{path} must wait for a card"
    assert words in why, why


# 2026-10-25: "all changes should be through express lane"; you chose to keep cards only for the window's own guard.
# These waited for a card until then: the checks the speed teams edit, scripts outside the cage and the commit tools,
# test helpers, notes, plans and the pipeline's routes.
@pytest.mark.parametrize(
    "path",
    [
        "thomas/server/precard/check.py",
        "thomas/server/proof/runner.py",
        "thomas/server/ratchet/attempt.py",
        "thomas/server/thomas_project_start.py",
        "thomas/server/self_change_status.py",
        "thomas/server/capacity_ledger.py",
        "thomas/server/routes/self_project_routes.py",
        "thomas/server/routes/evolve_agent_autopilot.py",
        "scripts/praxis/window_audit.py",
        "scripts/fast_tests_plugin.py",
        "tests/helpers_for_x.py",
        "docs/superpowers/plans/next.md",
        "plans/thomas/WORKBOARD.md",
        "thomas/README.md",
    ],
)
def test_everything_but_the_guard_may_land_in_a_window(path: str) -> None:
    assert _why(path, "M") == ""


def test_a_new_way_to_the_network_is_read_by_the_second_look_not_held_by_path() -> None:
    diff = "diff --git a/thomas/tools/x.py b/thomas/tools/x.py\n@@ -1 +1,2 @@\n+import requests\n"
    assert _why("thomas/tools/x.py", "M", diff) == ""


@pytest.mark.parametrize(
    "path",
    ["thomas/tools/some_tool.py", "tests/test_some_tool.py", "changelog.d/a-fix.md", "thomas/server/web/js/app.js"],
)
def test_ordinary_code_tests_notes_and_pages_may_land_in_a_window(path: str) -> None:
    assert _why(path, "M") == ""


def test_a_file_a_process_of_yours_loads_never_lands_in_a_window() -> None:
    assert "loads it" in _why("thomas/tools/base.py", "M", closure=frozenset({"thomas/tools/base.py"}))


def _commit_files(repo: Path, files: dict[str, str]) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "files")
    return git(repo, "rev-parse", "HEAD")


def test_the_closure_follows_every_import_lazy_relative_and_by_name(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    rev = _commit_files(
        repo,
        {
            "scripts/cage/promoter_service.py": (
                "from thomas.tools import helper\n"
                "def later():\n    import thomas.core.late\n"
                "import importlib\nimportlib.import_module('thomas.core.dyn')\n"
            ),
            "thomas/tools/helper.py": "from . import sibling\n",
            "thomas/tools/sibling.py": "VALUE = 1\n",
            "thomas/tools/other.py": "VALUE = 2\n",
            "thomas/core/late.py": "VALUE = 3\n",
        },
    )

    found = wr.static_closure(repo, rev, ["scripts/cage/promoter_service.py"])

    for path in ("thomas/tools/helper.py", "thomas/tools/sibling.py", "thomas/core/late.py", "thomas/core/dyn.py"):
        assert path in found, path
    assert "thomas/__init__.py" in found and "thomas/tools/__init__.py" in found, "packages run their __init__"
    assert "thomas/tools/other.py" not in found


def test_the_loaded_closure_is_every_file_under_the_checkout_this_process_loaded(tmp_path: Path) -> None:
    inside = tmp_path / "thomas" / "tools" / "base.py"
    modules = {
        "a": SimpleNamespace(__file__=str(inside)),
        "b": SimpleNamespace(__file__=str(tmp_path.parent / "elsewhere.py")),
        "c": SimpleNamespace(),
    }
    assert wr.loaded_closure(tmp_path, modules) == frozenset({"thomas/tools/base.py"})


def test_the_promoters_own_closure_holds_the_files_it_was_missing() -> None:
    """The four map readers found these loaded by the promoter and on no list (2026-10-14)."""
    found = wr.static_closure(REPO, "HEAD", ["scripts/cage/promoter_service.py", "scripts/cage/cage_keepalive.py"])
    for path in (
        "thomas/tools/__init__.py",
        "thomas/tools/base.py",
        "thomas/core/config.py",
        "thomas/tools/web_search.py",
        "thomas/preferences/store.py",
        "scripts/breakglass_window_core.py",
    ):
        assert path in found, path


def test_rules_name_every_file_of_a_change_that_must_wait_and_why(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    parent = _commit_files(
        repo, {"scripts/cage/promoter_service.py": "from thomas.tools import base\n", "thomas/tools/base.py": "A = 1\n"}
    )
    tree_commit = _commit_files(repo, {"thomas/tools/base.py": "A = 2\n", "thomas/tools/fine.py": "B = 1\n"})
    tree = git(repo, "rev-parse", f"{tree_commit}^{{tree}}")
    changes = [("M", "thomas/tools/base.py"), ("A", "thomas/tools/fine.py")]

    found = wr.Rules(repo, modules={}).excluded(parent, tree, changes, catalogue=CATALOGUE, enforced=())

    assert found == [("thomas/tools/base.py", "a process that runs as you loads it")]


# Ported from tests/test_express_eligibility.py, which Task 51 removed with Express (2026-10-14 review, C3). These are
# the charter rules the window reaches through ``charter.path_problem``; with that file gone, nothing else tested them.
NEVER_ELIGIBLE = {
    "scripts/cage/self_change_promoter.py": "referee_or_cage",
    "scripts/cage/referee/charter.py": "referee_or_cage",
    "scripts/forge/gates/new_gate.py": "referee_or_cage",
    "thomas/tools/owner_desk.py": "approval_or_checks",
    "thomas/server/precard/check.py": "approval_or_checks",
    "thomas/server/green_handoff.py": "approval_or_checks",
    "thomas/core/kernel/loader.py": "approval_or_checks",
    "thomas/server/web/js/express_switch.js": "approval_or_checks",
    "AGENTS.md": "config_or_release",
    "pyproject.toml": "config_or_release",
    "agent_safety.toml": "config_or_release",
    "runtime/data.json": "runtime_or_binary",
    "thomas/core/__pycache__/leaf.cpython-312.pyc": "runtime_or_binary",
    "sub/.git/config": "referee_or_cage",
    "changelog.d/.gitattributes": "referee_or_cage",
    "thomas/core/GIT~1/x": "referee_or_cage",
    "thomas/core/leaf.py ": "path_spelling",
    "thomas/core/leaf.py.": "path_spelling",
    "thomas/core/leaf.py:stream": "path_spelling",
    "thomas/core/../leaf.py": "path_spelling",
    "thomas\\core\\leaf.py": "path_spelling",
    "thomas/core/café.py": "path_spelling",
    "": "path_spelling",
}


@pytest.mark.parametrize(("path", "code"), sorted(NEVER_ELIGIBLE.items()))
def test_the_charter_names_every_path_it_refuses_and_the_window_refuses_each(path: str, code: str) -> None:
    from scripts.cage.referee import charter

    assert charter.path_problem(path) == code
    if path in _CHECKS_THE_WINDOW_LANDS:  # the checks, not their guard: these land in a window since 2026-10-25
        assert _why(path, "A") == ""
    else:
        assert _why(path, "A"), f"{path!r} must wait for a card"


_CHECKS_THE_WINDOW_LANDS = {"thomas/server/precard/check.py", "thomas/server/green_handoff.py"}


# Files only the charter refuses: file_class ranks each as code and no danger class names it, so a charter "tidied"
# by a later card would let each land with no card. Python 3.12 loads a .pyd before the .py beside it, a .pyc with no
# source imports, and an unchecked-hash __pycache__ file is used instead of its source; all run as you under pytest.
_ONLY_THE_CHARTER_REFUSES = {
    "thomas/core/leaf.pyd": "runtime state or a binary",
    "thomas/core/leaf.pyc": "runtime state or a binary",
    "thomas/core/leaf.pyo": "runtime state or a binary",
    "thomas/core/leaf.dll": "runtime state or a binary",
    "thomas/core/leaf.so": "runtime state or a binary",
    "thomas/core/__pycache__/leaf.cpython-312.pyc": "runtime state or a binary",
    "thomas/core/evil.pth": "runtime state or a binary",
    "changelog.d/a-note.pth": "runtime state or a binary",
    "thomas/core/sitecustomize.py": "runs a file of that name",
    "thomas/core/usercustomize.py": "runs a file of that name",
    "thomas/core/__main__.py": "runs a file of that name",
    "thomas/core/setup.py": "runs a file of that name",
    "thomas/core/noxfile.py": "runs a file of that name",
    "thomas/core/newpkg/__init__.py": "runs a file of that name",
    "changelog.d/sitecustomize.py": "runs a file of that name",
    "thomas/core/.gitignore": "the cage, the commit tools or the gates",
    "thomas/core/.gitkeep": "the cage, the commit tools or the gates",
}


@pytest.mark.parametrize(("path", "words"), sorted(_ONLY_THE_CHARTER_REFUSES.items()))
def test_compiled_binary_and_auto_run_files_never_land_in_a_window(path: str, words: str) -> None:
    assert words in _why(path, "A")


def test_the_rules_refuse_every_compiled_binary_and_auto_run_file_of_a_real_change(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    parent = _commit_files(repo, {"scripts/cage/promoter_service.py": "VALUE = 1\n"})
    tree_commit = _commit_files(
        repo, {**{path: "x = 1\n" for path in _ONLY_THE_CHARTER_REFUSES}, "thomas/ok.py": "A = 1\n"}
    )
    tree = git(repo, "rev-parse", f"{tree_commit}^{{tree}}")
    changes = [("A", path) for path in [*_ONLY_THE_CHARTER_REFUSES, "thomas/ok.py"]]

    found = dict(wr.Rules(repo, modules={}).excluded(parent, tree, changes, catalogue=CATALOGUE, enforced=()))

    assert set(found) == set(_ONLY_THE_CHARTER_REFUSES), "every one waits for a card, and the plain module does not"
