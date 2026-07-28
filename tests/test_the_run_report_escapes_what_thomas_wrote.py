"""Everything in the run report is untrusted text rendered into the page.

The report carries filenames, tool output, verification evidence and error
messages — all produced by a model or by code it generated, none of it written
by the person reading it. It is built with template strings and assigned via
innerHTML, so an unescaped field is a script tag in the owner's own UI.

Nothing asserted this. It is correct today, and correct-with-no-test is the
state in which a control disappears during an ordinary refactor.

The risk grew concrete on 2026-07-28: the report began carrying the names of
files another code task created. A filename is attacker-influenced in the
weakest sense — the model chooses it — but "the model chooses it" is exactly
the class of input that should never be trusted into markup.
"""

from __future__ import annotations

from pathlib import Path

WEB_JS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js"
# The report and the artifact cards moved to a sibling module when
# unified_code_mode.js was split. The escaper did NOT move and was not copied:
# it is declared once and injected, which the first test below pins by counting
# declarations across both files. Two escapers is how one of them stops
# escaping.
CODE_JS = WEB_JS / "unified_code_mode.js"
CODE_RESULTS_JS = WEB_JS / "unified_code_results.js"


def _js() -> str:
    return CODE_JS.read_text(encoding="utf-8") + "\n" + CODE_RESULTS_JS.read_text(encoding="utf-8")


def test_the_escaper_covers_every_dangerous_character() -> None:
    declarations = [line for line in _js().splitlines() if line.strip().startswith("const esc =")]

    assert len(declarations) == 1, "one escaper, shared by injection -- a second copy is one that can drift"
    line = declarations[0]

    for char in ("&", "<", ">", '"', "'"):
        assert char in line, f"{char!r} is not escaped"
    assert "&amp;" in line and "&lt;" in line and "&gt;" in line
    assert "&quot;" in line and "&#39;" in line


def test_every_report_row_field_is_escaped() -> None:
    """Both halves: the heading and the detail. A filename lands in the detail."""
    body = _js().split("function reportRow", 1)[1].split("\n  function", 1)[0]

    assert "esc(heading)" in body
    assert "esc(label)" in body
    assert "${heading}" not in body, "raw interpolation of untrusted text"
    assert "${label}" not in body


def test_the_section_title_is_escaped_too() -> None:
    body = _js().split("function reportSection", 1)[1].split("\n  function", 1)[0]

    assert "esc(title)" in body


def test_every_filename_reaching_the_dom_is_escaped() -> None:
    """Artifact cards carry names Thomas chose, into attributes and text. The
    card markup was rewritten heavily on 2026-07-28 — thumbnails, an inline
    stage, a download control, edit-mode identities — and each rewrite is a
    chance to interpolate a name raw.

    Audited then: the only bare `${file}` builds a JavaScript key, not markup.
    Every path into the document escapes."""
    body = _js().split("function artifactCardsHtml", 1)[1].split("\n  }\n", 1)[0]

    for attribute in ("data-code-open-artifact", "data-code-save-artifact", "data-code-artifact-slot"):
        assert f'{attribute}="${{esc(' in body, f"{attribute} interpolates a filename unescaped"
    assert 'title="Download ${esc(file)}"' in body
    assert 'src="${esc(doc)}"' in body, "a preview URL is interpolated raw into an attribute"


def test_open_risks_reach_the_page_through_that_row() -> None:
    """Pins the path the new provenance risk travels, so a future report
    section cannot render risk details by some other unescaped route."""
    body = _js().split("function runReportHtml", 1)[1].split("\n  function", 1)[0]

    risks_line = next(line for line in body.splitlines() if "open_risks" in line)
    assert "reportRow(" in risks_line
    assert "item.detail" in risks_line
