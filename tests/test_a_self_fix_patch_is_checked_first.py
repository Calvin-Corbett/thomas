"""A self-fix whose patch could reach outside Thomas's code is refused before you are asked.

From the spec's CVE survey (docs/superpowers/specs/2026-09-22-trusted-self-change-
design.md, section 7, "write safety"): a patch may not add a symlink or submodule,
change a file mode, rename, touch runtime/ or git itself, climb out with ``..``,
or write through a folder that is really a link. Each of these is refused by the
promoter, before any prompt, and a patch altered after it was submitted is too.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp

from tests.green_support import git, make_blue
from thomas.server import green_checkout, green_handoff
from thomas.tools import cage_shell, trusted_card

_OK = "diff --git a/thomas/fix_me.py b/thomas/fix_me.py\nindex 1..2 100644\n--- a/thomas/fix_me.py\n+++ b/thomas/fix_me.py\n"


@pytest.fixture
def blue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "green-root"))
    repo = make_blue(tmp_path)
    git(repo, "checkout", "-q", "-b", "dev")
    return repo


def test_an_ordinary_patch_is_allowed(blue: Path) -> None:
    assert checks.write_safety_refusal(_OK, blue) is None


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ("diff --git a/link b/link\nnew file mode 120000\n", "symlink"),
        ("diff --git a/vendor b/vendor\nnew file mode 160000\n", "submodule"),
        ("diff --git a/t.py b/t.py\nindex 1..2 120000\n", "symlink"),
        ("diff --git a/t.py b/t.py\nold mode 100644\nnew mode 100755\n", "mode"),
        ("diff --git a/a.py b/b.py\nsimilarity index 90%\nrename from a.py\nrename to b.py\n", "header"),
        ("diff --git a/a.py b/a.py\nsimilarity index 90%\ncopy from b.py\n", "renames or copies"),
        ("diff --git a/runtime/state.json b/runtime/state.json\n", "may not change"),
        ("diff --git a/sub/.git/config b/sub/.git/config\n", "may not change"),
        ("diff --git a/.git/hooks/pre-commit b/.git/hooks/pre-commit\n", "may not change"),
        ("diff --git a/../outside.py b/../outside.py\n", "unsafe path"),
        ('diff --git "a/odd name.py" "b/odd name.py"\n', "header"),
        ("", "changes nothing"),
    ],
)
def test_an_unsafe_patch_is_refused(blue: Path, patch: str, reason: str) -> None:
    refusal = checks.write_safety_refusal(patch, blue)

    assert refusal is not None and reason in refusal


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows reparse point")
def test_a_folder_that_is_really_a_link_is_refused(blue: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(blue / "linked"), str(elsewhere)], capture_output=True)
    assert made.returncode == 0, made.stderr
    patch = "diff --git a/linked/x.py b/linked/x.py\n"

    refusal = checks.write_safety_refusal(patch, blue)

    assert refusal is not None and "is a link" in refusal


def test_a_patch_changed_after_it_was_submitted_is_refused_before_asking(blue: Path, tmp_path: Path) -> None:
    green = green_checkout.create_green(blue, "exec-swapped")
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    sub = green_handoff.settle("exec-swapped", promote=True, summary="Fixed.", chat="c")
    assert sub is not None
    (sub / "change.patch").write_bytes((sub / "change.patch").read_bytes().replace(b"VALUE = 2", b"VALUE = 9"))
    pins = tmp_path / "pins"
    pins.mkdir()
    (pins / trusted_card.PIN_NAME).write_text(trusted_card.catalogue_digest(trusted_card.CATALOGUE_PATH))
    asked: list[str] = []

    outcome = sp.Promoter(
        repo=blue,
        cage_root=cage_shell.cage_root(),
        ask=lambda action, reason: bool(asked.append(action)),
        pin_root=pins,
        audit=lambda _r: [],
    ).promote(sub)

    assert outcome.status == "refused" and "hash" in outcome.detail
    assert asked == []
