"""Self-test of the Express threat lab: every path and inbox fixture really creates the trick it claims.

A later test that says "the referee refused the junction" proves nothing unless the junction existed. Each test
here builds a fixture for real inside a scratch folder and checks the trick with facts the file system reports, not
with the fixture's own say-so. Windows-only tricks skip elsewhere, and a trick this machine cannot build (8.3 names
off, no symlink privilege) skips with that reason (``EXPRESS_LAB_STRICT=1`` turns those skips into failures). A
fixture that is broken fails. The patch fixtures are checked in ``test_express_lab_patch_fixtures.py``.

Plan row 6 ("every path-identity trick ends refused with the tree unchanged") is a test of the real referee and
writer (packages B1 and B2) running against these fixtures. Here it is only the check that the lab can supply
every trick the row names, each built for real.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

import pytest

from tests.express_pytest import lab, make  # noqa: F401  (lab is a fixture)
from tests.express_support import (
    FIXTURES,
    PATH_IDENTITY_FIXTURES,
    EnvironmentUnavailable,
    ExpressLab,
    build_fixture,
    is_reparse_point,
)
from tests.express_winfs import alternate_streams, create_symlink, link_count, short_path

PLAN_ROW_6 = {  # section 6, row 6, written out here so the support module cannot quietly shorten its own list
    "junction_after_check",
    "short_name_alias",
    "case_variant",
    "alternate_stream",
    "trailing_dot",
    "dot_git_variant",
    "symlink_to_outside",
    "gitlink",
    "mode_change",
    "rename",
    "binary_blob",
    "pyc_file",
    "nul_byte_path",
    "non_canonical_spelling",
}
WINDOWS_ONLY = {n for n, (_kind, windows, _build) in FIXTURES.items() if windows}


def test_every_fixture_the_plan_names_is_registered() -> None:
    assert PLAN_ROW_6 == set(PATH_IDENTITY_FIXTURES) <= set(FIXTURES)  # trailing space is built too, beyond the list
    assert {"trailing_space", "forged_submission", "oversized_patch", "poison_terms", "poison_unary"} <= set(FIXTURES)
    assert {"inbox_junction_entry", "inbox_hard_linked_entry", "inbox_sparse_giant_entry"} <= set(FIXTURES)
    assert {"inbox_alternate_stream_entry", "control_plain_fragment"} <= set(FIXTURES)


def test_an_unknown_fixture_name_is_an_error_not_a_skip(lab: ExpressLab) -> None:
    with pytest.raises(KeyError, match="no lab fixture"):
        build_fixture("junction_after_chek", lab)


@pytest.mark.skipif(os.name == "nt", reason="this checks the refusal off Windows")
@pytest.mark.parametrize("name", sorted(WINDOWS_ONLY))
def test_a_windows_only_fixture_says_why_it_cannot_be_built_elsewhere(name: str, lab: ExpressLab) -> None:
    with pytest.raises(EnvironmentUnavailable, match="Windows"):
        build_fixture(name, lab)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_a_fixture_builds_and_describes_its_own_trick(name: str, lab: ExpressLab) -> None:
    case = make(name, lab)
    assert case.name == name and case.kind == FIXTURES[name][0] and case.trick
    assert case.windows_only == (name in WINDOWS_ONLY)
    assert case.claimed or case.patches or case.inbox_entry is not None
    if case.kind == "path":
        assert len(case.patches) == len(case.claimed)  # one hand-in patch per claimed spelling
        assert case.protected  # a path case always says which folder to compare before and after


def test_junction_replaces_the_landing_folder_only_after_the_check(lab: ExpressLab) -> None:
    case = make("junction_after_check", lab)
    folder, target = case.facts["parent"], case.facts["target"]
    assert folder.is_dir() and not is_reparse_point(folder) and not case.facts["reparse_before_arm"]
    assert case.claimed[0] == "changelog.d/lab-landing-swap.md"  # a legal flat name: no spelling rule catches it
    case.arm()
    assert is_reparse_point(folder) and case.facts["moved"].is_dir()  # the real folder was moved aside
    (folder / "probe.txt").write_bytes(b"probe")
    assert (target / "probe.txt").read_bytes() == b"probe"  # a write through it lands in the target


def test_a_swap_the_file_system_refuses_is_recorded_not_raised(
    lab: ExpressLab, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = make("junction_after_check", lab)

    def held_open(src, dst):
        raise PermissionError(32, "in use")

    monkeypatch.setattr(os, "rename", held_open)
    case.arm()
    assert "PermissionError" in case.facts["blocked"] and not is_reparse_point(case.facts["parent"])


def test_short_name_alias_names_the_same_file_under_another_spelling(lab: ExpressLab) -> None:
    case = make("short_name_alias", lab)
    real = case.facts["real"]
    claimed_name = case.claimed[0].split("/")[-1]  # what a hand-in would actually name
    assert claimed_name == case.facts["alias"] == Path(short_path(real)).name and "~" in claimed_name
    assert claimed_name.lower() != real.name.lower() and claimed_name not in os.listdir(real.parent)
    assert (real.parent / claimed_name).read_bytes() == case.facts["original"] and case.facts["same_file"]
    assert lab.base_sha == lab.repo.head() == case.facts["base"]  # this fixture moved dev, and says so


@pytest.mark.parametrize("name", ["case_variant", "trailing_dot", "trailing_space"])
def test_spelling_variant_folds_onto_an_existing_file(name: str, lab: ExpressLab) -> None:
    case = make(name, lab)
    real = case.facts["real"]
    spelling = case.claimed[0]
    assert spelling.split("/")[-1] not in os.listdir(real.parent)  # it is not the name on disk
    assert open(str(lab.repo.root) + os.sep + spelling.replace("/", os.sep), "rb").read() == case.facts["original"]


def test_alternate_stream_hides_bytes_on_the_existing_file(lab: ExpressLab) -> None:
    case = make("alternate_stream", lab)
    real = case.facts["real"]
    listing = sorted(os.listdir(real.parent))
    assert case.facts["streams_before"] == []
    with open(str(lab.repo.root) + os.sep + case.claimed[0].replace("/", os.sep), "wb") as stream:
        stream.write(b"hidden")
    assert alternate_streams(real) == [":hidden:$DATA"]
    assert real.read_bytes() == case.facts["original"] and sorted(os.listdir(real.parent)) == listing


def test_dot_git_spellings_fold_onto_the_real_git_folder(lab: ExpressLab) -> None:
    case = make("dot_git_variant", lab)
    hooks = case.facts["hooks"]
    assert len(case.facts["spellings"]) >= 1
    for spelling in case.facts["spellings"]:
        assert not spelling.startswith(".git/") and os.path.samefile(lab.repo.root / Path(spelling).parent, hooks)


def test_symlink_points_outside_the_tree(lab: ExpressLab) -> None:
    case = make("symlink_to_outside", lab)  # skips without the privilege; the next test runs it without
    link = case.facts["link"]
    assert link.is_symlink() and os.path.samefile(link, case.facts["victim"])
    assert not str(link.resolve()).startswith(str(lab.repo.root))


def test_symlink_fixture_runs_with_an_injected_creator_and_skips_for_privilege(lab: ExpressLab) -> None:
    calls = []

    def stand_in(target, link, target_is_directory=False):  # a hard link is what this account can make
        calls.append((Path(target).name, Path(link).name, target_is_directory))
        os.link(target, link)

    lab.symlink = functools.partial(create_symlink, symlink=stand_in)
    case = build_fixture("symlink_to_outside", lab)
    assert calls == [("victim.txt", "lab-symlink-target.md", False)]
    assert case.claimed == ("changelog.d/lab-symlink-target.md",)
    assert case.facts["link"].read_bytes() == b"outside victim\n"

    def deny(*_args, **_kwargs):
        raise OSError(1314, "A required privilege is not held by the client")

    other = ExpressLab(lab.layout.root.parent / "second")
    other.symlink = functools.partial(create_symlink, symlink=deny)
    with pytest.raises(EnvironmentUnavailable, match="privilege"):
        build_fixture("symlink_to_outside", other)


def test_inbox_junction_entry_is_a_reparse_point_to_another_folder(lab: ExpressLab) -> None:
    case = make("inbox_junction_entry", lab)
    entry, target = case.facts["entry"], case.facts["target"]
    assert is_reparse_point(entry) and not is_reparse_point(target)
    assert os.path.samefile(entry, target) and lab.outside in target.parents
    assert (entry / "submission.json").read_bytes() == (target / "submission.json").read_bytes()


def test_inbox_hard_link_shares_its_bytes_with_a_file_outside(lab: ExpressLab) -> None:
    case = make("inbox_hard_linked_entry", lab)
    entry, shared = case.facts["entry"], case.facts["shared"]
    assert case.facts["links"] == link_count(entry) == 2 and os.path.samefile(entry, shared)
    assert lab.layout.inbox in entry.parents and lab.layout.inbox not in shared.parents


def test_inbox_alternate_stream_hides_bytes_on_the_patch(lab: ExpressLab) -> None:
    case = make("inbox_alternate_stream_entry", lab)
    patch = case.facts["entry"]
    assert case.facts["streams"] == [":hidden:$DATA"] == alternate_streams(patch)
    assert sorted(os.listdir(case.inbox_entry)) == ["change.patch", "submission.json"]  # the listing never shows it


def test_inbox_sparse_entry_claims_gigabytes_but_occupies_almost_nothing(lab: ExpressLab) -> None:
    from tests.express_winfs import allocated_size

    case = make("inbox_sparse_giant_entry", lab)
    giant = case.facts["entry"]
    assert giant.stat().st_size == case.facts["logical_size"] >= 4 * 1024**3
    assert allocated_size(giant) < 1 << 20


def test_forged_submission_claims_the_lane_over_a_never_eligible_patch_and_has_a_bare_twin(lab: ExpressLab) -> None:
    import json

    case = make("forged_submission", lab)
    forged = json.loads((case.facts["claimed"] / "submission.json").read_text(encoding="utf-8"))
    twin = json.loads((case.facts["stripped"] / "submission.json").read_text(encoding="utf-8"))
    assert forged["lane"] == "express" and forged["class"] == "D" and forged["eligible"] is True
    assert (
        forged["files"] == ["scripts/cage/self_change_promoter.py"]
        and twin == {}
        and (case.facts["claimed"] / "change.patch").read_bytes() == case.patches[0]
    )
    assert (case.facts["stripped"] / "change.patch").read_bytes() == case.patches[0]
    assert case.claimed == ("scripts/cage/self_change_promoter.py",) and not lab.repo.text("status", "--porcelain")
