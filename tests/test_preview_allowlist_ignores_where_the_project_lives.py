"""The allowlist must describe the project, not where the project happens to sit.

The filter that skips `.git`, `node_modules` and `.thomas` ran against each
file's ABSOLUTE parts. Thomas keeps projects in `~/.thomas/projects/<name>`, so
`.thomas` was an ancestor of every file in every project and the allowlist came
out empty -- every time, for everyone.

That did not fail loudly. The caller fell back to an allowlist of just the one
requested file, so the entry page loaded and nothing it referenced did
(`trey-depth-renderer.js` kept 404ing), and because the allowlist then differed
per file, each file minted a separate origin and destroyed the one before it --
opening the game blanked the thumbnail that was showing the shell page.
"""

from __future__ import annotations

import re
from pathlib import Path

ROUTES = Path(__file__).resolve().parent.parent / "thomas" / "server" / "routes" / "evolve_agent_routes.py"


def _preview_body() -> str:
    text = ROUTES.read_text(encoding="utf-8")
    return text.split("async def conversation_preview", 1)[1].split("\n    async def ", 1)[0]


def test_the_hidden_directory_filter_runs_on_the_relative_path() -> None:
    body = _preview_body()
    guard = next(line for line in body.splitlines() if ".thomas" in line and "part in" in line)

    assert "rel.parts" in guard, "an absolute path carries the project's own location"
    assert "path.parts" not in guard


def test_a_project_under_a_dot_directory_still_lists_its_files(tmp_path) -> None:
    """The condition, evaluated the way the route evaluates it, against the real
    layout that broke: a project inside `.thomas`."""
    root = tmp_path / ".thomas" / "projects" / "code_scratch"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<p>shell</p>", encoding="utf-8")
    (root / "trey-depth-renderer.js").write_text("export const x = 1;", encoding="utf-8")
    (root / "assets" / "tile.png").write_bytes(b"\x89PNG")
    (root / ".git").mkdir()
    (root / ".git" / "config.json").write_text("{}", encoding="utf-8")

    allowed = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file()
        and not any(part in {".git", "node_modules", ".thomas"} for part in p.relative_to(root).parts)
    }

    assert allowed == {"index.html", "trey-depth-renderer.js", "assets/tile.png"}


def test_version_control_inside_the_project_is_still_excluded() -> None:
    """Fixing the location bug must not start serving the project's git objects."""
    body = _preview_body()

    assert ".git" in body and "node_modules" in body


def test_an_empty_allowlist_is_an_error_not_a_one_file_fallback() -> None:
    """`allowed or {tail}` is what let the empty allowlist look like a working
    preview. An unpreviewable project must say so."""
    body = _preview_body()

    assert not re.search(r"allowed\s+or\s+\{", body)
    assert "nothing to preview" in body


def test_the_route_requires_api_access() -> None:
    """It mints a real origin over the owner's project directory. Anything that
    can call it can start a server on their files."""
    body = _preview_body()

    assert "require_api_access(request)" in body
    # Before the route touches any request input, not merely somewhere in it.
    assert body.index("require_api_access(request)") < body.index("request.match_info")
    assert body.index("require_api_access(request)") < body.index("request.query")


def test_a_traversal_in_the_requested_path_is_refused() -> None:
    body = _preview_body()

    assert '".." in tail.split("/")' in body


def test_the_resolved_target_must_stay_inside_the_project() -> None:
    """The `..` check alone is not enough — a symlink or an absolute path would
    pass it. The resolved path is compared against the project root."""
    body = _preview_body()

    assert "is_relative_to(root.resolve())" in body


def test_the_allowlist_does_not_depend_on_which_file_was_requested() -> None:
    """Two files of one project must produce the same allowlist, or the service
    treats them as different apps and gives each its own short-lived origin."""
    body = _preview_body()
    allowlist = body.split("allowed = set()", 1)[1].split("if not allowed", 1)[0]

    assert "tail" not in allowlist, "the allowlist must describe the project, not the request"
