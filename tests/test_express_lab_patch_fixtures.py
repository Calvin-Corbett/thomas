"""Self-test of the patch fixtures: each hostile patch really is what it says, as git itself reports it.

The facts are the ones ``git diff-tree --raw`` gives for the patch applied to ``dev`` (``TempGitRepo.raw_lines``),
never the text of the patch: a mode, a status, a rename, a binary body, a path git derives. Spellings git would not
write itself (a NUL byte, ``./``, control characters) are checked in the patch text instead. The poison patches are
checked by compiling their source in a child process on this interpreter.
"""

from __future__ import annotations

import posixpath
import subprocess
import sys

import pytest

from tests.express_lab_patches import NON_CANONICAL
from tests.express_pytest import lab, make  # noqa: F401  (lab is a fixture)
from tests.express_support import ExpressLab


@pytest.mark.parametrize(
    ("name", "old_mode", "new_mode", "status"),
    [
        ("gitlink", "000000", "160000", "A"),
        ("mode_change", "100644", "100755", "M"),
        ("symlink_patch", "000000", "120000", "A"),
        ("control_plain_fragment", "000000", "100644", "A"),
    ],
)
def test_patch_fixture_carries_the_mode_git_reports(name, old_mode, new_mode, status, lab: ExpressLab) -> None:
    rows = lab.repo.raw_lines(make(name, lab).patches[0])
    assert len(rows) == 1 and rows[0][:2] == [old_mode, new_mode] and rows[0][4] == status


def test_rename_is_reported_by_git_as_a_rename(lab: ExpressLab) -> None:
    patch = make("rename", lab).patches[0]
    assert b"\nrename from changelog.d/existing-fragment.md\n" in patch and b"\nrename to " in patch
    rows = lab.repo.raw_lines(patch)
    assert len(rows) == 1 and rows[0][4].startswith("R")
    assert rows[0][5:] == ["changelog.d/existing-fragment.md", "changelog.d/renamed-fragment.md"]


def test_binary_and_pyc_fixtures_carry_binary_content(lab: ExpressLab) -> None:
    assert b"GIT binary patch" in make("binary_blob", lab).patches[0]
    pyc = make("pyc_file", lab)
    assert len(pyc.patches) == 2 and any("__pycache__/" in c for c in pyc.claimed)
    for patch, claimed in zip(pyc.patches, pyc.claimed, strict=True):
        assert claimed.endswith(".pyc") and b"GIT binary patch" in patch and lab.repo.raw_lines(patch)[0][5] == claimed


def test_nul_byte_is_in_the_header_path(lab: ExpressLab) -> None:
    patch = make("nul_byte_path", lab).patches[0]
    header = patch.split(b"\n", 1)[0]
    assert header.startswith(b"diff --git a/changelog.d/") and header.count(b"\x00") == 2


def _canonical(meaning: str) -> str:
    return posixpath.normpath(meaning.replace("\\", "/").rstrip("\r\n\t /")).lower()


def test_non_canonical_spellings_all_differ_from_the_canonical_one(lab: ExpressLab) -> None:
    case = make("non_canonical_spelling", lab)
    assert len(case.patches) == len(NON_CANONICAL)
    for spelling, patch in zip(NON_CANONICAL, case.patches, strict=True):
        q = b'"' if spelling.quoted else b""
        assert b"diff --git " + q + b"a/" + spelling.text + q + b" " + q + b"b/" + spelling.text + q in patch
        assert spelling.meaning != "changelog.d/lab-x.md"
        assert _canonical(spelling.meaning) == "changelog.d/lab-x.md"  # the same place, spelled oddly
    assert any(s.quoted for s in NON_CANONICAL) and any(b"\r" in s.text for s in NON_CANONICAL)


def test_oversized_patch_is_600_kb_and_otherwise_valid(lab: ExpressLab) -> None:
    case = make("oversized_patch", lab)
    patch = case.patches[0]
    # The sizes below are the plan's own numbers, written out here rather than read from the builder's constants:
    # a test that takes its expectation from the code it checks passes when that constant is shrunk.
    assert len(patch) >= 600 * 1024 and case.facts["bytes"] == len(patch)
    assert lab.repo.raw_lines(patch)[0][4] == "A"


@pytest.mark.parametrize(("name", "count"), [("poison_terms", 200_000), ("poison_unary", 100_000)])
def test_poison_source_has_the_size_and_really_breaks_the_compiler(name: str, count: int, lab: ExpressLab) -> None:
    case = make(name, lab)
    source = case.facts["source"]
    operator = b"+" if name == "poison_terms" else b"-"
    assert source.count(operator) == (count - 1 if name == "poison_terms" else count)
    assert lab.repo.raw_lines(case.patches[0])[0][4:] == ["A", case.claimed[0]]  # git sees one added file, the poison
    done = subprocess.run(
        [sys.executable, "-c", "import sys; compile(sys.stdin.buffer.read(), 'poison', 'exec')"],
        input=source,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert done.returncode != 0  # the interpreter refuses it, one way or another, instead of compiling it


def test_a_valid_fragment_control_exists_so_no_test_passes_by_refusing_everything(lab: ExpressLab) -> None:
    case = make("control_plain_fragment", lab)
    assert case.claimed == ("changelog.d/brand-new-fragment.md",)
    assert lab.repo.raw_lines(case.patches[0])[0][5] == "changelog.d/brand-new-fragment.md"
