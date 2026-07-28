"""A page that loads its code at runtime must still get verified.

Browser smoke only runs on HTML the change touched, plus HTML discovered to
reference a changed asset -- and that discovery read markup. Thomas split a
game's renderer into its own file and loaded it with `createElement('script')`,
which no tag parser can see. Every later edit to that renderer was therefore
verified by nothing at all, and "no owner found" looked exactly like "this file
has no owner".
"""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil.build_verify import _browser_smoke_files

_STATIC = """<!doctype html><html><head><title>s</title>
<script src="renderer.js"></script></head><body><canvas></canvas></body></html>
"""

_DYNAMIC = """<!doctype html><html><head><title>d</title></head><body><canvas></canvas>
<script>
  const node = document.createElement('script');
  node.src = 'renderer.js';
  document.head.appendChild(node);
</script></body></html>
"""

_SHELL = """<!doctype html><html><head><title>shell</title>
<script src="main.js"></script></head><body><canvas></canvas></body></html>
"""

_MAIN_JS = "import('./renderer.js').then((mod) => mod.start());"


def _write(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")


def test_a_statically_linked_owner_is_still_found(tmp_path) -> None:
    _write(tmp_path, {"renderer.js": "export const draw = () => {};", "static-owner.html": _STATIC})

    assert _browser_smoke_files(tmp_path, ["renderer.js"]) == ["static-owner.html"]


def test_a_dynamically_loaded_owner_is_found(tmp_path) -> None:
    """This returned nothing, so the change ran no browser check."""
    _write(tmp_path, {"renderer.js": "export const draw = () => {};", "dynamic-owner.html": _DYNAMIC})

    assert _browser_smoke_files(tmp_path, ["renderer.js"]) == ["dynamic-owner.html"]


def test_an_owner_one_hop_away_through_javascript_is_found(tmp_path) -> None:
    """The usual shape: the page loads a module, and the module loads the
    renderer. Nothing in the HTML names the renderer at all."""
    _write(tmp_path, {"renderer.js": "export const start = () => {};", "main.js": _MAIN_JS, "shell.html": _SHELL})

    assert _browser_smoke_files(tmp_path, ["renderer.js"]) == ["shell.html"]


def test_an_unrelated_page_is_not_dragged_in(tmp_path) -> None:
    """Over-matching costs an extra browser run, which is the safe direction --
    but it should not mean running every page in the project every time."""
    _write(
        tmp_path,
        {
            "renderer.js": "export const draw = () => {};",
            "dynamic-owner.html": _DYNAMIC,
            "unrelated.html": "<!doctype html><html><body><p>nothing to do with it</p></body></html>",
        },
    )

    assert _browser_smoke_files(tmp_path, ["renderer.js"]) == ["dynamic-owner.html"]


def test_text_matching_is_a_last_resort_not_a_supplement(tmp_path) -> None:
    """When an asset already has a real owner it is covered precisely, and
    widening there would pull in every page that names it in a comment."""
    _write(
        tmp_path,
        {
            "renderer.js": "export const draw = () => {};",
            "static-owner.html": _STATIC,
            "docs.html": "<!doctype html><html><body><p>see renderer.js for details</p></body></html>",
        },
    )

    assert _browser_smoke_files(tmp_path, ["renderer.js"]) == ["static-owner.html"]


def test_changed_html_is_still_smoked_directly(tmp_path) -> None:
    _write(tmp_path, {"page.html": "<!doctype html><html><body><p>hi</p></body></html>"})

    assert _browser_smoke_files(tmp_path, ["page.html"]) == ["page.html"]


def test_a_change_with_no_web_assets_smokes_nothing(tmp_path) -> None:
    """Editing a Python file must not start a browser."""
    _write(tmp_path, {"tool.py": "print('hi')", "page.html": "<!doctype html><html><body>x</body></html>"})

    assert _browser_smoke_files(tmp_path, ["tool.py"]) == []
