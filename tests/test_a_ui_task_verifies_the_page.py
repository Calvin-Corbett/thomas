"""The task type for building a UI had no UI check.

`design-ui` maps to verification family `ui`, and `DEFAULT_CHECKERS` had an
entry for `code` and nothing else, so every `ui` task fell through to the
structural check -- which passes as soon as one file exists in the workspace.
A page whose only script is a syntax error passed. A stylesheet nothing links
passed. A script included twice, so the page dies on a redeclared const,
passed.

The checks that catch all three had existed for months in
`thomas/forge/anvil/build_verify.py`, where only the Forge/Code path could
reach them: `marketplace` may not import `forge`. They now live in
`thomas/tools/web_preflight.py`, which both layers already depend on.

Every test here is written in both directions -- the broken workspace fails AND
the working one still passes -- because a checker that fails everything would
satisfy a one-directional test and be worse than no checker at all.
"""

from __future__ import annotations

import shutil

import pytest

from thomas.marketplace.orchestrator.verification import (
    _generic_checker,
    run_web_preflight,
    verify_deliverable,
)

_HAS_NODE = shutil.which("node") is not None

_WORKING_PAGE = """<!doctype html>
<html><head><link rel="stylesheet" href="style.css"></head>
<body><canvas id="c"></canvas><script src="game.js"></script></body></html>
"""


def _write_working_app(root) -> None:
    (root / "index.html").write_text(_WORKING_PAGE, encoding="utf-8")
    (root / "game.js").write_text("const canvas = document.getElementById('c');\n", encoding="utf-8")
    (root / "style.css").write_text("canvas { width: 100%; }\n", encoding="utf-8")


def test_a_working_page_passes_and_says_which_check_ran(tmp_path) -> None:
    _write_working_app(tmp_path)

    result = verify_deliverable("design-ui", str(tmp_path), "built the game")

    assert result.passed
    assert result.family == "ui"
    assert result.checks == ("web_preflight",)
    assert "3 file(s)" in result.evidence


@pytest.mark.skipif(not _HAS_NODE, reason="needs a real node on PATH to parse JavaScript")
def test_a_page_whose_script_cannot_parse_fails(tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><body><script>const a={},b={},wave:1,};</script></body></html>",
        encoding="utf-8",
    )

    result = verify_deliverable("design-ui", str(tmp_path), "built the game")

    assert not result.passed
    assert result.checks == ("web_preflight",)
    assert "does not parse" in result.evidence


@pytest.mark.skipif(not _HAS_NODE, reason="needs a real node on PATH to parse JavaScript")
def test_the_structural_check_alone_would_have_passed_that_page(tmp_path) -> None:
    """The old behaviour, asserted rather than described: this is exactly the
    workspace the `ui` family used to be verified with, and it passes."""
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><body><script>const a={},b={},wave:1,};</script></body></html>",
        encoding="utf-8",
    )

    assert _generic_checker(str(tmp_path), "built the game").passed


def test_an_asset_nothing_loads_fails(tmp_path) -> None:
    """No node needed: this one is pure reachability."""
    (tmp_path / "index.html").write_text("<!doctype html><html><body>hi</body></html>", encoding="utf-8")
    (tmp_path / "renderer.js").write_text("const depth = 1;\n", encoding="utf-8")

    result = verify_deliverable("design-ui", str(tmp_path), "added a renderer")

    assert not result.passed
    assert "renderer.js was written but nothing loads it" in result.evidence


def test_a_script_included_twice_fails(tmp_path) -> None:
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><head><script defer src="star.js"></script></head>'
        '<body><script src="star.js"></script></body></html>',
        encoding="utf-8",
    )
    (tmp_path / "star.js").write_text("const canvas = 1;\n", encoding="utf-8")

    result = verify_deliverable("design-ui", str(tmp_path), "starfield")

    assert not result.passed
    assert "loads star.js 2 times" in result.evidence


def test_a_ui_task_that_delivered_prose_still_gets_the_structural_check(tmp_path) -> None:
    """A `ui` task can legitimately hand back a written spec. Failing those
    would swap the old false positive for a new false negative."""
    (tmp_path / "design-notes.md").write_text("# layout\n\n- sidebar left\n", encoding="utf-8")

    result = verify_deliverable("design-ui", str(tmp_path), "wrote the spec")

    assert result.passed
    assert result.family == "ui"
    assert result.checks == ("files_present",)


def test_an_empty_ui_workspace_with_no_answer_still_fails(tmp_path) -> None:
    result = verify_deliverable("design-ui", str(tmp_path), "")

    assert not result.passed
    assert result.family == "ui"


def test_other_families_are_untouched_by_the_new_checker(tmp_path) -> None:
    """The page is broken in a way `ui` now rejects; `research` must not care."""
    (tmp_path / "index.html").write_text("<!doctype html><html><body>hi</body></html>", encoding="utf-8")
    (tmp_path / "renderer.js").write_text("const depth = 1;\n", encoding="utf-8")

    assert verify_deliverable("research-topic", str(tmp_path), "read it").passed
    assert not verify_deliverable("design-ui", str(tmp_path), "read it").passed


def test_a_workspace_under_a_dotted_root_is_still_inspected(tmp_path) -> None:
    """Thomas keeps every workspace under ~/.thomas. Four scanners have now
    filtered on absolute path parts and silently seen nothing at all."""
    root = tmp_path / ".thomas" / "runtime" / "work"
    root.mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><html><body>hi</body></html>", encoding="utf-8")
    (root / "renderer.js").write_text("const depth = 1;\n", encoding="utf-8")

    result = run_web_preflight(str(root))

    assert not result.passed, "the dotted root must not hide the workspace"


def test_vendored_trees_are_not_verified(tmp_path) -> None:
    """node_modules is someone else's code and would drag thousands of files
    through `node --check` on every verification."""
    _write_working_app(tmp_path)
    vendor = tmp_path / "node_modules" / "left-pad"
    vendor.mkdir(parents=True)
    (vendor / "index.js").write_text("module.exports = 1;\n", encoding="utf-8")

    result = run_web_preflight(str(tmp_path))

    assert result.passed
    assert "left-pad" not in result.evidence
    assert "3 file(s)" in result.evidence


def test_the_forge_path_runs_the_very_same_preflight() -> None:
    """The hoist has to leave one implementation, not two that drift. The old
    private names in build_verify are aliases, which is what keeps the ten test
    modules importing them from there working unchanged."""
    from thomas.forge.anvil import build_verify
    from thomas.tools import web_preflight

    assert build_verify._artifact_preflight_failures is web_preflight.artifact_preflight_failures
    assert build_verify._orphaned_web_assets is web_preflight.orphaned_web_assets
    assert build_verify._duplicate_script_includes is web_preflight.duplicate_script_includes
    assert build_verify._javascript_syntax_error is web_preflight.javascript_syntax_error
    assert build_verify._has_obvious_top_level_throw is web_preflight.has_obvious_top_level_throw
    assert build_verify._mask_js_strings_and_comments is web_preflight.mask_js_strings_and_comments
    assert build_verify._browser_smoke_files is web_preflight.browser_smoke_files
    assert build_verify._owners_by_mention is web_preflight.owners_by_mention
    assert build_verify._LocalAssetReferenceParser is web_preflight.LocalAssetReferenceParser


def test_the_shared_module_pulls_in_no_project_code() -> None:
    """It sits in `tools` so `marketplace` and `forge` can both call it without
    either importing the other. An import of a project module here would be the
    coupling the move exists to avoid."""
    import ast
    from pathlib import Path

    source = Path(web_preflight_path()).read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    assert not [name for name in imported if name.split(".")[0] == "thomas"], imported


def web_preflight_path() -> str:
    from thomas.tools import web_preflight

    return str(web_preflight.__file__)
