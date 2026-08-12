"""A page that loads the same script twice runs it twice.

Thomas was asked for a starfield. He wrote a clean one and then included
`starfield.js` twice -- once with `defer` in the head, once at the end of the
body. The file executed twice, so its first `const` was declared twice, and the
page died on `Identifier 'canvas' has already been declared`.

Both files were individually perfect. `node --check` passes each, because
neither is wrong; only the pair is. The browser caught it, but the message names
the SCRIPT while the fault is in the HTML -- so the repair loop spent its whole
budget rewriting the JavaScript. 61 checks, six issues, no convergence, because
the error pointed at the wrong file.
"""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil.build_verify import _artifact_preflight_failures, _duplicate_script_includes

_TWICE = """<!doctype html><html><head>
<script src="starfield.js" defer></script>
</head><body>
<canvas id="starfield"></canvas>
<script src="starfield.js"></script>
</body></html>
"""

_ONCE = """<!doctype html><html><head></head><body>
<canvas id="starfield"></canvas>
<script src="starfield.js"></script>
</body></html>
"""


def _project(tmp_path: Path, page: str, name: str = "starfield.html") -> Path:
    (tmp_path / "starfield.js").write_text('const canvas = document.querySelector("#starfield");', encoding="utf-8")
    (tmp_path / name).write_text(page, encoding="utf-8")
    return tmp_path


def test_the_same_script_included_twice_is_reported(tmp_path) -> None:
    root = _project(tmp_path, _TWICE)

    found = _duplicate_script_includes(root, ["starfield.html"])

    assert len(found) == 1
    assert "starfield.js" in found[0]


def test_the_message_names_the_page_to_fix_not_the_script(tmp_path) -> None:
    """The whole failure was the repair loop editing the file the browser named.
    The page is what has to change."""
    root = _project(tmp_path, _TWICE)

    message = _duplicate_script_includes(root, ["starfield.html"])[0]

    assert "starfield.html" in message
    assert "duplicate script tag in starfield.html" in message.lower()


def test_the_message_does_not_overclaim_the_consequence(tmp_path) -> None:
    """Running twice is certain. The SyntaxError follows only if the file
    declares something at top level -- a file of function declarations or an
    IIFE runs twice without erroring. Asserting the error outright happened to
    be true for starfield.js and would send the next reader hunting for an
    error that is not there."""
    root = _project(tmp_path, _TWICE)

    message = _duplicate_script_includes(root, ["starfield.html"])[0]

    assert "runs 2 times" in message
    assert "any top-level const, let or class" in message


def test_a_page_that_loads_it_once_is_fine(tmp_path) -> None:
    root = _project(tmp_path, _ONCE)

    assert _duplicate_script_includes(root, ["starfield.html"]) == []


def test_the_same_file_reached_by_two_different_paths_still_counts(tmp_path) -> None:
    """`./starfield.js` and `starfield.js` are one file. Comparing the written
    text rather than the resolved path would miss it."""
    page = """<!doctype html><html><body>
<script src="./starfield.js"></script>
<script src="starfield.js"></script>
</body></html>
"""
    root = _project(tmp_path, page)

    assert len(_duplicate_script_includes(root, ["starfield.html"])) == 1


def test_a_remote_script_listed_twice_is_left_alone(tmp_path) -> None:
    """A CDN repeated may be a deliberate fallback, and it is not ours to fix."""
    page = """<!doctype html><html><body>
<script src="https://cdn.example.com/lib.js"></script>
<script src="https://cdn.example.com/lib.js"></script>
</body></html>
"""
    root = _project(tmp_path, page)

    assert _duplicate_script_includes(root, ["starfield.html"]) == []


def test_two_different_local_scripts_are_fine(tmp_path) -> None:
    page = """<!doctype html><html><body>
<script src="starfield.js"></script>
<script src="other.js"></script>
</body></html>
"""
    root = _project(tmp_path, page)
    (root / "other.js").write_text("const other = 1;", encoding="utf-8")

    assert _duplicate_script_includes(root, ["starfield.html"]) == []


def test_a_parse_error_quotes_the_offending_source(tmp_path) -> None:
    """A line number alone is not actionable. For an inline script it counts
    from the start of the extracted block, so it matches no line of the HTML
    the reader opens -- and a parser blames where it gave up, not where the
    mistake is. The quoted source is greppable however it is numbered."""
    from thomas.forge.anvil.build_verify import _javascript_syntax_error

    error = _javascript_syntax_error("const ok = 1;\nfunction ( { broken\n")

    assert "Error" in error
    assert "parser stopped at:" in error
    assert "the mistake may be earlier" in error


def test_editing_only_the_script_still_checks_the_page_that_owns_it(tmp_path) -> None:
    """The realistic case. The page is written once and thereafter only the
    script is touched, so a duplicate include sits in a file no later run
    changes -- and a check that looks only at changed pages never sees it."""
    root = _project(tmp_path, _TWICE)

    failures = _artifact_preflight_failures(root, ["starfield.js"])

    assert any("loads starfield.js 2 times" in item for item in failures)


def test_it_runs_as_part_of_preflight(tmp_path) -> None:
    """Wired in, not merely written: preflight is what fails the build."""
    root = _project(tmp_path, _TWICE)

    failures = _artifact_preflight_failures(root, ["starfield.html"])

    assert any("loads starfield.js 2 times" in item for item in failures)
