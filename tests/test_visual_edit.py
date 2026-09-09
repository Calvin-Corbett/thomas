"""Hermetic tests for visual click-to-edit -> source diffs (CAP-113).

These tests build a small fixture project (CSS + tokens + markup) in a temp
dir, then prove the acceptance line: a visual color edit becomes a source diff
changing the right file:line from->to; a text edit becomes a source diff; an
edit to an unmapped element is reported (not silently applied); multiple edits
produce one coherent reviewable diff set; determinism. A final test injects a
hermetic fake index to prove the element->source index is injectable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools.visual_edit import (
    PROP_COLOR,
    PROP_SIZE,
    PROP_TEXT,
    Declaration,
    DictElementIndex,
    ElementLocation,
    ProjectElementIndex,
    VisualEdit,
    convert_edit,
    convert_edits,
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A minimal fixture: a token file, a component stylesheet, and markup."""
    styles = tmp_path / "styles"
    styles.mkdir()

    # Design tokens as CSS custom properties.
    (styles / "tokens.css").write_text(
        "\n".join(
            [
                ":root {",
                "  --btn-color: #ff0000;",
                "  --btn-padding: 8px;",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # A component stylesheet with concrete rules.
    (styles / "button.css").write_text(
        "\n".join(
            [
                ".btn {",
                "  color: #123456;",
                "  width: 120px;",
                "  padding: 4px;",
                "}",
                "",
                ".card {",
                "  background: #ffffff;",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # Markup with an id-tagged element carrying text content.
    (tmp_path / "index.html").write_text(
        "\n".join(
            [
                "<html>",
                "  <body>",
                '    <button id="save">Save</button>',
                "  </body>",
                "</html>",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Acceptance: a visual COLOR edit becomes a source diff at the right file:line
# ---------------------------------------------------------------------------


def test_color_edit_becomes_source_diff_at_right_line(project: Path) -> None:
    index = ProjectElementIndex(project)
    edit = VisualEdit(element=".btn", prop=PROP_COLOR, from_value="#123456", to_value="#abcdef")
    result = convert_edit(edit, index)

    assert result.mapped is True
    assert result.file == "styles/button.css"
    # ".btn { color: ... }" -> color is on line 2 of button.css.
    assert result.line == 2
    assert result.location == "styles/button.css:2"
    assert "#123456" in result.before
    assert "#abcdef" in result.after
    assert "#123456" not in result.after

    diff_set = convert_edits([edit], index)
    diff_text = diff_set.unified_text()
    assert "-  color: #123456;" in diff_text
    assert "+  color: #abcdef;" in diff_text
    assert "a/styles/button.css" in diff_text
    assert "b/styles/button.css" in diff_text


def test_color_token_edit_maps_to_token_file(project: Path) -> None:
    index = ProjectElementIndex(project)
    edit = VisualEdit(element="--btn-color", prop=PROP_COLOR, from_value="#ff0000", to_value="#00ff00")
    result = convert_edit(edit, index)

    assert result.mapped is True
    assert result.location == "styles/tokens.css:2"
    diff = convert_edits([edit], index).unified_text()
    assert "-  --btn-color: #ff0000;" in diff
    assert "+  --btn-color: #00ff00;" in diff


# ---------------------------------------------------------------------------
# Acceptance: a TEXT edit becomes a source diff
# ---------------------------------------------------------------------------


def test_text_edit_becomes_source_diff(project: Path) -> None:
    index = ProjectElementIndex(project)
    edit = VisualEdit(element="save", prop=PROP_TEXT, from_value="Save", to_value="Store")
    result = convert_edit(edit, index)

    assert result.mapped is True
    assert result.file == "index.html"
    assert result.line == 3
    diff = convert_edits([edit], index).unified_text()
    assert ">Save<" in diff.replace("\n", "")  # the old line is present
    assert '+    <button id="save">Store</button>' in diff


def test_size_edit_disambiguates_by_category(project: Path) -> None:
    index = ProjectElementIndex(project)
    edit = VisualEdit(element=".btn", prop=PROP_SIZE, from_value="120px", to_value="160px")
    result = convert_edit(edit, index)
    assert result.mapped is True
    assert result.location == "styles/button.css:3"
    diff = convert_edits([edit], index).unified_text()
    assert "+  width: 160px;" in diff


# ---------------------------------------------------------------------------
# Acceptance: an edit to an unmapped element is REPORTED, not applied
# ---------------------------------------------------------------------------


def test_unmapped_element_is_reported_not_applied(project: Path) -> None:
    index = ProjectElementIndex(project)
    edit = VisualEdit(element=".does-not-exist", prop=PROP_COLOR, from_value="#000", to_value="#fff")
    diff_set = convert_edits([edit], index)

    assert diff_set.file_diffs == []  # nothing applied
    assert len(diff_set.unmapped) == 1
    reported = diff_set.unmapped[0]
    assert reported.mapped is False
    assert reported.reason is not None
    assert "not mapped" in reported.reason
    assert reported.location is None


def test_value_mismatch_is_reported_not_applied(project: Path) -> None:
    index = ProjectElementIndex(project)
    # Element exists, but the "from" value does not match the source.
    edit = VisualEdit(element=".btn", prop=PROP_COLOR, from_value="#999999", to_value="#000000")
    diff_set = convert_edits([edit], index)
    assert diff_set.file_diffs == []
    assert len(diff_set.unmapped) == 1
    assert "#999999" in diff_set.unmapped[0].reason


def test_text_mismatch_is_reported(project: Path) -> None:
    index = ProjectElementIndex(project)
    edit = VisualEdit(element="save", prop=PROP_TEXT, from_value="Submit", to_value="Go")
    result = convert_edit(edit, index)
    assert result.mapped is False
    assert "text mismatch" in result.reason


# ---------------------------------------------------------------------------
# Acceptance: multiple edits produce ONE coherent reviewable diff set
# ---------------------------------------------------------------------------


def test_multiple_edits_one_coherent_diff_set(project: Path) -> None:
    index = ProjectElementIndex(project)
    edits = [
        VisualEdit(element=".btn", prop=PROP_COLOR, from_value="#123456", to_value="#0a0a0a"),
        VisualEdit(element=".btn", prop=PROP_SIZE, from_value="120px", to_value="200px"),
        VisualEdit(element=".card", prop=PROP_COLOR, from_value="#ffffff", to_value="#eeeeee"),
        VisualEdit(element="save", prop=PROP_TEXT, from_value="Save", to_value="Store"),
        VisualEdit(element=".ghost", prop=PROP_COLOR, from_value="#111", to_value="#222"),
    ]
    diff_set = convert_edits(edits, index)

    # Four edits mapped, one (.ghost) reported.
    assert len(diff_set.mapped) == 4
    assert len(diff_set.unmapped) == 1

    # Two edits on button.css collapse into ONE file diff (coherent).
    files = [fd.file for fd in diff_set.file_diffs]
    assert files == sorted(files)  # deterministic path order
    assert files.count("styles/button.css") == 1
    button_diff = next(fd for fd in diff_set.file_diffs if fd.file == "styles/button.css")
    # .btn color (2), .btn width (3), and .card background (8) all land in one file.
    assert button_diff.changed_lines == (2, 3, 8)
    assert "+  color: #0a0a0a;" in button_diff.diff_text
    assert "+  width: 200px;" in button_diff.diff_text
    assert "+  background: #eeeeee;" in button_diff.diff_text

    # Two distinct files touched: button.css, index.html.
    assert set(files) == {"styles/button.css", "index.html"}


def test_determinism(project: Path) -> None:
    index = ProjectElementIndex(project)
    edits = [
        VisualEdit(element=".btn", prop=PROP_COLOR, from_value="#123456", to_value="#0a0a0a"),
        VisualEdit(element=".card", prop=PROP_COLOR, from_value="#ffffff", to_value="#eeeeee"),
        VisualEdit(element="save", prop=PROP_TEXT, from_value="Save", to_value="Store"),
    ]
    first = convert_edits(edits, ProjectElementIndex(project)).unified_text()
    second = convert_edits(edits, ProjectElementIndex(project)).unified_text()
    third = convert_edits(list(reversed(edits)), index).unified_text()
    assert first == second
    # Same set of edits in a different order yields the same final diff text.
    assert first == third


# ---------------------------------------------------------------------------
# The element->source index is injectable: prove with a hermetic fake
# ---------------------------------------------------------------------------


def test_injectable_fake_index() -> None:
    source = "\n".join([".hero {", "  color: rebeccapurple;", "}"]) + "\n"
    fake = DictElementIndex(
        locations={
            ".hero": ElementLocation(
                element=".hero",
                file="fake.css",
                declarations=(Declaration(property="color", value="rebeccapurple", line=2),),
            )
        },
        sources={"fake.css": source},
    )
    edit = VisualEdit(element=".hero", prop=PROP_COLOR, from_value="rebeccapurple", to_value="teal")
    result = convert_edit(edit, fake)
    assert result.mapped is True
    assert result.location == "fake.css:2"
    diff = convert_edits([edit], fake).unified_text()
    assert "-  color: rebeccapurple;" in diff
    assert "+  color: teal;" in diff
