"""The monolith guard must not read a file's history through the console's codec.

`_git_blob_line_count` shells out to `git show HEAD:<path>` to learn how many
lines a file had before this change, and it asked subprocess for text without
saying which encoding. Python then fell back to the platform codec -- cp1252 on
this machine -- so one byte outside that set took the read down.

On Windows subprocess decodes captured output on a reader thread. The
UnicodeDecodeError died there, never reached the caller, and `returncode` stayed
0. The function read that as "git succeeded, output empty" and returned **0**,
which the guard understood as "the file had no lines at HEAD". Growth is
`now - baseline`, so a decode failure reported the entire file as new: the
maximum blocking verdict, justified by a number that was not true.

Measured on 2026-09-09: `thomas/server/web/js/unified_work_mode.js`, a valid
UTF-8 file 864 lines long and barely changed, was refused as
`baseline 0, growth 864, max_growth 30`.
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest
from scripts.forge.gates import monolith_guard as mg

# U+201D RIGHT DOUBLE QUOTATION MARK. Valid UTF-8, and its second byte is 0x9d --
# which cp1252 has no character for. An ordinary curly quote in a comment.
UNMAPPABLE = "\u201d"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


def _repo(tmp_path: Path, body: str) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "f.js").write_text(body, encoding="utf-8")
    _git(root, "add", "f.js")
    _git(root, "commit", "-qm", "seed")
    return root


def test_a_curly_quote_does_not_erase_a_files_history(tmp_path: Path):
    """The load-bearing case: the count must be the real one, not zero."""
    body = "\n".join([f"// line {i}{UNMAPPABLE}" for i in range(40)]) + "\n"
    root = _repo(tmp_path, body)
    assert mg._git_blob_line_count(root, ref="HEAD", rel_path="f.js") == 40


def test_a_plain_ascii_file_is_unaffected(tmp_path: Path):
    root = _repo(tmp_path, "a\nb\nc\n")
    assert mg._git_blob_line_count(root, ref="HEAD", rel_path="f.js") == 3


def test_an_empty_blob_is_zero_and_a_missing_one_is_none(tmp_path: Path):
    """Zero must keep meaning "really empty", which is why the bug was invisible."""
    root = _repo(tmp_path, "")
    assert mg._git_blob_line_count(root, ref="HEAD", rel_path="f.js") == 0
    assert mg._git_blob_line_count(root, ref="HEAD", rel_path="never.js") is None


def test_the_guard_does_not_report_growth_for_an_unchanged_file(tmp_path: Path):
    """End to end: the wrong count became a wrong verdict, so assert the verdict."""
    body = "\n".join([f"// line {i}{UNMAPPABLE}" for i in range(40)]) + "\n"
    root = _repo(tmp_path, body)
    before = mg._git_blob_line_count(root, ref="HEAD", rel_path="f.js")
    (root / "f.js").write_text(body + f"// one more{UNMAPPABLE}\n", encoding="utf-8")
    after = len((root / "f.js").read_text(encoding="utf-8").splitlines())
    assert before is not None
    assert after - before == 1, "growth must be the one line added, not the whole file"


@pytest.mark.parametrize("reader", ["_git_changed_files", "_git_staged_files", "_git_ref_exists"])
def test_every_git_reader_names_its_codec(reader: str):
    """A sibling left on the platform codec is the same bug waiting."""
    src = inspect.getsource(getattr(mg, reader))
    if "text=True" in src:
        assert 'encoding="utf-8"' in src, f"{reader} decodes through the platform codec"
