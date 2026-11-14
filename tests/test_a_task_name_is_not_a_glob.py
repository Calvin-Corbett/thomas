"""A WIP task's own directory name must not read as a glob pattern.

`bootstrap_claim` mints task ids shaped `[WIP][HSK-20260909-030707] branch dev`,
so a claim on that task's plan directory is a path containing two bracket groups.
`_is_glob` counted `[` as a glob metacharacter, so the path was compiled as a
pattern whose character classes matched other agents' task directories -- and any
two WIP task scopes collided. Measured 2026-09-09: an agent could not claim its
own task's plan directory while another agent held theirs, which blocked the
commit that plan file was required for.

Bracket character classes are not used in this repo's scope patterns; `*` and `?`
are. So a bracket alone no longer makes a path a pattern, and a bracketed path
that a genuine wildcard pattern covers is still matched.
"""

from __future__ import annotations

from scripts.forge.gates.workboard_claims import _is_glob, _scope_overlaps

MINE = "plans/thomas/tasks/[WIP][HSK-20260909-030707] branch dev"
THEIRS = "plans/thomas/tasks/[WIP][HSK-20260909-002209] PRAXIS-PHASE3-KERNEL"


def test_two_different_wip_task_directories_do_not_collide():
    assert _scope_overlaps(MINE, THEIRS) is False
    assert _scope_overlaps(THEIRS, MINE) is False


def test_the_same_wip_task_directory_still_collides_with_itself():
    assert _scope_overlaps(MINE, MINE) is True


def test_a_wip_task_directory_still_collides_with_a_parent_scope():
    """Containment must keep working, or a real conflict would be missed."""
    assert _scope_overlaps(MINE, "plans/thomas/tasks") is True
    assert _scope_overlaps("plans/thomas/tasks", MINE) is True
    assert _scope_overlaps(f"{MINE}/PLAN.md", MINE) is True


def test_a_bracketed_name_is_not_treated_as_a_pattern():
    assert _is_glob(MINE) is False
    assert _is_glob("thomas/work/lanes") is False


def test_real_wildcards_are_still_patterns():
    assert _is_glob("thomas/**") is True
    assert _is_glob("thomas/*.py") is True
    assert _is_glob("thomas/file?.py") is True


def test_a_wildcard_pattern_still_covers_a_bracketed_path():
    """The bug fix must not stop a genuine glob from reaching these paths."""
    assert _scope_overlaps("plans/thomas/tasks/**", MINE) is True
    assert _scope_overlaps(MINE, "plans/**") is True


def test_ordinary_scopes_are_unaffected():
    assert _scope_overlaps("thomas/work/lanes", "thomas/work/lanes/store.py") is True
    assert _scope_overlaps("thomas/work/lanes", "thomas/server/routes/work.py") is False
    assert _scope_overlaps("thomas/**", "thomas/work/lanes") is True
