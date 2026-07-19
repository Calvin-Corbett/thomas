from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = ROOT / "thomas" / "server" / "web" / "chat.html"


def test_chat_canvas_live_mode_waits_for_complete_html_before_render() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "function _livePreviewHtml(html, done)" in text
    assert "function _closePartialHtml(html)" in text
    assert "Receiving HTML" in text
    assert "if (canvasState.live) {" in text
    assert "Drawing it" in text
    assert "const _finalDoc = _injectReveal(canvasState.html" in text
    assert "f.setAttribute('srcdoc', _seen ? _staticDoc(_finalDoc) : _finalDoc);" in text


def test_chat_canvas_streams_partial_construction_but_only_completes_after_review() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "row.canvas_mode === 'construct'" in text
    assert "String(row.canvas_review_status || '').toLowerCase() === 'pending'" in text
    assert "canvasConstruct(rid, row.canvas_shell || '', row.canvas_elements || [], false, '')" in text
    assert "_canvasReviewed(row, _cdone) && row.canvas_mode === 'construct'" in text
    assert "canvasState.mode !== 'construct'" in text


def test_chat_shell_settings_button_opens_embedded_settings_workspace() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert 'id="tc-settings"' in text
    assert "mode === 'settings'" in text
    assert "? '/settings?embed=1'" in text
    assert "document.getElementById('tc-settings').addEventListener('click', () => openWorkspace('settings'));" in text


def test_chat_shell_declares_inline_favicon_for_clean_local_runtime() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert '<link rel="icon" href="data:image/svg+xml,' in text


def test_root_chat_copy_search_and_plural_artifact_controls_are_wired() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "async function copyMessageText(text, button)" in text
    assert "data-msg-copy" in text
    assert "navigator.clipboard.writeText(value)" in text
    assert "copyBtn.addEventListener('click'" in text
    assert "const chats = query" in text
    assert "String(c.title || '') + '\\n' + String(c.preview || '')" in text
    assert "state.search = e.target.value; renderChats();" in text
    assert "No matching chats." in text
    assert "if (!Array.isArray(rows)) return;" in text
    assert "verified deliverables" in text
    assert "data-artifact-open" in text
    assert "const artifactKey = art => String(art.url || art.path || art.name || art.id || '')" in text


def test_root_chat_never_presents_unreviewed_canvas_or_completion() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "function _completionVerified(row)" in text
    assert "row.receipt.ok === true" in text
    assert "function _canvasReviewed(row, done)" in text
    assert "canvas_review_status" in text
    assert "Reviewing the result before presenting it" in text
    assert "(_completionVerified(evt) ? 'completed' : 'running')" in text
    assert "function _maybeCollapseActivity(activity)" in text
    assert "activity.expectedHandoffCount || 1" in text
    assert "handoffs.length >= expected" in text
    assert "function _settleActivityForReply(activity)" in text
    assert "if (!handoffs.length) activity.expanded = false" in text
    assert "_settleActivityForReply(a); renderActivity(idx);" in text
    assert "a.expanded = false; renderActivity(idx);" not in text
    assert "evt.runtime_profile && evt.runtime_profile.group_expected_count" in text
    assert "row.runtime_profile && row.runtime_profile.group_expected_count" in text
    assert "handoffs.every(step => step.status === 'completed' || step.status === 'failed')" in text
    assert "if (_completionVerified(evt)) _mergeArtifacts(a, evt);" in text
    assert "if (_completionVerified(row)) _mergeArtifacts(a, row);" in text
    assert "else if (_canvasReviewed(row, _cdone)) canvasLiveHTML" in text
    assert "else if (a.wantsCanvas && s.status === 'running') { /* do not auto-open an unreviewed Canvas */ }" in text
    assert "a.wantsCanvas && s.status === 'running' && canvasState.mode !== 'render'" not in text
    assert "function resetCanvasForConversation()" in text
    assert "canvasState = { mode: 'blank', worker: '', progress: '', url: '', name: '' }" in text
    assert "resetCanvasForConversation(); renderChats();" in text


def test_root_chat_restores_only_verified_artifacts_for_the_selected_history_session() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "let chatSelectionToken = 0" in text
    assert "async function restoreVerifiedChatArtifacts(chatId, sessionId, selectionToken)" in text
    assert "encodeURIComponent(sid) + '/delegations'" in text
    assert "selectionToken !== chatSelectionToken || state.activeChat !== chatId" in text
    assert "String(row.session_id || '') === sid && _completionVerified(row)" in text
    assert "_mergeArtifacts(activity, row);" in text
    assert "restoreVerifiedChatArtifacts(id, c.sessionId, selectionToken);" in text
    restore_body = text.split("async function restoreVerifiedChatArtifacts", 1)[1].split("function selectChat", 1)[0]
    assert "announceCompletion(" not in restore_body
    assert "canvasLiveHTML(" not in restore_body
    assert "canvasRender(" not in restore_body


def test_root_chat_restores_reviewed_canvas_only_on_explicit_open() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "const reviewedCanvasRows = sessionRows.filter(row => _canvasReviewed(row, true));" in text
    assert "const durableCanvasRows = sessionRows.map(row =>" in text
    assert "profile.canvas === true" in text
    assert "mode: 'render'" in text
    assert "restored.mode === 'render' && restored.url" in text
    assert "state.restoredCanvas = reviewedCanvas ?" in text
    assert "function openConversationCanvas()" in text
    assert "restored.chatId === state.activeChat" in text
    assert "restored.sessionId === String(state.sessionId || '')" in text
    assert "document.getElementById('tc-canvas-btn').addEventListener('click', openConversationCanvas);" in text
    assert "state.restoredCanvas = null;" in text
    restore_body = text.split("async function restoreVerifiedChatArtifacts", 1)[1].split("function selectChat", 1)[0]
    assert "openCanvas(" not in restore_body
    assert "openConversationCanvas(" not in restore_body


def test_root_chat_text_artifact_preview_decodes_utf8_explicitly() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "function _isTextArtifact(kind, url, name)" in text
    assert "data-artifact-kind" in text
    assert "response.arrayBuffer()" in text
    assert "type: 'text/plain;charset=utf-8'" in text
    assert "new TextDecoder('utf-8', { fatal: false })" in text
    assert "canvasState = { mode: 'document'" in text


def test_root_chat_grouped_restored_activity_uses_clean_aggregate_summary() -> None:
    text = CHAT_HTML.read_text(encoding="utf-8")

    assert "const grouped = groupSize > 1;" in text
    assert "`${groupSize} workers completed`" in text
    assert "const verifiedLabel = verifiedNames.length === 1" in text
    restore_body = text.split("async function restoreVerifiedChatArtifacts", 1)[1].split("function selectChat", 1)[0]
    assert "row.last_progress" not in restore_body
    assert "row.summary" not in restore_body
