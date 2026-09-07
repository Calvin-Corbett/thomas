"""``diff.create`` matches the text the model meant when only line endings or trailing spaces differ (2026-09-05).

Fifteen ``diff.create`` calls on one day's Build transcripts failed with
"old_str not found ... Make sure the text matches exactly including
whitespace". The game files on this machine end lines with CRLF and the model
writes LF; a search string that is byte-exact except for that can never match,
and every miss cost a round. A match that differs only in line endings or in
trailing whitespace is the text the model meant: it is applied, the file keeps
its own line endings, and the result says what was forgiven. A search string
that is genuinely absent is still refused.

Also pinned: the tool used to read with universal newlines and write back LF,
so every edit silently turned a CRLF file into an LF file.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thomas.tools.diff import CreateDiffTool


def _run(tool, args):
    return asyncio.run(tool.execute(args))


def test_lf_old_str_matches_a_crlf_file_and_the_file_keeps_crlf(tmp_path: Path) -> None:
    (tmp_path / "game.js").write_bytes(b"function loop() {\r\n  update();\r\n  render();\r\n}\r\n")
    result = _run(
        CreateDiffTool(tmp_path),
        {"file": "game.js", "old_str": "  update();\n  render();\n", "new_str": "  update();\n  render();\n  tick();\n"},
    )
    assert result.ok, result.error
    raw = (tmp_path / "game.js").read_bytes()
    assert raw == b"function loop() {\r\n  update();\r\n  render();\r\n  tick();\r\n}\r\n", raw
    assert "line ending" in str(result.data).lower()


def test_trailing_spaces_in_the_file_do_not_defeat_the_match(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha   \nbeta\ngamma  \n", encoding="utf-8")
    result = _run(CreateDiffTool(tmp_path), {"file": "a.txt", "old_str": "alpha\nbeta\n", "new_str": "ALPHA\nbeta\n"})
    assert result.ok, result.error
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "ALPHA\nbeta\ngamma  \n"
    assert "trailing" in str(result.data).lower()


def test_a_genuinely_absent_old_str_is_still_refused(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    result = _run(CreateDiffTool(tmp_path), {"file": "a.txt", "old_str": "delta\n", "new_str": "x\n"})
    assert not result.ok
    assert "old_str not found" in str(result.error)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "alpha\nbeta\n"


def test_an_exact_match_is_applied_without_any_note(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    result = _run(CreateDiffTool(tmp_path), {"file": "a.txt", "old_str": "beta\n", "new_str": "BETA\n"})
    assert result.ok, result.error
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "alpha\nBETA\n"
    assert "forgiv" not in str(result.data).lower() and "trailing" not in str(result.data).lower()


def test_the_preview_agrees_with_create_on_a_loose_match(tmp_path: Path) -> None:
    """A preview that says 'not found' for text create would apply sends the model
    off to rewrite a search string that was already right."""
    from thomas.tools.diff import PreviewDiffTool

    (tmp_path / "a.txt").write_text("alpha   \nbeta\n", encoding="utf-8")
    result = _run(PreviewDiffTool(tmp_path), {"file": "a.txt", "old_str": "alpha\nbeta\n", "new_str": "ALPHA\nbeta\n"})
    assert result.ok, result.error
    assert "ALPHA" in str(result.data)
