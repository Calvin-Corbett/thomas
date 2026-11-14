"""The Express lab builder and its fakes behave the way later Express tests will rely on.

These tests pin the support code itself: an injected clock makes commits reproducible, git is called with a
scrubbed environment and an empty hooks folder, the fakes record what they were asked, the ACL lister is additive
the way NTFS is, and a hand-in folder has the shape the real handoff writes. The threat-lab fixtures are checked in
``test_express_lab_fixtures.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.express_fakes import START_EPOCH
from tests.express_lab_inbox import REAL_MANIFEST_KEYS
from tests.express_pytest import lab, skip_or_fail  # noqa: F401  (lab is a fixture)
from tests.express_support import (
    ExpressLab,
    FakeAclLister,
    FakeClock,
    FakeGrantTransport,
    FakePresence,
    PipeRefused,
    build_fixture,
    is_reparse_point,
    resolved_git,
    write_hand_in,
)
from tests.express_winfs import IS_WINDOWS, EnvironmentUnavailable

WRITE_SPELLINGS = ["AppendData", "CreateFiles", "Delete", "GenericWrite", "(M)", "Full control", "ChangePermissions"]


def test_the_clock_makes_commits_reproducible(tmp_path: Path) -> None:
    first = ExpressLab(tmp_path / "a")
    second = ExpressLab(tmp_path / "b")
    later = ExpressLab(tmp_path / "c", clock=FakeClock(START_EPOCH + 1))
    assert first.base_sha == second.base_sha
    assert later.base_sha != first.base_sha
    assert first.repo.text("log", "-1", "--format=%ct") == str(int(START_EPOCH) + 60)


def test_the_clock_only_moves_forward() -> None:
    clock = FakeClock()
    clock.advance(30)
    assert clock.monotonic() == 1030.0 and clock.time() == START_EPOCH + 30
    with pytest.raises(ValueError):
        clock.advance(-1)


def test_git_runs_with_a_scrubbed_environment(lab: ExpressLab, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_DIR", str(lab.layout.root / "not-a-repo"))
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", "evil")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    env = lab.repo.env()
    assert not {"GIT_DIR", "GIT_EXTERNAL_DIFF", "GIT_CONFIG_COUNT", "PATH"} & set(env)
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert lab.repo.head() == lab.base_sha  # the polluted variables never reached git
    assert os.path.isabs(resolved_git()) and lab.repo.git_path == resolved_git()


def test_the_repository_is_on_dev_and_a_planted_hook_never_runs(lab: ExpressLab) -> None:
    assert lab.repo.text("symbolic-ref", "--short", "HEAD") == "dev"
    hook = lab.repo.root / ".git" / "hooks" / "pre-commit"
    hook.write_bytes(b"#!/bin/sh\nexit 1\n")  # if git ran it, every commit below would be refused
    head = lab.repo.commit_files({"docs/after-hook.md": b"x\n"}, "a commit with a refusing hook in .git/hooks")
    assert lab.repo.head() == head != lab.base_sha


def test_a_crlf_lab_stores_lf_and_writes_crlf_for_markdown(tmp_path: Path) -> None:
    crlf = ExpressLab(tmp_path / "crlf", crlf=True)
    assert (
        crlf.repo.autocrlf and (crlf.repo.root / ".gitattributes").read_bytes() == b"* text=auto\n*.md text eol=crlf\n"
    )
    blob = crlf.repo.entry(b"line one\nline two\n")
    assert crlf.repo.filtered_bytes(blob.sha, "notes/x.md") == b"line one\r\nline two\r\n"
    assert crlf.repo.text("status", "--porcelain") == ""


def test_move_dev_advances_dev_by_one_commit(lab: ExpressLab) -> None:
    before = lab.repo.head()
    after = lab.repo.move_dev()
    assert after != before and lab.repo.text("rev-parse", f"{after}^") == before


def test_layout_names_every_folder_and_pins_by_hash(lab: ExpressLab) -> None:
    layout = lab.layout
    for folder in (layout.pins, layout.state, layout.inbox, layout.outbox, layout.requests, layout.hooks):
        assert folder.is_dir()
    assert layout.state.parent == layout.referee and layout.inbox.parent == layout.cage
    digest = layout.write_pin("express.policy", "ceiling=480\n")
    assert digest == hashlib.sha256(b"ceiling=480\n").hexdigest()
    assert (layout.pins / "express.policy").read_bytes() == b"ceiling=480\n"


def test_the_grant_transport_admits_only_an_elevated_caller() -> None:
    pipe = FakeGrantTransport()
    with pytest.raises(PipeRefused):
        pipe.send({"op": "grant", "minutes": 120}, elevated=False)
    assert pipe.send({"op": "grant", "minutes": 120}, elevated=True) == {"ok": True, "op": "grant"}
    assert [c.elevated for c in pipe.calls] == [False, True]
    assert len(pipe.refused()) == 1 and len(pipe.admitted("grant")) == 1 and pipe.admitted("off") == []
    open_pipe = FakeGrantTransport(elevated_only=False)
    open_pipe.send({"op": "off"}, elevated=False)
    assert open_pipe.refused() == [] and len(open_pipe.calls) == 1


def test_presence_follows_the_injected_clock() -> None:
    clock = FakeClock()
    presence = FakePresence(clock)
    clock.advance(600)
    assert presence.state().idle_seconds == 600 and not presence.state().locked
    presence.touch()
    assert presence.state().idle_seconds == 0
    presence.lock()
    assert presence.state().locked
    presence.unlock()
    presence.new_logon_session("session-2")
    assert presence.state().logon_session == "session-2" and not presence.state().locked


def test_acl_permissions_are_additive_so_a_child_entry_never_hides_an_inherited_writer(tmp_path: Path) -> None:
    acl = FakeAclLister()
    repo, child = tmp_path / "ThomasRepo", tmp_path / "ThomasRepo" / "changelog.d"
    acl.grant(repo, "BUILTIN\\Administrators", "FullControl")
    acl.grant(repo, "thomas-agent", "Modify")
    acl.grant(repo, "Users", "ReadAndExecute")
    assert acl.writers(child) == ["BUILTIN\\Administrators", "thomas-agent"]  # inherited from the parent
    acl.grant(child, "Users", "Read")  # an explicit entry for someone else changes nothing for thomas-agent
    assert acl.writers(child) == ["BUILTIN\\Administrators", "thomas-agent"]
    acl.revoke(repo, "thomas-agent")
    assert acl.writers(repo) == ["BUILTIN\\Administrators"] and acl.list(tmp_path / "elsewhere") == ()


def test_acl_block_inheritance_and_deny_follow_ntfs_order(tmp_path: Path) -> None:
    acl = FakeAclLister()
    repo, child = tmp_path / "repo", tmp_path / "repo" / "changelog.d"
    acl.grant(repo, "thomas-agent", "Modify")
    acl.block_inheritance(child)  # removing the inherited Modify is what the folder fix (plan C4) does
    assert acl.writers(child) == [] and acl.writers(repo) == ["thomas-agent"]
    acl.grant(child, "thomas-agent", "Modify", deny=True)
    acl.grant(child, "thomas-agent", "Modify")  # a deny is read before an allow on the same folder
    assert not acl.can_write(child, "thomas-agent")


def test_acl_groups_give_their_members_the_group_rights(tmp_path: Path) -> None:
    acl = FakeAclLister()
    acl.grant(tmp_path / "repo", "Builders", "Modify")
    assert acl.writers(tmp_path / "repo") == ["Builders"] and not acl.can_write(tmp_path / "repo", "thomas-agent")
    acl.add_member("Builders", "thomas-agent")
    assert acl.writers(tmp_path / "repo") == ["Builders", "thomas-agent"]


@pytest.mark.parametrize("group", ["Everyone", "BUILTIN\\Users", "NT AUTHORITY\\Authenticated Users", "INTERACTIVE"])
def test_a_modify_grant_to_a_broad_group_makes_every_account_a_writer(group: str, tmp_path: Path) -> None:
    """On a real machine every cage account is in these groups, so a lab that left it out would pass row 33 wrongly."""
    acl = FakeAclLister()
    acl.grant(tmp_path / "repo", group.lower(), "Modify")  # the name matches whatever its case
    assert acl.can_write(tmp_path / "repo", "thomas-agent")
    acl.block_inheritance(tmp_path / "repo" / "changelog.d")
    assert not acl.can_write(tmp_path / "repo" / "changelog.d", "thomas-agent")


def test_taking_ownership_counts_as_write_access(tmp_path: Path) -> None:
    acl = FakeAclLister()
    acl.grant(tmp_path, "thomas-agent", "TakeOwnership")  # an owner can then grant themselves anything
    assert acl.can_write(tmp_path, "thomas-agent")


@pytest.mark.parametrize("rights", WRITE_SPELLINGS)
def test_every_write_capable_spelling_counts_as_a_writer(rights: str, tmp_path: Path) -> None:
    acl = FakeAclLister()
    acl.grant(tmp_path, "thomas-agent", rights)
    assert acl.can_write(tmp_path, "thomas-agent"), rights


@pytest.mark.parametrize("rights", ["Read", "ReadAndExecute", "RX", "R", "ReadData", "ListDirectory"])
def test_read_rights_are_not_writers_and_an_unknown_right_raises(rights: str, tmp_path: Path) -> None:
    acl = FakeAclLister()
    acl.grant(tmp_path, "thomas-agent", rights)
    assert not acl.can_write(tmp_path, "thomas-agent")
    with pytest.raises(ValueError, match="unknown NTFS right"):
        acl.grant(tmp_path, "thomas-agent", "Frobnicate")


def test_patch_for_moves_neither_dev_nor_the_working_copy(lab: ExpressLab) -> None:
    before = (
        lab.repo.head(),
        lab.repo.text("status", "--porcelain"),
        sorted(os.listdir(lab.repo.root / "changelog.d")),
    )
    patch = lab.repo.patch_for({"changelog.d/new.md": lab.repo.entry(b"### Added\n- x\n")})
    assert b"diff --git a/changelog.d/new.md b/changelog.d/new.md" in patch
    assert lab.repo.raw_lines(patch)[0][4:] == ["A", "changelog.d/new.md"]
    after = (lab.repo.head(), lab.repo.text("status", "--porcelain"), sorted(os.listdir(lab.repo.root / "changelog.d")))
    assert before == after and before[1] == ""


def test_a_hand_in_folder_carries_every_key_the_real_handoff_writes(lab: ExpressLab) -> None:
    """Coupled on purpose to ``thomas/server/green_handoff.py::_write_submission``: if its keys change, so must this."""
    source = (Path(__file__).resolve().parent.parent / "thomas" / "server" / "green_handoff.py").read_text(
        encoding="utf-8"
    )
    assert all(f'"{key}"' in source for key in REAL_MANIFEST_KEYS)
    patch = lab.repo.patch_for({"changelog.d/new.md": lab.repo.entry(b"### Added\n- x\n")})
    folder = write_hand_in(lab.layout.inbox, "xpr-shape01", patch, lab.base_sha, {"execution_id": "run-1"})
    written = json.loads((folder / "submission.json").read_text(encoding="utf-8"))
    assert set(written) == set(REAL_MANIFEST_KEYS) and written["execution_id"] == "run-1"
    assert written["id"] == "xpr-shape01" and written["patch_sha256"] == hashlib.sha256(patch).hexdigest()
    assert written["files"] == ["changelog.d/new.md"] and (folder / "change.patch").read_bytes() == patch


def test_close_removes_junctions_before_the_scratch_root_goes(tmp_path: Path) -> None:
    lab = ExpressLab(tmp_path / "lab")
    try:
        try:
            case = build_fixture("junction_after_check", lab)
        except EnvironmentUnavailable as exc:
            skip_or_fail(str(exc))
        case.arm()
        folder = case.facts["parent"]
        canary = lab.outside / "canary.txt"
        assert is_reparse_point(folder) and canary.exists()
    finally:
        lab.close()
    assert not is_reparse_point(folder) and folder.is_dir()  # the real landing folder is back where it was
    assert (folder / "existing-fragment.md").exists() and canary.read_bytes() == b"outside canary\n"


def test_close_runs_every_undo_and_raises_for_each_one_that_failed(tmp_path: Path) -> None:
    lab = ExpressLab(tmp_path / "lab")
    ran: list[str] = []

    def stuck() -> None:
        raise OSError("stuck")

    lab.on_close(lambda: ran.append("first"))
    lab.on_close(stuck)
    lab.on_close(lambda: ran.append("last"))
    with pytest.raises(RuntimeError, match="stuck"):
        lab.close()
    assert ran == ["last", "first"]  # a failing undo did not stop the others


@pytest.mark.skipif(not IS_WINDOWS, reason="a junction is a Windows reparse point")
def test_close_notices_a_junction_that_is_still_there(tmp_path: Path) -> None:
    from tests.express_winfs import create_junction, remove_junction

    lab = ExpressLab(tmp_path / "lab")
    link = lab.outside / "leftover"
    create_junction(link, lab.layout.root)
    lab.on_close(lambda: None, gone=link)  # an undo that forgot to remove it
    try:
        with pytest.raises(RuntimeError, match="still a reparse point"):
            lab.close()
    finally:
        remove_junction(link)


def test_a_planted_filter_in_the_repository_config_never_runs(lab: ExpressLab) -> None:
    """Repo-local config is not trusted: a planted filter driver and its attributes line must not run a command."""
    canary = lab.layout.root / "canary.txt"
    git_dir = lab.repo.root / ".git"
    with open(git_dir / "config", "a", encoding="utf-8") as config:
        config.write(f'[filter "evil"]\n\tclean = echo ran >> "{canary.as_posix()}"\n')
    (git_dir / "info").mkdir(exist_ok=True)
    (git_dir / "info" / "attributes").write_text("README.md filter=evil\n", encoding="utf-8")
    lab.repo.commit_files({"README.md": b"changed so the filter would have to run\n"}, "touch the filtered file")
    lab.repo.git("status", "--porcelain")
    lab.repo.git("diff", "--textconv", "HEAD")
    assert not canary.exists()
    assert lab.repo.config_resets == 1 and "evil" not in (git_dir / "config").read_text(encoding="utf-8")
    assert not (git_dir / "info" / "attributes").exists()


@pytest.mark.parametrize(
    "spelling", ["MACHINE\\thomas-agent", "thomas-agent@MACHINE", "THOMAS-AGENT", "DOMAIN\\Thomas-Agent"]
)
def test_acl_grants_spelled_the_way_icacls_prints_them_reach_the_bare_account(spelling: str, tmp_path: Path) -> None:
    acl = FakeAclLister()
    acl.grant(tmp_path, spelling, "Modify")
    assert acl.can_write(tmp_path, "thomas-agent") and not acl.can_write(tmp_path, "someone-else")


@pytest.mark.parametrize(
    "who", ["S-1-1-0", "S-1-5-32-545", "S-1-5-11", "NT AUTHORITY\\BATCH", "NT AUTHORITY\\SERVICE", "LOCAL"]
)
def test_well_known_sids_and_service_groups_are_broad_groups(who: str, tmp_path: Path) -> None:
    acl = FakeAclLister()
    acl.grant(tmp_path, who, "Modify")
    assert acl.can_write(tmp_path, "thomas-agent")
