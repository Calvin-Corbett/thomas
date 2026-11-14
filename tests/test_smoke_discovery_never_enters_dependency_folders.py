"""Smoke discovery never walks dependency, cache or VCS folders.

Browser smoke finds the pages that load a changed asset by reading every HTML
file under the project. That read used to ``rglob`` the whole tree, including
.venv, .git, node_modules and .thomas. On 2026-10-31 one such discovery on the
Thomas checkout took ten minutes and failed every timeout the suite allows, and
a user's project with a large node_modules would pay the same on every web
check. The walk now prunes the folders ``ORPHAN_SCAN_PRUNED_DIRS`` already
names, so a page in a normal folder is still found and a page vendored inside
node_modules is not.
"""

from __future__ import annotations

from pathlib import Path

from thomas.tools.web_preflight import ORPHAN_SCAN_PRUNED_DIRS, browser_smoke_files, project_pages

_PAGE = '<html><head><script src="/shared/app.js"></script></head><body>x</body></html>'


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_page_in_a_normal_folder_is_found_and_one_in_node_modules_is_not(tmp_path: Path) -> None:
    _write(tmp_path, "shared/app.js", "console.log('changed');")
    _write(tmp_path, "site/index.html", _PAGE)
    _write(tmp_path, "node_modules/some-dep/demo/index.html", _PAGE)
    _write(tmp_path, ".venv/lib/site-packages/pkg/doc.html", _PAGE)
    _write(tmp_path, ".git/hooks/readme.html", _PAGE)
    picked = browser_smoke_files(tmp_path, ["shared/app.js"])
    assert picked == ["site/index.html"], picked


def test_a_script_in_node_modules_cannot_name_a_page_as_an_owner(tmp_path: Path) -> None:
    # The text-mention fallback walks scripts too. A vendored script that
    # happens to name the asset must not drag the page that loads it in.
    _write(tmp_path, "lib/renderer.js", "export const start = () => {};")
    _write(tmp_path, "node_modules/dep/index.js", "// mentions renderer.js")
    _write(tmp_path, "vendor.html", '<html><head><script src="node_modules/dep/index.js"></script></head></html>')
    picked = browser_smoke_files(tmp_path, ["lib/renderer.js"])
    assert picked == [], picked


def test_project_pages_prunes_every_named_folder_and_keeps_the_rest(tmp_path: Path) -> None:
    for folder in ORPHAN_SCAN_PRUNED_DIRS:
        _write(tmp_path, f"{folder}/inner/page.html", _PAGE)
    _write(tmp_path, "docs/guide.htm", _PAGE)
    _write(tmp_path, "app/Index.HTML", _PAGE)
    found = {path.relative_to(tmp_path).as_posix() for path in project_pages(tmp_path)}
    assert found == {"docs/guide.htm", "app/Index.HTML"}, found
