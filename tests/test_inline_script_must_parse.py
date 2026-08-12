"""A page whose script cannot parse is a blank page, not a delivery."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from thomas.forge.anvil.build_verify import _artifact_preflight_failures

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is required to parse JavaScript")


def _page(tmp_path: Path, name: str, script: str) -> Path:
    path = tmp_path / name
    path.write_text(f"<!doctype html><body><canvas id=c></canvas><script>\n{script}\n</script></body>", encoding="utf-8")
    return path


def test_a_page_whose_inline_script_cannot_parse_is_caught(tmp_path: Path) -> None:
    """Thomas's own failure, reproduced.

    It delivered a 29KB game as one HTML file with a single inline script that
    spliced object-literal syntax into a const declaration list. The browser
    refuses the whole script, so the page is simply blank -- and the run reported
    success. Standalone .js files were already node --check'd; inline scripts,
    which is how every generated game ships, were only scanned for a top-level
    throw. Nothing had ever tried to parse them.
    """
    _page(tmp_path, "game.html",
          "const world={w:2300,h:1500},player={x:450},enemies=[],wave:1,waveLeft:0,boss:false};")

    failures = _artifact_preflight_failures(tmp_path, ["game.html"])

    assert failures, "a page that cannot run was reported as fine"
    assert "does not parse" in failures[0]
    assert "SyntaxError" in failures[0]


def test_the_corrected_page_passes(tmp_path: Path) -> None:
    """The shape Thomas fixed it to -- the fields moved inside the object."""
    _page(tmp_path, "game.html",
          "const world={w:2300,h:1500,wave:1,waveLeft:0,boss:false},player={x:450};\n"
          "requestAnimationFrame(()=>{});")

    assert _artifact_preflight_failures(tmp_path, ["game.html"]) == []


def test_a_broken_standalone_script_is_still_caught(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("const a = ;", encoding="utf-8")

    failures = _artifact_preflight_failures(tmp_path, ["app.js"])

    # A lone unreferenced script is BOTH unparseable and orphaned, and both are
    # worth saying, so do not depend on which is reported first.
    assert any("does not parse" in f for f in failures), failures


def test_modern_syntax_is_not_mistaken_for_an_error(tmp_path: Path) -> None:
    """A false 'your game is broken' would be worse than no opinion."""
    _page(tmp_path, "modern.html",
          "class A { #x = 1; get x(){ return this.#x; } }\n"
          "const f = async () => { for await (const v of []) {} };\n"
          "const g = globalThis?.foo ?? 'ok';")

    assert _artifact_preflight_failures(tmp_path, ["modern.html"]) == []


def test_a_script_with_a_src_is_not_parsed_as_inline(tmp_path: Path) -> None:
    (tmp_path / "linked.html").write_text(
        '<!doctype html><body><script src="app.js"></script></body>', encoding="utf-8")
    (tmp_path / "app.js").write_text("const ok = 1;", encoding="utf-8")

    assert _artifact_preflight_failures(tmp_path, ["linked.html"]) == []
