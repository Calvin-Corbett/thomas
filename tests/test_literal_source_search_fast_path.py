"""Literal searches skip line splitting in files that cannot contain a match."""

from __future__ import annotations

import re
from pathlib import Path

from thomas.tools import code_search_scan as scan


def test_literal_scan_preserves_results_without_splitting_nonmatching_files(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text("unrelated text\n" * 100, encoding="utf-8")
    (tmp_path / "b.py").write_text("first\nneedle here\nlast\n", encoding="utf-8")
    original = Path.read_text
    split_paths: list[str] = []

    class TrackedText(str):
        def splitlines(self, *args, **kwargs):
            split_paths.append(self.path_name)
            return super().splitlines(*args, **kwargs)

    def tracked_read(path: Path, *args, **kwargs) -> str:
        text = TrackedText(original(path, *args, **kwargs))
        text.path_name = path.name
        return text

    monkeypatch.setattr(Path, "read_text", tracked_read)
    rows, files, note = scan.search_lines(tmp_path, tmp_path, re.compile("needle"), file_glob="*.py", context=1)
    assert rows == ["b.py:1  first", "b.py:2> needle here", "b.py:3  last", "--"]
    assert files == 2
    assert note == ""
    assert split_paths == ["b.py"]


def test_case_insensitive_ascii_literal_skips_nonmatching_files(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.py").write_text("unrelated\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("NEEDLE here\n", encoding="utf-8")
    reads: list[str] = []
    original = scan._read_lines

    def counted_read(path: Path) -> list[str] | None:
        reads.append(path.name)
        return original(path)

    monkeypatch.setattr(scan, "_read_lines", counted_read)
    rows, files, note = scan.search_lines(tmp_path, tmp_path, re.compile("needle", re.IGNORECASE))
    assert (rows, files, note) == (["b.py:1: NEEDLE here"], 2, "")
    assert reads == []


def test_unicode_casefold_keeps_regex_matches(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("KELVIN K\n", encoding="utf-8")
    rows, files, note = scan.search_lines(tmp_path, tmp_path, re.compile("kelvin k", re.IGNORECASE))
    assert (rows, files, note) == (["a.py:1: KELVIN K"], 1, "")


def test_regex_scan_retains_nonliteral_and_case_insensitive_matches(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("Needle one\nneedle two\n", encoding="utf-8")
    for pattern in (re.compile("[Nn]eedle"), re.compile("needle", re.IGNORECASE)):
        rows, files, note = scan.search_lines(tmp_path, tmp_path, pattern, file_glob="*.py")
        assert rows == ["a.py:1: Needle one", "a.py:2: needle two"]
        assert files == 1
        assert note == ""


def test_literal_scan_does_not_match_across_line_boundaries(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("one\ntwo\n", encoding="utf-8")
    assert scan.search_lines(tmp_path, tmp_path, re.compile("one\ntwo"), file_glob="*.py") == ([], 1, "")
