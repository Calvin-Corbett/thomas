"""An agent has to be able to open the file it just wrote -- and nothing else.

Measured 2026-09-20 by driving the UI. Asked for a clock page, the worker wrote
a good `index.html` in about a minute, then spent **eleven more minutes and
~390 MB** unable to look at it. `browser.open` on
`file:///C:/Users/.../workspaces/exec-.../index.html` came back
`{"ok": false, "error": "Only http(s) URLs may be fetched."}`, so it shelled out
to `npx playwright install chromium` twice -- downloading a browser the tool
already had five builds of -- and stood up its own `python -m http.server` to
get an http URL for a file already on its own disk.

The obvious fix is wrong. `check_url` is the SSRF guard shared by `web.fetch`
and `eng.web_extract`; allowing `file://` there would let any agent read any
local file and put it on a page. The hostile-agent assumption says do not, and
the owner's standing direction on the browser (2026-08-25) is "no weakening
these to make something easier".

So the allowance is the narrowest thing that solves it: a `file://` URL is
permitted only when the resolved real path is inside that task's own workspace,
and only when a workspace was configured at all. `resolve()` follows symlinks
BEFORE the comparison, which is what makes the escape tests below meaningful --
a link planted inside the workspace pointing at an SSH key is the attack this
has to refuse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools.browser_page import workspace_file_url


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "exec-1234"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    return ws


def _url(path: Path) -> str:
    return path.resolve().as_uri()


def test_an_agent_may_open_a_file_in_its_own_workspace(workspace: Path) -> None:
    allowed = workspace_file_url(_url(workspace / "index.html"), workspace)
    assert allowed is not None
    assert allowed.name == "index.html"


def test_a_file_outside_the_workspace_is_refused(tmp_path: Path, workspace: Path) -> None:
    secret = tmp_path / "id_rsa"
    secret.write_text("SYNTHETIC TEST KEY", encoding="utf-8")
    assert workspace_file_url(_url(secret), workspace) is None


def test_a_symlink_out_of_the_workspace_is_refused(tmp_path: Path, workspace: Path) -> None:
    """The real attack: a link planted inside the workspace, pointing out.

    Refused because the path is resolved through symlinks BEFORE it is compared,
    not after.
    """
    secret = tmp_path / "id_rsa"
    secret.write_text("SYNTHETIC TEST KEY", encoding="utf-8")
    link = workspace / "innocent.html"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):  # Windows without developer mode
        pytest.skip("symlinks not permitted in this environment")
    assert workspace_file_url(_url(link), workspace) is None


def test_a_traversal_path_is_refused(tmp_path: Path, workspace: Path) -> None:
    secret = tmp_path / "id_rsa"
    secret.write_text("SYNTHETIC TEST KEY", encoding="utf-8")
    traversal = (workspace / ".." / "id_rsa").as_uri()
    assert workspace_file_url(traversal, workspace) is None


def test_a_file_that_does_not_exist_is_refused(workspace: Path) -> None:
    """No guessing. The allowance covers looking at real output, nothing else."""
    assert workspace_file_url(_url(workspace / "nope.html"), workspace) is None


def test_a_run_with_no_workspace_gets_no_file_access(workspace: Path) -> None:
    assert workspace_file_url(_url(workspace / "index.html"), None) is None
    assert workspace_file_url(_url(workspace / "index.html"), "") is None


def test_an_http_url_is_not_this_functions_business(workspace: Path) -> None:
    """Anything not file:// falls through to the SSRF guard, untouched."""
    assert workspace_file_url("https://example.com/", workspace) is None
    assert workspace_file_url("http://127.0.0.1:8765/index.html", workspace) is None


def test_a_file_url_naming_a_remote_host_is_refused(workspace: Path) -> None:
    """`file://evil.example/share/x` is a UNC fetch, not a local read."""
    assert workspace_file_url("file://evil.example/share/index.html", workspace) is None


def test_the_open_tool_is_actually_given_the_workspace(workspace: Path) -> None:
    """The wiring, not just the rule.

    A confinement check nothing calls is the failure this repo keeps repeating.
    `_build_tools` hands `register_browser_tools` the run's sandbox; this pins
    that the registered open tool really carries it.
    """
    import importlib.util

    if importlib.util.find_spec("playwright") is None:
        pytest.skip("playwright not installed")
    from thomas.tools.browser import BrowserOpenTool, register_browser_tools

    class _Registry:
        def __init__(self) -> None:
            self.tools: list[object] = []

        def register(self, tool: object) -> None:
            self.tools.append(tool)

    with_ws = _Registry()
    register_browser_tools(with_ws, workspace)
    opener = next(t for t in with_ws.tools if isinstance(t, BrowserOpenTool))
    assert opener._workspace == workspace

    # And the default stays closed: a caller that does not know its workspace
    # gets a tool with no file access at all.
    without_ws = _Registry()
    register_browser_tools(without_ws)
    default_opener = next(t for t in without_ws.tools if isinstance(t, BrowserOpenTool))
    assert default_opener._workspace is None


def test_a_hard_link_is_a_known_limit_and_is_written_down(tmp_path: Path, workspace: Path) -> None:
    """The one escape this check does NOT catch, asserted rather than implied.

    A hard link has no target path to resolve: the file genuinely IS at the
    workspace path, so `resolve()` cannot tell it from ordinary output and the
    read is allowed. That is a limit of path-based confinement, not a bug here.

    It is accepted because it grants nothing new. Making the link needs
    `shell.exec`, and an agent holding `shell.exec` can already read the same
    bytes directly -- the tool sandbox is a tool-level boundary, not an OS one.
    The OS-level answer is the separate sandbox identity in `docs/CAGE_SETUP.md`.
    If this check is ever relied on as a security boundary on its own, this test
    is the note saying it is not one.
    """
    secret = tmp_path / "id_rsa"
    secret.write_text("SYNTHETIC TEST KEY", encoding="utf-8")
    link = workspace / "hardlink.html"
    try:
        import os

        os.link(secret, link)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("hard links not permitted in this environment")

    assert workspace_file_url(_url(link), workspace) is not None, (
        "behaviour changed: update the note above, do not silently tighten"
    )
