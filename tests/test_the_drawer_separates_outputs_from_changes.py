"""The drawer's "Outputs" heading covered two different kinds of thing.

Measured on the three-file kanban run, reading down the single labelled column::

    OUTPUTS
      index.html   artifact, with preview
      app.js       change row, Keep/Revert
      index.html   change row, Keep/Revert    <- the same name again
      styles.css   change row, Keep/Revert
    FILES · /
      app.js, index.html, styles.css

The deliverable is almost always ALSO a changed file, so its name rendered twice
under one heading on essentially every run, and the repeat read as a rendering
fault rather than as "the thing you made" and "a file you may revert". The fix
then was a "Changed files" sub-heading between the two groups.

The 2026-10 Build redesign (design 3a) separates them for good: OUTPUTS is the
changed files with Keep / Revert alone (unified_code_drawer.js), and the
deliverable's rows, a file you opened and the project tree fold into one "Files"
section beneath it (unified_code_surface.js). Still never de-duplicated: the
deliverable keeps its Revert row under OUTPUTS, the file you are most likely to
want to undo.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_surface.js"
DRAWER_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_drawer.js"


def _without_comments(text: str) -> str:
    """Strip // comments so a scan cannot read its own documentation."""

    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))


def _surface() -> str:
    return _without_comments(CODE_JS.read_text(encoding="utf-8"))


def test_the_deliverable_sits_in_the_files_fold_not_under_outputs() -> None:
    body = _surface()
    files = re.search(r"const files = `(.*?)`;", body, re.S)
    assert files, "the drawer's Files fold is gone; this guard needs rewriting"
    fold = files.group(1)
    assert "<summary" in fold and ">Files</summary>" in fold
    assert "${preview}" in fold and "${artifactRows}" in fold, "the deliverable is no longer folded under Files"
    # The changed files go to the drawer's OUTPUTS, and nowhere else.
    assert re.search(r"drawerHtml\(\{\s*changes: visibleChanges", body), "the change rows are not handed to OUTPUTS"
    assert 'data-code-keep="' not in body, "the surface draws its own Keep rows again, beside OUTPUTS"


def test_outputs_holds_the_change_rows_under_their_own_label() -> None:
    drawer = _without_comments(DRAWER_JS.read_text(encoding="utf-8"))
    assert re.search(
        r'<div class="tc-agents-label">Outputs</div>\s*<div class="tc-agents-outputs">\$\{outputs\}</div>', drawer
    )
    assert 'data-code-keep="${esc(file)}"' in drawer and 'data-code-revert="${esc(file)}"' in drawer


def test_the_fold_is_declared_after_what_it_holds() -> None:
    """The trap the old heading nearly shipped with: `preview` and `artifactRows`
    are `const`s, and reading one before its declaration is a temporal-dead-zone
    ReferenceError that takes out the whole of Build. The ORDER is pinned."""

    body = _surface()
    files_decl = body.find("const files =")
    for name in ("const preview =", "const artifactRows ="):
        decl = body.find(name)
        assert decl != -1, f"`{name}` is gone; this guard needs rewriting"
        assert files_decl > decl, f"`const files` is declared before `{name}`"
