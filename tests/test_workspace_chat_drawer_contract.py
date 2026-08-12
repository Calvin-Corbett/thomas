from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = REPO_ROOT / "thomas/server/web/chat.html"
DRAWER_JS = REPO_ROOT / "thomas/server/web/js/workspace_chat_drawer.js"
DRAWER_VIEW_JS = REPO_ROOT / "thomas/server/web/js/workspace_chat_drawer_view.js"
TRANSPORT_JS = REPO_ROOT / "thomas/server/web/js/workspace_chat_transport.js"
DRAWER_CSS = REPO_ROOT / "thomas/server/web/css/workspace_chat_drawer.css"
CANVAS_LOADER = REPO_ROOT / "thomas/server/web/js/app_runtime_loader.js"
LIBRARY_JS = REPO_ROOT / "thomas/server/web/static/my_stuff.script01.js"


def test_parent_shell_owns_one_workspace_chat_drawer_and_transforms_top_action() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    js = DRAWER_JS.read_text(encoding="utf-8")
    view = DRAWER_VIEW_JS.read_text(encoding="utf-8")

    assert html.count("/static/js/workspace_chat_drawer.js") == 1
    assert html.count("/static/js/workspace_chat_drawer_view.js") == 1
    assert html.count("/static/js/workspace_chat_transport.js") == 1
    assert html.index("workspace_chat_transport.js") < html.index("workspace_chat_drawer_view.js") < html.index("workspace_chat_drawer.js")
    assert html.count("/static/css/workspace_chat_drawer.css") == 1
    assert 'id="tc-primary-action-label">Canvas</span>' in html
    assert "state.workspaceOpen && window.ThomasWorkspaceChat" in html
    assert "window.ThomasWorkspaceChat.setWorkspace(mode)" in html
    assert "window.ThomasWorkspaceChat.setWorkspace(null)" in html
    assert "label.textContent = 'Chat'" in js
    assert "label.textContent = 'Canvas'" in js
    assert "body.appendChild(drawer)" in view
    assert "document.createElement('iframe')" not in js + view


def test_workspace_drawer_uses_scoped_resident_surface_without_general_session_bootstrap() -> None:
    transport = TRANSPORT_JS.read_text(encoding="utf-8")
    js = transport + DRAWER_JS.read_text(encoding="utf-8")

    for mode in ("mission", "office", "app_builder", "my_stuff", "channels", "token_economy", "marketplace", "settings"):
        assert f"workspace:{mode}" in transport
    assert "surface_mode: 'workspace'" in js
    assert "context_id: scoped.context" in js
    assert "/api/chats?mode=workspace&context_id=" in js
    assert "/api/session/new" not in js
    assert "send_task" not in js
    assert "delegation" not in js.lower()


def test_workspace_drawer_registers_meaningful_regions_with_edit_mode_contract() -> None:
    js = DRAWER_JS.read_text(encoding="utf-8") + DRAWER_VIEW_JS.read_text(encoding="utf-8")

    for identity in (
        "workspace-chat.drawer",
        "workspace-chat.history",
        "workspace-chat.conversation",
        "workspace-chat.thread",
        "workspace-chat.composer",
        "workspace-chat.action.new",
        "workspace-chat.action.close",
        "workspace-chat.action.send",
    ):
        assert identity in js
    assert "data-ui-instance-key" in js
    assert "thomas:ui-edit-mode-change" in js
    assert "closeDrawer()" in js
    assert "drawer.inert = true" in js


def test_duplicate_canvas_and_library_chat_paths_are_retired() -> None:
    canvas_loader = CANVAS_LOADER.read_text(encoding="utf-8")
    library = LIBRARY_JS.read_text(encoding="utf-8")

    assert "canvas_thomas_conversation.js" not in canvas_loader
    assert "window.ThomasCanvasConversation" not in canvas_loader
    assert "fetch('/api/v2/chat'" not in library
    assert "thomas:workspace-chat:open" in library
    assert "data-open-workspace-chat" in library


def test_workspace_drawer_assets_stay_small_and_parse_as_javascript() -> None:
    for asset in (DRAWER_JS, DRAWER_VIEW_JS, TRANSPORT_JS, DRAWER_CSS):
        assert len(asset.read_text(encoding="utf-8").splitlines()) <= 300
    for script in (TRANSPORT_JS, DRAWER_VIEW_JS, DRAWER_JS):
        completed = subprocess.run(
            ["node", "--check", str(script)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
