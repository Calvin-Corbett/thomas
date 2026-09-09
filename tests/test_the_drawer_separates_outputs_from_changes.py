"""The drawer's "Outputs" heading covered two different kinds of thing.

Measured on the three-file kanban run, reading down the single labelled column::

    OUTPUTS
      index.html   artifact, with preview
      app.js       change row, Keep/Revert
      index.html   change row, Keep/Revert    <- the same name again
      styles.css   change row, Keep/Revert
    FILES · /
      app.js, index.html, styles.css

The deliverable is almost always ALSO a changed file, so its name renders twice
under one heading on essentially every run. Scanning the column, the repeat
reads as a rendering fault rather than as "the thing you made" and "a file you
may revert". The section below it (`Files · /`) has its own title and the
preview above it is visually distinct -- the change rows were the only group
without a label, the same "every sibling but one" shape as `project_delta_since`
and `--c-danger`.

Labelled rather than de-duplicated on purpose: dropping the second row would
remove the only Revert control for the deliverable, which is the file you are
most likely to want to undo.

Verified both ways at 1920x1080. Section titles across the drawer go from
``['Outputs', 'Files · /']`` to ``['Outputs', 'Changed files', 'Files · /']``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_mode.js"


def _source() -> str:
    return CODE_JS.read_text(encoding="utf-8")


def _without_comments(text: str) -> str:
    """Strip // comments so a scan cannot read its own documentation.

    This change is documented directly above itself and the prose quotes both
    the variable name and the heading text; three earlier CSS guards in this
    suite passed against deleted fixes for exactly that reason.
    """

    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("//")
    )


def test_the_change_rows_carry_their_own_heading() -> None:
    body = _without_comments(_source())
    assert "changesTitle" in body, (
        "the drawer no longer builds a heading for the changed-files group, so "
        "the deliverable and the Keep/Revert rows share one 'Outputs' label and "
        "the deliverable's filename appears twice with nothing distinguishing them"
    )
    # re.S: the declaration wraps across two lines. Without it this failed with
    # the code plainly correct -- the same brittleness that made the CSP guards
    # go red when their directive outgrew one line.
    assert re.search(r"changesTitle\s*=.*tc-code-section-title.*Changed files", body, re.S), (
        "the changed-files heading is gone or no longer uses "
        "`tc-code-section-title`, so it will not match the styling of 'Outputs' "
        "and 'Files · /' beside it"
    )


def test_the_heading_renders_immediately_before_the_change_rows() -> None:
    """A title built but never interpolated is a silent no-op."""

    body = _without_comments(_source())
    assert "${changesTitle}${changeRows" in body, (
        "`changesTitle` is not rendered directly before `changeRows`; either it "
        "is never interpolated (built and dropped) or something now sits between "
        "the heading and the rows it labels"
    )


def test_it_is_declared_after_preview() -> None:
    """The trap this nearly shipped with.

    `changesTitle` reads `preview`, which is a `const` declared much further
    down the same function. Placing the declaration above it is a temporal-dead-
    zone ReferenceError that takes out the whole of Code mode -- the same class
    of break as closing a template literal early. Zero page errors is the only
    acceptable state, so the ORDER is pinned, not just the presence.
    """

    body = _without_comments(_source())
    preview_decl = body.find("const preview =")
    changes_decl = body.find("const changesTitle")
    assert preview_decl != -1, "`const preview =` is gone; this guard needs rewriting"
    assert changes_decl != -1, "`const changesTitle` is gone"
    assert changes_decl > preview_decl, (
        "`changesTitle` is declared BEFORE `const preview`, so evaluating it "
        "throws a temporal-dead-zone ReferenceError and Code mode renders "
        "nothing at all"
    )


def test_the_heading_is_suppressed_when_there_is_nothing_above_it() -> None:
    """No preview and no artifacts means one group, and no separator is wanted.

    Without the guard, a run with only changed files would show 'Changed files'
    stacked directly beneath 'Outputs', two headings separating nothing.
    """

    body = _without_comments(_source())
    assert re.search(
        r"changesTitle\s*=\s*\(\s*preview\s*\|\|\s*artifactRows\s*\)\s*&&\s*changeRows", body, re.S
    ), (
        "the changed-files heading is no longer gated on something preceding it, "
        "so a changes-only run shows two headings in a row with nothing between them"
    )
