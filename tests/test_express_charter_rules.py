"""Referee core, Charter rules checked without a repository (plan B1): modes, headers, reparse files."""

from __future__ import annotations

import pytest
from scripts.cage.referee.charter import Charter

from tests.express_referee_support import FRAGMENT, decide, entry, git, lab, patch_adding  # noqa: F401
from tests.express_winfs import IS_WINDOWS

GOOD = "changelog.d/lab-fixture-note.md"


def test_mode_is_judged_on_the_derived_entry(lab):
    """A new fragment with a mode other than 100644 is demoted by the mode rule itself, whatever applied the patch."""
    from scripts.cage.referee.derive import Change, Derived

    blob = "a" * 40
    for mode, code in (("100755", "mode"), ("120000", "symlink"), ("160000", "gitlink")):
        change = Change("A", "000000", mode, "0" * 40, blob, GOOD)
        derived = Derived("t" * 40, "r" * 40, (change,), {blob: len(FRAGMENT)}, {blob: FRAGMENT}, frozenset())
        assert decide_derived(derived).code == code
    plain = Change("A", "000000", "100644", "0" * 40, blob, GOOD)
    assert (
        decide_derived(Derived("t" * 40, "r" * 40, (plain,), {blob: len(FRAGMENT)}, {blob: FRAGMENT}, frozenset())).lane
        == "express"
    )


def decide_derived(derived):
    from scripts.cage.referee.charter import decide

    return decide(derived, Charter())


def test_a_header_naming_another_file_cannot_change_the_decision(lab, git):
    """The ``diff --git`` line says a cage file; the content lines say a fragment: never Express (git refuses it)."""
    blob = entry(lab, FRAGMENT).sha.encode()
    patch = (
        b"diff --git a/scripts/cage/evil.py b/scripts/cage/evil.py\nnew file mode 100644\nindex 0000000.." + blob[:7]
        + b"\n--- /dev/null\n+++ b/changelog.d/lab-header-note.md\n@@ -0,0 +1,2 @@\n+### Added\n+- A plain change.\n"
    )  # fmt: skip
    decision = decide(lab, git, patch)  # git itself refuses a header that disagrees with the content lines
    assert (decision.lane, decision.code) == ("regular", "patch_does_not_apply"), decision


@pytest.mark.skipif(not IS_WINDOWS, reason="junctions are an NTFS behaviour")
def test_a_reparse_point_given_as_the_file_is_refused_as_one(lab):
    from scripts.cage.referee.nofollow import UnsafeEntry, default_fs

    from tests.express_winfs import create_junction, remove_junction

    link = lab.layout.root / "link-as-file"
    create_junction(link, lab.outside)
    lab.on_close(lambda: remove_junction(link), gone=link)
    with pytest.raises(UnsafeEntry) as refused:
        default_fs().read_regular(link, 1000)
    assert refused.value.code == "reparse_point"


def test_a_tip_must_be_a_whole_commit_id_and_must_exist(lab, git):
    from scripts.cage.referee.derive import DeriveFailed, derive, evaluate

    patch = patch_adding(lab, {GOOD: FRAGMENT})
    tip = lab.repo.head()
    for bad in (tip + "zz", tip + "\n", tip[:39], tip.upper(), "dev", ""):
        with pytest.raises(DeriveFailed) as refused:
            derive(git, bad, patch)
        assert refused.value.code == "bad_tip", bad
    with pytest.raises(DeriveFailed) as missing:
        evaluate(git, "1" * 40, patch, Charter())
    assert missing.value.code == "tip_missing"  # a wrong tip is the caller's error, never a quiet demotion
    assert derive(git, tip, patch).tip == tip


def test_a_refusing_git_demotes_and_a_crashed_git_raises(lab, git, monkeypatch):
    from scripts.cage.referee import gitenv
    from scripts.cage.referee.derive import evaluate

    patch, tip, real = patch_adding(lab, {GOOD: FRAGMENT}), lab.repo.head(), gitenv.GitRunner.run

    def failing(crashed):
        def run(self, *args, **kwargs):
            if args[0] == "write-tree":
                raise gitenv.GitFailed("simulated", crashed=crashed)
            return real(self, *args, **kwargs)

        return run

    monkeypatch.setattr(gitenv.GitRunner, "run", failing(False))
    decision = evaluate(git, tip, patch, Charter())
    assert (decision.lane, decision.code) == ("regular", "git_failed")
    monkeypatch.setattr(gitenv.GitRunner, "run", failing(True))
    with pytest.raises(gitenv.GitFailed):
        evaluate(git, tip, patch, Charter())
