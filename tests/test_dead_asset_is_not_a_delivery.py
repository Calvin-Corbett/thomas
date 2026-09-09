"""Code that nothing loads has not been delivered."""

from __future__ import annotations

from pathlib import Path

from thomas.forge.anvil.build_verify import _orphaned_web_assets


def test_a_written_script_that_nothing_loads_is_caught(tmp_path: Path) -> None:
    """Asked to give a game a third-person camera, Thomas wrote
    trey-depth-renderer.js -- 8.5KB of real perspective projection, horizon,
    depth sorting and zombie sprites -- and never added a script tag. The page
    kept its single inline script and looked identical. Every check passed,
    because every check asks "does this parse", and dead code parses perfectly.
    """
    (tmp_path / "game.html").write_text("<!doctype html><body><script>const a=1;</script></body>", encoding="utf-8")
    (tmp_path / "renderer.js").write_text("export function render(){}", encoding="utf-8")

    failures = _orphaned_web_assets(tmp_path, ["game.html", "renderer.js"])

    assert failures and "renderer.js" in failures[0]
    assert "nothing loads it" in failures[0]


def test_a_script_tag_makes_it_reachable(tmp_path: Path) -> None:
    (tmp_path / "game.html").write_text(
        '<!doctype html><body><script src="renderer.js"></script></body>', encoding="utf-8")
    (tmp_path / "renderer.js").write_text("export function render(){}", encoding="utf-8")

    assert _orphaned_web_assets(tmp_path, ["game.html", "renderer.js"]) == []


def test_an_import_from_another_script_counts(tmp_path: Path) -> None:
    """Reachability is not only a script tag."""
    (tmp_path / "main.js").write_text("import { render } from './renderer.js';", encoding="utf-8")
    (tmp_path / "renderer.js").write_text("export function render(){}", encoding="utf-8")

    assert _orphaned_web_assets(tmp_path, ["renderer.js"]) == []


def test_a_dynamic_load_counts(tmp_path: Path) -> None:
    """A build step or an unusual loader must not be called a mistake."""
    (tmp_path / "main.js").write_text("new Worker('worker.js');", encoding="utf-8")
    (tmp_path / "worker.js").write_text("self.onmessage=()=>{};", encoding="utf-8")

    assert _orphaned_web_assets(tmp_path, ["worker.js"]) == []


def test_a_file_mentioning_only_itself_is_still_an_orphan(tmp_path: Path) -> None:
    (tmp_path / "lonely.js").write_text("// lonely.js does nothing\nexport const x = 1;", encoding="utf-8")

    assert _orphaned_web_assets(tmp_path, ["lonely.js"])


def test_non_web_files_are_left_alone(tmp_path: Path) -> None:
    """Only web assets are expected to be loaded by something."""
    (tmp_path / "notes.md").write_text("# notes", encoding="utf-8")
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")

    assert _orphaned_web_assets(tmp_path, ["notes.md", "data.json"]) == []


def test_css_is_checked_too(tmp_path: Path) -> None:
    (tmp_path / "page.html").write_text("<!doctype html><body>hi</body>", encoding="utf-8")
    (tmp_path / "theme.css").write_text("body{color:red}", encoding="utf-8")

    assert _orphaned_web_assets(tmp_path, ["theme.css"])
