"""Focused contracts for the live Channels workspace modernization."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_036 = ROOT / "thomas/server/web/js/runtime/036_workbench_editors_08.js"
RUNTIME_037 = ROOT / "thomas/server/web/js/runtime/037_workbench_editors_09.js"
RUNTIME_038 = ROOT / "thomas/server/web/js/runtime/038_module_rendering_dispatch_01.js"
CHANNELS_CSS = ROOT / "thomas/server/web/css/component_styles/marketplace-channels.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_channels_uses_the_current_five_theme_visual_language() -> None:
    css = _read(CHANNELS_CSS)
    renderer = _read(RUNTIME_037)
    channels_css = css[css.index(".module-channels-shell {") :]

    for theme in ("nebula", "dark", "light", "aurora", "sandstone"):
        assert f'data-thomas-theme="{theme}"' in channels_css
    for token in (
        "--c-surface",
        "--c-surface-2",
        "--c-border",
        "--c-text",
        "--c-dim",
        "--c-muted",
        "--c-accent",
        "--c-accent-ink",
        "--c-accent-soft",
        "--c-accent-line",
        "--c-composer-bg",
    ):
        assert f"var({token})" in channels_css

    assert "background: var(--c-bg)" not in channels_css
    assert 'body:has(#moduleWorkspace[data-mode="channels"]) .main-content' in css
    assert ".main-content::before { display: none !important; }" in css
    assert "rgba(" not in channels_css
    assert re.search(r"#[0-9a-fA-F]{3,8}\b", channels_css) is None
    assert "'JetBrains Mono', ui-monospace, monospace" in channels_css
    assert "'Newsreader', Georgia, serif" in channels_css
    assert 'class="thomas-eyes-mark module-channels-eyes-mark"' in renderer
    assert "@media (prefers-reduced-motion: reduce)" in channels_css


def test_channels_registers_stable_shared_editor_regions() -> None:
    helpers = _read(RUNTIME_036)
    renderer = _read(RUNTIME_037)
    combined = f"{helpers}\n{renderer}"

    assert 'data-ui-workspace="channels"' in renderer
    assert 'data-ui-id="channels.shell"' in renderer
    assert 'data-ui-component="workspace-shell"' in renderer
    assert 'data-ui-component="repeating-card-group"' in renderer
    assert "items-runtime-owned,reposition-allow,resize-deny,add-deny,remove-deny" in renderer
    assert 'data-ui-id="channels.catalog-card.${escapeHtml(instanceKey)}"' in renderer
    assert 'data-ui-instance-key="${escapeHtml(instanceKey)}"' in renderer

    for dynamic_id in (
        "channels.history.session.${escapeHtml(instanceKey)}",
        "channels.history.hit.${escapeHtml(hitKey)}",
        "channels.history.turn.${escapeHtml(turnKey)}",
    ):
        assert f'data-ui-id="{dynamic_id}"' in helpers
    assert helpers.count('data-ui-instance-key="') >= 4
    assert "function moduleChannelsProtectedAttrs" in helpers
    for policy in ("controls secrets", "controls bridge", "controls bridge destructive"):
        assert policy in renderer
    for bound in ("minWidth=", "minHeight=", "maxHeight=", "contain=parent"):
        assert bound in renderer
    assert "data-editor-ui" not in combined
    assert ">Edit UI<" not in combined


def test_channels_preserves_real_discord_actions_and_honest_planned_states() -> None:
    catalog = _read(RUNTIME_036)
    renderer = _read(RUNTIME_037)
    dispatch = _read(RUNTIME_038)

    assert catalog.count("eyebrow: 'Reserved'") >= 10
    assert "Coming soon" in renderer
    assert "This channel is a placeholder slot" in renderer
    assert 'data-channels-action="configure_channel"' in renderer

    for action in (
        "toggle_enabled",
        "start",
        "stop",
        "restart",
        "voice_probe",
        "save_config",
        "save_voice_settings",
        "search",
        "clear_search",
    ):
        assert f"actionId === '{action}'" in dispatch or f"data-channels-action=\"{action}\"" in renderer
    for endpoint in (
        "/api/channels/discord/enabled",
        "/api/channels/discord/voice-probe",
        "/api/channels/discord/config",
        "/api/channels/discord/runtime",
    ):
        assert endpoint in dispatch
    assert "if (!value && (key === 'bot_token' || key === 'thomas_api_token')) return;" in dispatch


def test_channels_claimed_files_stay_within_hard_size_limits() -> None:
    assert len(_read(RUNTIME_036).splitlines()) <= 1500
    assert len(_read(RUNTIME_037).splitlines()) <= 1500
    assert len(_read(RUNTIME_038).splitlines()) <= 1500
    assert len(_read(CHANNELS_CSS).splitlines()) <= 1200
