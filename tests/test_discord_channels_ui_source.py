from __future__ import annotations

from pathlib import Path

from tests.web_ui_source import read_app_js_source

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = REPO_ROOT / "thomas" / "server" / "web" / "index.html"


def test_channels_nav_button_exists_in_live_shell() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="navChannelsBtn"' in html
    assert 'data-nav-mode="channels"' in html
    assert "Channels" in html


def test_channels_runtime_wires_discord_controls_and_history() -> None:
    js = read_app_js_source()
    assert "const navChannelsBtn = document.getElementById('navChannelsBtn');" in js
    assert "'channels'" in js
    assert "function moduleRenderChannelsSurface(container)" in js
    assert "function moduleRenderChannelsSurfaceNext(container, state)" in js
    assert "moduleRenderChannelsSurface(moduleQueueList);" in js
    assert "/api/channels/discord" in js
    assert "All channels" in js
    assert "Secure local store" in js
    assert 'data-channel-card-select="${escapeHtml(entry.id)}"' in js
    assert 'data-channels-action="restart"' in js
    assert 'data-channels-config-field="thomas_api_token"' in js
    assert "moduleChannelsDraggedCardId" in js
    assert 'data-channels-action="back_to_catalog"' in js
    assert 'data-channels-action="voice_probe"' in js
    assert "Run Wake Probe" in js
    assert "Hey Thomas, how are you?" in js
    assert "raw_transcript" in js
    assert 'data-channels-action="configure_channel"' in js
    assert "function moduleChannelsHelpButton" in js
    assert 'data-channels-action="save_voice_settings"' in js
    assert 'data-channels-runtime-field="voice_profile"' in js
    assert 'data-channels-voice-config-field="voice_tts_backend"' in js
    assert 'data-channels-voice-config-field="voice_tts_model"' in js
    assert 'data-channels-voice-config-field="voice_cloud_voice"' in js
    assert 'data-channels-voice-config-field="default_voice_channel_name"' in js
    assert 'data-channels-voice-config-field="voice_silence_ms"' in js
    assert 'data-channels-voice-config-field="voice_wake_capture_ms"' in js
    assert 'data-channels-voice-config-field="voice_stt_backend"' in js
    assert 'data-channels-voice-config-field="voice_stt_beam_size"' in js
    assert 'data-channels-voice-config-field="voice_stt_vad_filter"' in js
    assert 'data-channels-voice-config-field="voice_stt_vad_min_silence_ms"' in js
    assert 'data-channels-voice-config-field="voice_stt_hint_phrases"' in js
    assert 'data-channels-voice-config-field="voice_stt_prompt"' in js
    assert "module-channels-history-frame" in js
    assert 'data-ui-workspace="channels"' in js
    assert 'data-ui-id="channels.shell"' in js
    assert 'data-ui-component="repeating-card-group"' in js
    assert 'class="thomas-eyes-mark module-channels-eyes-mark"' in js
    assert "function moduleChannelsProtectedAttrs" in js
    assert ">i</span>" in js
    assert "ph-eye" not in js
