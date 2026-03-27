from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_INDEX_PATH = ROOT / "thomas" / "server" / "web" / "index.html"
WEB_RUNTIME_PATH = ROOT / "thomas" / "server" / "web" / "js" / "app_runtime_primary.mjs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chat_shell_contains_mission_control_sidebar_entry() -> None:
    text = _read(WEB_INDEX_PATH)
    assert 'id="navMissionBtn"' in text
    assert "Mission Control" in text


def test_evolve_runtime_stays_in_chat_and_posts_followups() -> None:
    text = _read(WEB_RUNTIME_PATH)
    start = text.index("async function runEvolveMissionJob")
    end = text.index("async function runChatSendJob")
    evolve_block = text[start:end]
    assert "I'll reply here when it finishes." in evolve_block
    assert "Mission Control is available from the left sidebar" in evolve_block
    assert "setSidebarNavMode('mission')" not in evolve_block
    assert "void refreshTaskContinuity({ sessionOverride: chatSessionId, force: true });" in evolve_block
    assert "void missionRefresh({ force: true, silent: true });" in evolve_block
    assert "async function refreshEvolveChatReplies" in text
    assert "mission-evolve-result-" in text
    assert "const EVOLVE_TERMINAL_JOB_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'dead']);" in text


def test_chat_runtime_defaults_to_v2_and_renders_delegation_activity() -> None:
    text = _read(WEB_RUNTIME_PATH)
    assert "const chatEndpoint = window.__THOMAS_CHAT_V2__ === false ? '/api/chat' : '/api/v2/chat';" in text
    assert "function createDelegationBadge(specialistId, task) {" in text
    assert "function createAgentActivityRow(agentId, status, currentTask, elapsedMs) {" in text
    assert "function upsertAgentActivity(container, agentId, status, currentTask, elapsedMs) {" in text
    assert "} else if (evt.type === 'delegation') {" in text
    assert "} else if (evt.type === 'agent_activity') {" in text
    assert "} else if (evt.type === 'memory_refresh') {" in text


def test_chat_runtime_prefers_visible_model_selector_over_setup_profile() -> None:
    text = _read(WEB_RUNTIME_PATH)
    assert "const selectedProfile = modelSelector.value || setupProviderSelector.value;" in text
    assert "const selectedProfile = setupProviderSelector.value || modelSelector.value;" not in text


def test_chat_runtime_scopes_model_state_to_active_profile_and_skips_inactive_saved_profiles() -> None:
    text = _read(WEB_RUNTIME_PATH)
    assert "function resolveStoredModelSelection(profileName = '', { allowLocalBackup = false } = {}) {" in text
    assert "const targetProfile = (savedProfileMeta && savedProfileMeta.active)" in text
    assert "applyProfileSelection(targetProfile, { allowLocalBackup: !hasPersistedProfile });" in text
    assert "const model = (activeProfile === safeString(profileName) ? safeString(activeModelOverride) : '')" in text
    assert "model_id: resolveActiveModelIdForProfile(profile) || undefined," in text
    assert "activeModelOverride = savedModelId ||" not in text


def test_chat_runtime_provider_picker_expands_inline_and_routes_inactive_profiles_to_setup() -> None:
    text = _read(WEB_RUNTIME_PATH)
    assert "function renderSetupProviderPickerMenu(profileName = '', { preserveExpanded = true } = {}) {" in text
    assert "setupProviderMenuShowMore = true;" in text
    assert "Show ${inactive.length} more provider${inactive.length === 1 ? '' : 's'}" in text
    assert (
        "setupProviderMenu.appendChild(createSetupProviderMenuLabel('Uninstalled', 'setup-provider-divider'));" in text
    )
    assert "async function handoffInactiveProviderToEasySetup(profileName = '') {" in text
    assert "await openEasySetup({ source: 'model_setup_provider', force: true, restart: true });" in text
    assert "handleEasySetupPathSelect(path);" in text
    assert "primeEasySetupProfileSelection(selectedProfile, path);" in text
    assert "const profileKey = safeString(profile?.name).toLowerCase();" in text
    assert (
        "provider === 'local' || provider === 'ollama' || profileKey === 'local' || profileKey.includes('ollama')"
        in text
    )
    assert "ChatGPT / Codex selected. Run connection test." in text
    assert "Ready now" not in text
    assert "Needs connection" not in text
    assert (
        "const preferredModel = resolveStoredModelSelection(profileName, { allowLocalBackup }) || defaultModel;" in text
    )
    assert "setupShowAllProviders" not in text


def test_chat_runtime_uses_profile_aware_composer_subbar_and_payload_helper() -> None:
    text = _read(WEB_RUNTIME_PATH)
    assert "initChatComposerSubbar();" in text
    assert "function ensureChatComposerSubbar() {" in text
    assert (
        "function buildChatRequestPayload(message, { docs = [], images = [], systemPrompt = '', resolvedProfile = '', studioChatContext = null } = {}) {"
        in text
    )
    assert "payload.reasoning_effort = reasoningEffort;" in text
    assert "token_economy: resolveChatPayloadTokenEconomy()," in text
    assert "_initThinkingDropdown" not in text


def test_task_continuity_prefers_chat_scoped_delegations() -> None:
    text = _read(WEB_RUNTIME_PATH)
    assert "function buildDelegationRuntimeState(delegations, { sessionId = '' } = {}) {" in text
    assert (
        "const delegationResp = await fetchJsonSafe(`/api/v2/chat/session/${encodeURIComponent(sid)}/delegations`);"
        in text
    )
    assert "void refreshTaskContinuity({ sessionOverride: _delegationSessionId, force: true });" in text


def test_chat_runtime_preserves_stream_chunk_spacing_and_server_mic_capture() -> None:
    text = _read(WEB_RUNTIME_PATH)
    assert "function streamChunkString(value) {" in text
    assert "const textChunk = streamChunkString(chunk);" in text
    assert "const evtText = streamChunkString(evt.text || evt.delta || evt.content);" in text
    assert "const micTranscribeEndpoint = '/api/v2/chat/transcribe';" in text
    assert "navigator.mediaDevices?.getUserMedia" in text
    assert "new MediaRecorder(stream" in text
    assert "await transcribeMicBlob(new Blob(parts, { type: mimeType }))" in text
    assert "Server transcription is unavailable right now. Falling back to browser speech recognition." in text


def test_chat_runtime_renders_hover_timestamps_and_inline_edit_panel() -> None:
    text = _read(WEB_RUNTIME_PATH)
    assert "function chatMessageTimestampText(valueRaw) {" in text
    assert "row.dataset.messageTimestamp = String(createdAt);" in text
    assert "row.title = chatMessageTimestampText(createdAt);" in text
    assert "const footer = document.createElement('div');" in text
    assert "footer.className = 'message-footer';" in text
    assert "timestamp.className = 'message-timestamp';" in text
    assert "const panel = document.createElement('div');" in text
    assert "panel.className = 'message-edit-panel';" in text
    assert (
        "contentDiv.innerHTML = '';"
        not in text[text.index("function beginEditMessage") : text.index("function cancelEditMessage")]
    )


def test_chat_runtime_uses_ambient_robot_status_and_office_delegation_bridge() -> None:
    text = _read(WEB_RUNTIME_PATH)
    assert "const CHAT_THINKING_UI_ENABLED = false;" in text
    assert "function robotAmbientStatusText(channel = 'thinking') {" in text
    assert "const OFFICE_CHAT_PREVIEW_GRACE_MS = 9000;" in text
    assert "function officeShouldShowChatPreview() {" in text
    assert "function officeTaskMatchesChatPreview(task) {" in text
    assert "officeWorkspace.classList.toggle('chat-preview-active', showOfficePreview);" in text
    create_robot_start = text.index("function _createRobotStatus(category) {")
    create_robot_end = text.index("function _updateThinkingDisplay(container, text) {")
    create_robot_block = text[create_robot_start:create_robot_end]
    assert "chat-robot-thinking-toggle" not in create_robot_block
    assert "chat-robot-thinking-details" not in create_robot_block
    assert "function _syncDelegationWorkerVisual(evt, status, taskText) {" in text
    assert "officeQueueTask(taskText, {" in text
    assert "const previewSessionId = _delegationSessionId || safeString(activeChatId) || 'chat';" in text
    assert "source: `chat-delegation:${previewSessionId}:${activityId}`," in text
    assert "const previewScoped = Boolean(officeWorkspace?.classList.contains('chat-preview-active'));" in text
    assert "officeState.tasks.filter((task) => officeTaskMatchesChatPreview(task))" in text
    assert "officeBeginTeleportSequence(agent, performance.now());" in text


def test_chat_css_supports_footer_actions_settings_scroll_and_new_robot_idles() -> None:
    bubble_css = _read(ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "part-001b.css")
    settings_css = _read(ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "part-002a.css")
    robot_css = _read(ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "part-005b.css")
    office_layout_css = _read(ROOT / "thomas" / "server" / "web" / "css" / "layout_parts" / "part-002b.css")
    assert ".message-footer {" in bubble_css
    assert ".message-timestamp {" in bubble_css
    assert ".message-edit-panel {" in bubble_css
    assert ".settings-suite-content {" in bubble_css
    assert "height: min(92vh, calc(100vh - 24px));" in bubble_css
    assert ".settings-suite-body {" in settings_css
    assert "height: 100%;" in settings_css
    assert ".settings-sections {" in settings_css
    assert ".chat-robot-anim-scanning {" in robot_css
    assert ".chat-robot-anim-shimmy {" in robot_css
    assert ".office-workspace.chat-preview-active {" in office_layout_css
    assert ".office-workspace.chat-preview-active .office-chatbar {" in office_layout_css
