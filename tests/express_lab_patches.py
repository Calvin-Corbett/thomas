"""Patch fixtures: hand-ins whose content is the trick.

Most are real ``git diff --binary`` output built from a private index, so they carry exactly the modes and
statuses a tree comparison would see (gitlink 160000, symlink 120000, rename, binary, mode change). Spellings git
itself would refuse to write (a NUL byte, ``./``, ``.git``, control characters) are written by hand. The poison and
oversized fixtures carry the content sizes the plan names (a 600 KB patch, a 200,000-term expression, a
100,000-deep unary chain); nothing in the lab applies or compiles them. Each fixture has one fault where that is
physically possible. The changelog-fragment fixtures keep a valid flat name (``changelog.d/lab-<slug>.md``) and a
valid fragment body; the poison, ``.pyc``, rename, mode-change and forged fixtures use the paths their trick needs. A fixture states
what it is and gives no opinion on what should happen to it.
"""

from __future__ import annotations

import sys
from typing import NamedTuple

from tests.express_lab import ExpressLab, LabCase, lab_fixture
from tests.express_repo import TreeEntry

EXISTING = "changelog.d/existing-fragment.md"
PAYLOAD = b"### Added\n- A scratch change for the lab.\n"
POISON_TERMS = 200_000
POISON_DEPTH = 100_000
OVERSIZE_BYTES = 600 * 1024


def _case(lab: ExpressLab, name: str, kind: str, trick: str, **fields: object) -> LabCase:
    return LabCase(name, kind, trick, False, lab.layout.root, **fields)  # type: ignore[arg-type]


def hand_written_add(lab: ExpressLab, path: bytes, body: bytes = b"x\n", *, quoted: bool = False) -> bytes:
    """A new-file patch whose header spells ``path`` exactly as given, including spellings git would normalise.

    ``quoted`` wraps each name in double quotes, which is how git writes a name with a control character in it
    (the control character itself then appears as a backslash escape inside ``path``).
    """
    blob = lab.repo.entry(body).sha.encode()
    q = b'"' if quoted else b""
    return (
        b"diff --git " + q + b"a/" + path + q + b" " + q + b"b/" + path + q + b"\nnew file mode 100644\n"
        b"index 0000000.." + blob[:7] + b"\n--- /dev/null\n+++ " + q + b"b/" + path + q + b"\n@@ -0,0 +1 @@\n+"
        + body.rstrip(b"\n") + b"\n"
    )  # fmt: skip


@lab_fixture("control_plain_fragment", "control")
def control_plain_fragment(lab: ExpressLab) -> LabCase:
    """The fixture with no fault: a plain valid new fragment, so a later test can show a lander does land something."""
    path = "changelog.d/brand-new-fragment.md"
    patch = lab.repo.patch_for({path: lab.repo.entry(PAYLOAD)})
    return _case(
        lab, "control_plain_fragment", "control", "a plain valid new fragment", claimed=(path,), patches=(patch,)
    )


@lab_fixture("gitlink", "patch")
def gitlink(lab: ExpressLab) -> LabCase:
    patch = lab.repo.patch_for({"changelog.d/lab-gitlink.md": TreeEntry("160000", "a" * 40)})
    return _case(lab, "gitlink", "patch", "a submodule pointer (mode 160000) added to the tree", patches=(patch,))


@lab_fixture("mode_change", "patch")
def mode_change(lab: ExpressLab) -> LabCase:
    blob = lab.repo.text("rev-parse", f"HEAD:{EXISTING}")
    patch = lab.repo.patch_for({EXISTING: TreeEntry("100755", blob)})
    trick = "an existing file made executable (100644 to 100755)"
    return _case(lab, "mode_change", "patch", trick, patches=(patch,))


@lab_fixture("rename", "patch")
def rename(lab: ExpressLab) -> LabCase:
    entry = TreeEntry("100644", lab.repo.text("rev-parse", f"HEAD:{EXISTING}"))
    patch = lab.repo.patch_for({EXISTING: None, "changelog.d/renamed-fragment.md": entry})
    trick = "an existing file renamed, which git reports as a rename"
    return _case(lab, "rename", "patch", trick, patches=(patch,))


@lab_fixture("binary_blob", "patch")
def binary_blob(lab: ExpressLab) -> LabCase:
    patch = lab.repo.patch_for({"changelog.d/lab-blob.md": lab.repo.entry(b"\x00\x01\x02binary\xff\xfe")})
    return _case(lab, "binary_blob", "patch", "a new file with binary content", patches=(patch,))


@lab_fixture("pyc_file", "patch")
def pyc_file(lab: ExpressLab) -> LabCase:
    blob = lab.repo.entry(b"\xcb\x0d\x0d\x0a\x00\x00\x00\x00compiled")
    paths = ("thomas/core/leaf.pyc", "thomas/core/__pycache__/leaf.cpython-312.pyc")
    patches = tuple(lab.repo.patch_for({p: blob}) for p in paths)
    return _case(lab, "pyc_file", "patch", "compiled bytecode added to the tree", patches=patches, claimed=paths)


@lab_fixture("symlink_patch", "patch")
def symlink_patch(lab: ExpressLab) -> LabCase:
    patch = lab.repo.patch_for({"changelog.d/lab-symlink.md": lab.repo.entry(b"../../outside", "120000")})
    return _case(lab, "symlink_patch", "patch", "a symlink (mode 120000) added to the tree", patches=(patch,))


@lab_fixture("nul_byte_path", "patch")
def nul_byte_path(lab: ExpressLab) -> LabCase:
    patch = hand_written_add(lab, b"changelog.d/lab-ok\x00.md")
    return _case(lab, "nul_byte_path", "patch", "a header path with a NUL byte in it", patches=(patch,))


class Spelling(NamedTuple):
    text: bytes  # exactly as it appears inside the header
    meaning: str  # the path the file system would read it as, for the self-test
    quoted: bool


NON_CANONICAL = (
    Spelling(b"changelog.d/./lab-x.md", "changelog.d/./lab-x.md", False),
    Spelling(b"changelog.d//lab-x.md", "changelog.d//lab-x.md", False),
    Spelling(b"./changelog.d/lab-x.md", "./changelog.d/lab-x.md", False),
    Spelling(b"changelog.d/../changelog.d/lab-x.md", "changelog.d/../changelog.d/lab-x.md", False),
    Spelling(b"changelog.d\\lab-x.md", "changelog.d\\lab-x.md", False),
    Spelling(b"CHANGELOG.D/lab-x.md", "CHANGELOG.D/lab-x.md", False),
    Spelling(b"changelog.d/lab-x.md/", "changelog.d/lab-x.md/", False),
    Spelling(b"changelog.d/lab-x.md\r", "changelog.d/lab-x.md\r", False),
    Spelling(b"changelog.d/lab-x.md\t", "changelog.d/lab-x.md\t", False),
    Spelling(b"changelog.d/lab-x.md\\n", "changelog.d/lab-x.md\n", True),
    Spelling(b"changelog.d/lab-x.md\\t", "changelog.d/lab-x.md\t", True),
)


@lab_fixture("non_canonical_spelling", "patch")
def non_canonical_spelling(lab: ExpressLab) -> LabCase:
    patches = tuple(hand_written_add(lab, s.text, quoted=s.quoted) for s in NON_CANONICAL)
    trick = "paths spelled other than in canonical form, including control characters raw and in git's quoted form"
    return _case(lab, "non_canonical_spelling", "patch", trick, patches=patches)


@lab_fixture("oversized_patch", "patch")
def oversized_patch(lab: ExpressLab) -> LabCase:
    body = b"### Added\n" + b"- a long line of filler text that only adds weight\n" * (OVERSIZE_BYTES // 50 + 1)
    patch = lab.repo.patch_for({"changelog.d/lab-huge.md": lab.repo.entry(body)})
    return _case(
        lab, "oversized_patch", "patch", "a patch of about 600 KB", patches=(patch,), facts={"bytes": len(patch)}
    )


def _poison(lab: ExpressLab, name: str, path: str, source: bytes, trick: str) -> LabCase:
    """A poison source carried in a patch (about 400 KB for the terms, 100 KB for the unary chain)."""
    patch = lab.repo.patch_for({path: lab.repo.entry(source)})
    facts = {"source": source, "python": sys.version}  # the poison is proved on this interpreter, not the referee's
    return _case(lab, name, "poison", trick, patches=(patch,), claimed=(path,), facts=facts)


@lab_fixture("poison_terms", "poison")
def poison_terms(lab: ExpressLab) -> LabCase:
    source = b"X = " + b"+".join([b"1"] * POISON_TERMS) + b"\n"
    return _poison(lab, "poison_terms", "thomas/core/poison_terms.py", source, "a 200,000-term expression")


@lab_fixture("poison_unary", "poison")
def poison_unary(lab: ExpressLab) -> LabCase:
    source = b"X = " + b"-" * POISON_DEPTH + b"1\n"
    return _poison(lab, "poison_unary", "thomas/core/poison_unary.py", source, "a 100,000-deep unary chain")
