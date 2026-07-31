"""A helper written beside its importer must not be called dead code.

`orphaned_web_assets` decides a written asset is unreachable when its filename
appears nowhere in the project. To build the text it searches, it walked the
project and skipped **every** changed file -- not just the one being judged.

That is the whole bug. The only evidence that could make a file reachable came
from files this run did NOT touch, so for any two files written in the same pass
where one imports the other, the import was invisible and the imported one could
never be found reachable. A run that splits a renderer out of `main.js` -- the
single most ordinary thing a web build does -- has both files in its changed
list, always.

Measured on a three-file app that works, before the fix::

    index.html   <script type="module" src="main.js"></script>
    main.js      import { draw } from './renderer.js'; draw();
    renderer.js  export function draw() { ... }

    orphaned_web_assets(root, ["index.html", "main.js", "renderer.js"])
      -> ['renderer.js was written but nothing loads it -- no script tag,
          link, import or reference anywhere in the project ...']
    orphaned_web_assets(root, ["renderer.js"])       # main.js left unchanged
      -> []

Same files, same project. The only difference is whether the importer happened
to be touched in the same run, and the answer flipped from correct to wrong.

After the fix both read `[]`, and a file nothing loads is still reported.

Why it mattered: this failure is fatal, not cosmetic. `artifact_preflight_failures`
feeds it to `assert not preflight_failures` inside the verify subprocess, so the
run exits non-zero and the repair loop is handed "nothing loads renderer.js"
about a file imported on the next line of `main.js`. The comment in
`web_preflight.py` records where a false orphan report ends: Thomas adds a script
tag, is told again, adds a second one, the page dies on a redeclared const, and
25 passes are burned.

Why the existing suite stayed green: `test_dead_asset_is_not_a_delivery.py`'s
import case passes `["renderer.js"]` and leaves `main.js` out of the changed
list, and its script-tag case leans on `game.html` -- HTML is never a candidate,
so a page always vouched. Neither arrangement can reach the broken path.
"""

from __future__ import annotations

from pathlib import Path

from thomas.tools.web_preflight import artifact_preflight_failures, orphaned_web_assets

_PAGE = '<!doctype html><html><body><script type="module" src="main.js"></script></body></html>'


def _module_app(root: Path) -> None:
    (root / "index.html").write_text(_PAGE, encoding="utf-8")
    (root / "main.js").write_text("import { draw } from './renderer.js';\ndraw();\n", encoding="utf-8")
    (root / "renderer.js").write_text("export function draw() { return 1; }\n", encoding="utf-8")


def test_a_module_imported_by_another_new_module_is_not_reported_as_dead(tmp_path: Path) -> None:
    _module_app(tmp_path)

    failures = orphaned_web_assets(tmp_path, ["index.html", "main.js", "renderer.js"])

    assert failures == [], (
        "a correct two-module app was told one of its modules is dead code. The "
        "importer was written in the same pass, so it was excluded from the text "
        f"searched for the reference. Got: {failures!r}"
    )


def test_the_same_app_answered_correctly_when_only_one_file_changed(tmp_path: Path) -> None:
    """The control: this arrangement was right before the fix and stays right.

    It is also the arrangement the old import test used, which is why the suite
    never noticed -- leaving `main.js` out of the changed list is the one case
    where excluding the changed files costs nothing.
    """
    _module_app(tmp_path)

    assert orphaned_web_assets(tmp_path, ["renderer.js"]) == []


def test_a_file_nothing_loads_is_still_caught_when_the_whole_app_changed(tmp_path: Path) -> None:
    """The other direction. A fix that just stopped reporting would pass the
    test above and destroy the check."""
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><body><script src="main.js"></script></body></html>', encoding="utf-8"
    )
    (tmp_path / "main.js").write_text("console.log('hello');\n", encoding="utf-8")
    (tmp_path / "renderer.js").write_text("export function draw() { return 1; }\n", encoding="utf-8")

    failures = orphaned_web_assets(tmp_path, ["index.html", "main.js", "renderer.js"])

    assert len(failures) == 1, f"expected exactly the one dead file, got {failures!r}"
    assert "renderer.js" in failures[0]


def test_a_file_that_names_only_itself_is_still_an_orphan_beside_a_live_sibling(tmp_path: Path) -> None:
    """The rule the old line was reaching for, kept intact.

    Excluding the file being judged is what stops a file vouching for itself.
    Excluding its siblings was never needed for that, and is what broke.
    """
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><body><script src="main.js"></script></body></html>', encoding="utf-8"
    )
    (tmp_path / "main.js").write_text("console.log('main.js');\n", encoding="utf-8")
    (tmp_path / "lonely.js").write_text("// lonely.js does nothing\nexport const x = 1;\n", encoding="utf-8")

    failures = orphaned_web_assets(tmp_path, ["main.js", "lonely.js"])

    assert len(failures) == 1, f"expected only lonely.js, got {failures!r}"
    assert "lonely.js" in failures[0]


def test_a_stylesheet_a_new_script_installs_is_not_dead(tmp_path: Path) -> None:
    """Not only imports. A script that builds its own <link> counts too, and it
    is a candidate itself, so it used to be invisible for the same reason."""
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><body><script src="boot.js"></script></body></html>', encoding="utf-8"
    )
    (tmp_path / "boot.js").write_text(
        "const link = document.createElement('link');\nlink.href = 'theme.css';\n"
        "link.rel = 'stylesheet';\ndocument.head.appendChild(link);\n",
        encoding="utf-8",
    )
    (tmp_path / "theme.css").write_text("body{color:red}\n", encoding="utf-8")

    assert orphaned_web_assets(tmp_path, ["index.html", "boot.js", "theme.css"]) == []


def test_the_verifier_gate_no_longer_fails_the_working_module_app(tmp_path: Path) -> None:
    """End to end through the gate that actually stops a run.

    `artifact_preflight_failures` is what the verify subprocess asserts on, so a
    false orphan here is the difference between a delivered app and a run that
    spends its repair budget on correct code.
    """
    _module_app(tmp_path)

    failures = artifact_preflight_failures(tmp_path, ["index.html", "main.js", "renderer.js"])

    assert failures == [], f"the preflight gate failed a working app: {failures!r}"
