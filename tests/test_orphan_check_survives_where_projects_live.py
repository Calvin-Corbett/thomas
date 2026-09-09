"""The orphan check must work for a project stored under a dot-directory.

The filter that skips `.git`, `node_modules` and `.thomas` ran against each
file's ABSOLUTE parts. Thomas keeps every project he makes under `~/.thomas/`,
so `.thomas` matched as an ancestor of every file in every project, the whole
haystack was skipped, and the check reported that nothing loads anything.
Always, for everyone.

It did not fail quietly. Told his script was unreferenced, Thomas added a
script tag; told again, he added a second; the page then ran the file twice and
died on `Identifier 'canvas' has already been declared`, and he spent 25 passes
on it. The duplicate-include check catches that wreckage. This is the cause.

Same defect, same day, as the preview allowlist in `evolve_agent_routes.py` --
see `test_preview_allowlist_ignores_where_the_project_lives`.
"""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil.build_verify import _orphaned_web_assets

_PAGE = '<!doctype html><html><body><canvas></canvas>\n<script src="app.js"></script>\n</body></html>'


def _project(tmp_path: Path) -> Path:
    """A project laid out where Thomas actually puts them."""
    root = tmp_path / ".thomas" / "projects" / "scratch"
    root.mkdir(parents=True)
    (root / "app.js").write_text("const value = 1;", encoding="utf-8")
    (root / "index.html").write_text(_PAGE, encoding="utf-8")
    return root


def test_a_referenced_script_is_not_called_an_orphan(tmp_path) -> None:
    """The false failure that started the whole chain."""
    root = _project(tmp_path)

    assert _orphaned_web_assets(root, ["app.js"]) == []


def test_a_genuine_orphan_is_still_caught(tmp_path) -> None:
    """Fixing the false positive must not blind the check."""
    root = _project(tmp_path)
    (root / "stranded.js").write_text("const stranded = 1;", encoding="utf-8")

    found = _orphaned_web_assets(root, ["stranded.js"])

    assert len(found) == 1
    assert "stranded.js" in found[0]


def test_the_projects_own_metadata_is_still_skipped(tmp_path) -> None:
    """`.thomas` INSIDE the project holds conversation transcripts that quote
    source. A reference found only there is not a page loading the file."""
    root = _project(tmp_path)
    meta = root / ".thomas" / "evolve"
    meta.mkdir(parents=True)
    (meta / "transcript.json").write_text('{"text": "I created stranded.js for you"}', encoding="utf-8")
    (root / "stranded.js").write_text("const stranded = 1;", encoding="utf-8")

    assert _orphaned_web_assets(root, ["stranded.js"]) != [], "a transcript mention is not a page load"


def test_version_control_inside_the_project_is_still_skipped(tmp_path) -> None:
    root = _project(tmp_path)
    git = root / ".git"
    git.mkdir()
    (git / "COMMIT_EDITMSG").write_text("add stranded.js", encoding="utf-8")
    (root / "stranded.js").write_text("const stranded = 1;", encoding="utf-8")

    assert _orphaned_web_assets(root, ["stranded.js"]) != []
