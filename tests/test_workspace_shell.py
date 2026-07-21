from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"


def _read(relative: str) -> str:
    return (WEB / relative).read_text(encoding="utf-8", errors="replace")


def test_shared_shell_uses_the_exact_five_chat_theme_names_and_core_tokens() -> None:
    shell = _read("js/workspace_shell.js")
    css = _read("css/workspace_shell.css")

    assert 'const THEMES = ["nebula", "dark", "light", "aurora", "sandstone"]' in shell
    for value in ("#070912", "#16181c", "#fafbfc", "#08151a", "#f4ede1"):
        assert value in css
    for value in ("#8b8cff", "#6e9bff", "#2f6bff", "#34e0b0", "#c0603c"):
        assert value in css
    for value in ('"Manrope", system-ui, sans-serif', '"JetBrains Mono", ui-monospace, monospace', '"Newsreader", Georgia, serif'):
        assert value in css
    for value in ("--r-card: 8px", "--r-card: 12px", "--r-card: 14px", "--r-card: 16px"):
        assert value in css
    assert 'const STORAGE_KEY = "thomas_chat_theme"' in shell
    assert 'type: "thomas:theme"' in shell


def test_shared_eyes_mark_is_the_exact_current_chat_identity() -> None:
    css = _read("css/workspace_shell.css")

    assert "width: 30px; height: 30px" in css
    assert "border: 0; border-radius: 9px" in css
    assert "box-shadow: 0 0 18px var(--c-accent-soft)" in css
    assert "width: 5px; height: 6px" in css
    assert "border-radius: 1px" in css


def test_classic_runtime_fetches_in_parallel_but_preserves_execution_order() -> None:
    loader = _read("js/app_runtime_loader.js")

    assert "el.async = false" in loader
    assert "await Promise.all(RUNTIME_SCRIPTS.map(loadScript))" in loader
    assert "for (var i = 0; i < RUNTIME_SCRIPTS.length; i++)" not in loader


def test_chat_routes_bounded_workspaces_without_reloading_on_every_return() -> None:
    chat = _read("chat.html")

    assert "mission: '/mission?embed=1'" in chat
    assert "my_stuff: '/my-stuff?embed=1'" in chat
    assert "settings: '/settings?embed=1'" in chat
    assert "f.removeAttribute('src')" not in chat
    assert "ThomasWorkspaceShell.sendTheme" in chat
