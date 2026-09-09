"""The patch tools accept the patch grammar the model actually writes (2026-09-05).

Counted on today's Build transcripts: 88 calls to ``diff.apply_patch`` and
``diff.preview_patch``, 35 rejected with "no file headers (---/+++) found in
patch" and one with "unexpected line in hunk game.js#3: '*** End Patch'". The
GPT worker writes the Codex apply-patch envelope -- ``*** Begin Patch``,
``*** Update File: path``, ``@@ context``, ``*** End Patch`` -- and the parser
here reads numbered unified diffs only. Every rejection cost a round, and the
Mario Kart run then re-did the same edits as "small exact replacements".

The envelope is converted in front of both tools: each hunk's old lines are
located in the current file, numbered unified hunks are emitted, and a hunk
that cannot be placed is refused by name with the first line that was not
found. Plain unified diffs pass through untouched.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thomas.tools.diff import ApplyPatchTool, PreviewPatchTool
from thomas.tools.diff_codex_format import codex_patch_to_unified, looks_like_codex_patch

GAME = "function render() {\n  draw();\n}\n\nfunction loop() {\n  update();\n  render();\n}\n"

UPDATE = """*** Begin Patch
*** Update File: game.js
@@ function loop() {
   update();
-  render();
+  render();
+  requestAnimationFrame(loop);
 }
*** End Patch
"""


def _run(tool, args):
    return asyncio.run(tool.execute(args))


def test_an_update_in_the_model_grammar_is_applied(tmp_path: Path) -> None:
    (tmp_path / "game.js").write_text(GAME, encoding="utf-8")
    result = _run(ApplyPatchTool(tmp_path), {"patch": UPDATE})
    assert result.ok, result.error
    assert "requestAnimationFrame(loop);" in (tmp_path / "game.js").read_text(encoding="utf-8")
    assert (tmp_path / "game.js").read_text(encoding="utf-8").count("render();") == 1


def test_the_preview_names_hunks_in_the_model_grammar_too(tmp_path: Path) -> None:
    (tmp_path / "game.js").write_text(GAME, encoding="utf-8")
    result = _run(PreviewPatchTool(tmp_path), {"patch": UPDATE})
    assert result.ok, result.error
    assert "game.js#1" in str(result.data)


def test_a_new_file_and_a_deleted_file(tmp_path: Path) -> None:
    (tmp_path / "old.txt").write_text("gone\n", encoding="utf-8")
    patch = "*** Begin Patch\n*** Add File: notes.md\n+# Notes\n+one\n*** Delete File: old.txt\n*** End Patch\n"
    result = _run(ApplyPatchTool(tmp_path), {"patch": patch})
    assert result.ok, result.error
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "# Notes\none\n"
    assert not (tmp_path / "old.txt").exists()


def test_a_hunk_that_cannot_be_placed_is_refused_by_name(tmp_path: Path) -> None:
    (tmp_path / "game.js").write_text(GAME, encoding="utf-8")
    patch = "*** Begin Patch\n*** Update File: game.js\n@@\n-  explode();\n+  boom();\n*** End Patch\n"
    result = _run(ApplyPatchTool(tmp_path), {"patch": patch})
    assert not result.ok
    assert "game.js" in str(result.error) and "explode();" in str(result.error), result.error
    assert (tmp_path / "game.js").read_text(encoding="utf-8") == GAME


def test_a_plain_unified_diff_is_untouched(tmp_path: Path) -> None:
    unified = "--- a/game.js\n+++ b/game.js\n@@ -2,1 +2,1 @@\n-  draw();\n+  paint();\n"
    assert not looks_like_codex_patch(unified)
    assert codex_patch_to_unified(unified, tmp_path) == unified


def test_an_add_followed_by_a_bad_update_leaves_no_empty_file(tmp_path: Path) -> None:
    (tmp_path / "game.js").write_text(GAME, encoding="utf-8")
    patch = (
        "*** Begin Patch\n*** Add File: new.txt\n+hello\n"
        "*** Update File: game.js\n@@\n-  nothere();\n+  here();\n*** End Patch\n"
    )
    result = _run(ApplyPatchTool(tmp_path), {"patch": patch})
    assert not result.ok
    assert not (tmp_path / "new.txt").exists()


def test_the_second_hunk_is_placed_after_the_first(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x\ny\nx\ny\n", encoding="utf-8")
    patch = "*** Begin Patch\n*** Update File: a.txt\n@@\n x\n-y\n+Y1\n@@\n x\n-y\n+Y2\n*** End Patch\n"
    result = _run(ApplyPatchTool(tmp_path), {"patch": patch})
    assert result.ok, result.error
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "x\nY1\nx\nY2\n"


def test_an_empty_hunk_list_means_every_hunk(tmp_path: Path) -> None:
    """Eight calls in one day sent ``hunks: []`` and got "empty hunk selection;
    nothing applied". An empty list is not a selection of nothing; it is no
    selection, and the patch applies whole."""
    (tmp_path / "game.js").write_text(GAME, encoding="utf-8")
    result = _run(ApplyPatchTool(tmp_path), {"patch": UPDATE, "hunks": []})
    assert result.ok, result.error
    assert "requestAnimationFrame(loop);" in (tmp_path / "game.js").read_text(encoding="utf-8")
