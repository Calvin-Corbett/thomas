"""Publishing a public release needs a sign-in for that exact preview, and it writes only a review branch.

Proves scripts.forge.publish.public_release_publish and scripts.forge.publish.public_release (publish, confirm). The
public repository is a local bare repo, the sign-in is a stand-in function and the gh call is a fake. Nothing reaches
GitHub, and the real sign-in prompt is never shown.
"""

from __future__ import annotations

import time
from pathlib import Path

from scripts.forge.publish import public_release as pr
from scripts.forge.publish import public_release_preview as prev
from scripts.forge.publish import public_release_publish as pub

from tests.public_release_support import (  # noqa: F401
    CHANGELOG,
    clean_git_settings,
    make_dev,
    make_public,
    ok_preflight,
    refs,
    sh,
)

TODAY = "2026-11-03"
BRANCH = "release/1.2.3-2026-11-03"


def _setup(tmp_path: Path, extra: dict[str, str] | None = None, **kw: object) -> tuple[Path, Path, str, prev.Preview]:
    dev = make_dev(tmp_path, extra)
    bare, old = make_public(tmp_path)
    kw.setdefault("preflight", ok_preflight)
    return dev, bare, old, prev.build(dev, remote=str(bare), scratch_parent=tmp_path, today=TODAY, **kw)  # type: ignore[arg-type]


def _yes(_action: str, _reason: str) -> bool:
    return True


def test_publish_without_a_sign_in_refuses_and_sends_nothing(tmp_path: Path) -> None:
    _dev, bare, _old, preview = _setup(tmp_path)
    before = refs(bare)

    result = pr.publish(preview, None)

    assert not result.ok and "have not signed in" in result.refused
    assert refs(bare) == before


def test_a_declined_sign_in_gives_no_record_and_the_prompt_names_the_release(tmp_path: Path) -> None:
    _dev, _bare, _old, preview = _setup(tmp_path)
    asked: list[tuple[str, str]] = []

    def no(action: str, reason: str) -> bool:
        asked.append((action, reason))
        return False

    assert pr.confirm(preview, no) is None
    assert "1.2.3" in asked[0][0] and "main branch is not changed" in asked[0][0]


def test_a_sign_in_for_a_different_preview_refuses(tmp_path: Path) -> None:
    _dev, bare, _old, preview = _setup(tmp_path)
    other = prev.build(
        make_dev(tmp_path / "again", {"README.md": "changed\n"}), remote=str(bare), preflight=ok_preflight
    )
    record = pr.confirm(other, _yes)
    before = refs(bare)

    result = pr.publish(preview, record)

    assert not result.ok and "different preview" in result.refused
    assert refs(bare) == before


def test_a_record_made_by_hand_or_gone_stale_refuses(tmp_path: Path) -> None:
    _dev, bare, _old, preview = _setup(tmp_path)
    forged = pub.Confirmation(preview.digest(), pub.METHOD, time.time(), "0" * 64)
    old = pr.confirm(preview, _yes, now=time.time() - 3600)
    before = refs(bare)

    assert "not one this program made" in pr.publish(preview, forged).refused
    assert "too old" in pr.publish(preview, old).refused
    assert refs(bare) == before


def test_a_confirmed_preview_goes_to_a_review_branch_and_main_is_untouched(tmp_path: Path) -> None:
    _dev, bare, old, preview = _setup(tmp_path)
    before = refs(bare)

    result = pr.publish(preview, pr.confirm(preview, _yes))

    assert result.ok and result.pushed and result.branch == BRANCH and not result.signed
    after = refs(bare)
    assert after["refs/heads/main"] == before["refs/heads/main"] == old
    assert set(after) - set(before) == {f"refs/heads/{BRANCH}"}
    assert after[f"refs/heads/{BRANCH}"] == result.commit
    assert any("not signed" in line for line in result.lines)
    assert any("main was not changed" in line.lower() for line in result.lines)


def test_the_commit_has_the_public_main_as_its_only_parent_and_the_previewed_tree(tmp_path: Path) -> None:
    _dev, bare, old, preview = _setup(tmp_path)

    result = pr.publish(preview, pr.confirm(preview, _yes))

    assert sh(bare, "rev-list", "--parents", "-n", "1", result.commit).split() == [result.commit, old]
    assert sh(bare, "rev-parse", f"{result.commit}^{{tree}}") == preview.tree
    message = sh(bare, "log", "-1", "--format=%B", result.commit)
    assert message.startswith("Release 1.2.3\n\n- First change.\n- Second change.")
    assert "5 files; 3 private files left out" in message
    assert "private commit message" not in message
    assert sh(bare, "rev-list", "--count", result.commit) == "2"


def test_nothing_is_sent_on_a_dry_run(tmp_path: Path) -> None:
    _dev, bare, _old, preview = _setup(tmp_path)
    before = refs(bare)

    result = pr.publish(preview, pr.confirm(preview, _yes), dry_run=True)

    assert result.ok and result.dry_run and not result.pushed and result.commit
    assert refs(bare) == before
    assert "nothing was sent" in result.lines[0]


def test_a_branch_that_exists_gets_a_new_name_in_the_next_preview_and_this_one_is_refused(tmp_path: Path) -> None:
    dev, bare, _old, preview = _setup(tmp_path)
    first = pr.publish(preview, pr.confirm(preview, _yes))
    again = pr.publish(preview, pr.confirm(preview, _yes))
    next_preview = prev.build(dev, remote=str(bare), preflight=ok_preflight, scratch_parent=tmp_path, today=TODAY)

    assert first.branch == BRANCH and next_preview.branch == f"{BRANCH}-2"
    assert not again.ok and "already exists" in again.refused
    assert refs(bare)[f"refs/heads/{BRANCH}"] == first.commit


def test_only_a_release_branch_is_ever_written_and_a_diverged_one_is_refused_not_forced(tmp_path: Path) -> None:
    dev = make_dev(tmp_path)
    bare, old = make_public(tmp_path)
    ident = ("-c", "user.name=x", "-c", "user.email=x@x.invalid")
    other = sh(bare, *ident, "commit-tree", f"{old}^{{tree}}", "-p", old, "-m", "y")
    sh(bare, "update-ref", "refs/heads/release/taken", other)
    before = refs(bare)

    def made(name: str) -> prev.Preview:
        return prev.build(dev, remote=str(bare), preflight=ok_preflight, scratch_parent=tmp_path, branch=name)

    to_main = made("main")
    to_taken = made("release/taken")

    assert not pr.publish(to_main, pr.confirm(to_main, _yes)).ok
    assert "release/" in pr.publish(to_main, pr.confirm(to_main, _yes)).refused
    refused = pr.publish(to_taken, pr.confirm(to_taken, _yes))
    assert not refused.ok and "already exists" in refused.refused
    assert refs(bare) == before


def test_a_preview_that_is_not_safe_is_refused_even_when_signed(tmp_path: Path) -> None:
    _dev, bare, _old, preview = _setup(tmp_path, preflight=lambda _t: (False, "1 unexpected file"))
    before = refs(bare)

    result = pr.publish(preview, pr.confirm(preview, _yes))

    assert not result.ok and "1 unexpected file" in result.refused
    assert refs(bare) == before


def test_a_main_that_moved_after_the_preview_refuses(tmp_path: Path) -> None:
    _dev, bare, old, preview = _setup(tmp_path)
    moved = sh(
        bare,
        "-c",
        "user.name=x",
        "-c",
        "user.email=x@x.invalid",
        "commit-tree",
        f"{old}^{{tree}}",
        "-p",
        old,
        "-m",
        "x",
    )
    sh(bare, "update-ref", "refs/heads/main", moved)

    result = pr.publish(preview, pr.confirm(preview, _yes))

    assert not result.ok and "changed on GitHub after the preview" in result.refused
    assert refs(bare)["refs/heads/main"] == moved


def test_a_signing_key_that_does_not_work_refuses_instead_of_sending_it_unsigned(
    tmp_path: Path, clean_git_settings: Path
) -> None:
    # A signing program that is not there, so no real gpg runs and starts a background agent in the test home.
    program = (tmp_path / "no-such-gpg.exe").as_posix()
    clean_git_settings.write_text("[gpg]\n\tprogram = " + program + "\n", encoding="utf-8")
    _dev, bare, _old, preview = _setup(tmp_path)
    before = refs(bare)

    result = pr.publish(preview, pr.confirm(preview, _yes), signing_key="0123456789ABCDEF")

    assert not result.ok and "could not be made and signed" in result.refused
    assert refs(bare) == before


def test_a_message_that_names_the_person_who_made_the_commits_is_refused(
    tmp_path: Path, clean_git_settings: Path
) -> None:
    clean_git_settings.write_text("[user]\n\tname = Zed Quill\n", encoding="utf-8")
    named = CHANGELOG.replace("**First change.**", "**First change by Zed Quill.**")
    _dev, bare, _old, preview = _setup(tmp_path, {"CHANGELOG.md": named})
    before = refs(bare)

    result = pr.publish(preview, pr.confirm(preview, _yes))

    assert not result.ok and "would name Zed Quill" in result.refused
    assert refs(bare) == before


def test_a_pull_request_is_opened_only_when_asked_and_the_review_rule_is_said_plainly(tmp_path: Path) -> None:
    _dev, bare, _old, preview = _setup(tmp_path)
    calls: list[list[str]] = []

    def fake_gh(args: list[str], _cwd: Path) -> tuple[int, str]:
        calls.append(args)
        return 0, "https://github.com/example/thomas/pull/7"

    # A remote that is not a GitHub address cannot name a repository for gh, so it is refused before anything is sent.
    refused = pr.publish(preview, pr.confirm(preview, _yes), open_pr=True, gh=fake_gh)
    assert not refused.ok and "GitHub address" in refused.refused and calls == []

    quiet = pr.publish(preview, pr.confirm(preview, _yes), gh=fake_gh)
    assert calls == [] and any("No pull request was opened" in line for line in quiet.lines)


def test_the_pull_request_call_names_the_review_branch_and_says_merging_is_yours() -> None:
    result = pub.PublishResult(True, branch=BRANCH)
    preview = prev.Preview("1.2.3", "a", "b", None, "", "main", 1, {}, None)
    seen: list[list[str]] = []

    def fake_gh(args: list[str], _cwd: Path) -> tuple[int, str]:
        seen.append(args)
        return 0, "https://github.com/example/thomas/pull/7"

    pub._open_pr(result, preview, Path("."), ("example", "thomas"), fake_gh)

    assert seen[0][:8] == ["pr", "create", "--repo", "example/thomas", "--base", "main", "--head", BRANCH]
    assert result.pr_url.endswith("/pull/7")
    assert "merging is your step in GitHub" in result.lines[-1]


def test_the_command_line_asks_for_the_sign_in_and_stops_when_it_is_declined(monkeypatch, tmp_path, capsys) -> None:
    dev = make_dev(tmp_path)
    bare, _old = make_public(tmp_path)
    monkeypatch.setattr(prev, "default_preflight", ok_preflight)
    asked: list[str] = []
    real_confirm = pr.confirm
    monkeypatch.setattr(pr, "confirm", lambda p: real_confirm(p, lambda a, r: asked.append(a) or False))
    before = refs(bare)

    code = pr.main(["publish", "--repo", str(dev), "--remote", str(bare)])

    assert code == 1 and len(asked) == 1
    assert refs(bare) == before
    assert "have not signed in" in capsys.readouterr().out


def test_the_command_line_preview_sends_nothing_and_a_dry_run_sends_nothing(monkeypatch, tmp_path, capsys) -> None:
    dev = make_dev(tmp_path)
    bare, _old = make_public(tmp_path)
    monkeypatch.setattr(prev, "default_preflight", ok_preflight)
    real_confirm = pr.confirm
    monkeypatch.setattr(pr, "confirm", lambda p: real_confirm(p, _yes))
    before = refs(bare)

    assert pr.main(["preview", "--repo", str(dev), "--remote", str(bare)]) == 0
    assert "Safe to publish." in capsys.readouterr().out
    assert pr.main(["publish", "--repo", str(dev), "--remote", str(bare), "--dry-run"]) == 0
    assert "nothing was sent" in capsys.readouterr().out
    assert refs(bare) == before
