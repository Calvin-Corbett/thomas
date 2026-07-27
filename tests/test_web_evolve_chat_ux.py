from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_INDEX_PATH = ROOT / "thomas" / "server" / "web" / "index.html"
RUNTIME_DIR = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
COMPOSER_CONTROLS_PATH = ROOT / "thomas" / "server" / "web" / "js" / "composer_controls.js"
COMPANION_RUNTIME_PATH = ROOT / "thomas" / "server" / "web" / "js" / "companion_runtime.js"
PRIMARY_RUNTIME_PATH = ROOT / "thomas" / "server" / "web" / "js" / "app_runtime_primary.mjs"
CHAT_HTML_PATH = ROOT / "thomas" / "server" / "web" / "chat.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_many(paths: list[Path]) -> str:
    return "\n".join(_read(path) for path in paths)


def _read_all_runtime_js() -> str:
    """Read and concatenate all split runtime JS files in order."""
    if not RUNTIME_DIR.exists():
        return ""
    parts = sorted(RUNTIME_DIR.glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in parts)


def test_chat_shell_contains_mission_control_sidebar_entry() -> None:
    text = _read(WEB_INDEX_PATH)
    assert 'id="navMissionBtn"' in text
    assert "Mission Control" in text


def test_evolve_runtime_stays_in_chat_and_posts_followups() -> None:
    text = _read_all_runtime_js()
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


def test_chat_runtime_uses_only_v2_and_renders_delegation_activity() -> None:
    text = _read_all_runtime_js()
    assert "const chatEndpoint = '/api/v2/chat';" in text
    assert "window.__THOMAS_CHAT_V2__" not in text
    assert "'/api/chat'" not in text
    assert "function createDelegationBadge(specialistId, task) {" in text
    assert "function createAgentActivityRow(agentId, status, currentTask, elapsedMs) {" in text
    assert "function upsertAgentActivity(container, agentId, status, currentTask, elapsedMs) {" in text
    assert "} else if (evt.type === 'delegation') {" in text
    assert "} else if (evt.type === 'agent_activity') {" in text
    assert "} else if (evt.type === 'memory_refresh') {" in text


def test_chatgpt_connection_reply_opens_profile_scoped_easy_setup_recovery() -> None:
    split_runtime = _read(RUNTIME_DIR / "013_actions_interactions_02.js")
    bundled_runtime = _read(PRIMARY_RUNTIME_PATH)

    for text in (split_runtime, bundled_runtime):
        assert "function shouldPromptChatGPTConnectionRecovery(assistantText = '', payload = {}) {" in text
        assert "if (!isChatGPTConnectionProfile(payload?.profile || payload?.model)) return false;" in text
        assert "/^(?:the )?chatgpt(?: oauth| model)? (?:is not|isn't) connected\\b/i" in text
        assert "if (!normalized || normalized.length > 500) return false;" in text
        assert "if (shouldPromptChatGPTConnectionRecovery(assistantFinalText, payload)) {" in text
        assert "await promptChatGPTConnectionRecovery(payload);" in text
        assert "source: 'chatgpt_connection_recovery'" in text
        assert "handleEasySetupPathSelect('codex');" in text
        assert "Your ChatGPT or Codex app sign-in is separate from Thomas." in text


def test_companion_chat_uses_the_canonical_v2_endpoint() -> None:
    text = _read(COMPANION_RUNTIME_PATH)
    assert 'fetch("/api/v2/chat", {' in text
    assert 'fetch("/api/chat", {' not in text


def test_primary_runtime_fallback_has_no_v1_chat_switch() -> None:
    text = _read(PRIMARY_RUNTIME_PATH)
    assert "window.__THOMAS_CHAT_V2__" not in text
    assert "'/api/chat'" not in text
    assert text.count("const chatEndpoint = '/api/v2/chat';") >= 2


def test_chat_shell_defaults_to_a_usable_profile_case_insensitively() -> None:
    text = _read(CHAT_HTML_PATH)
    assert "String(prefs.active_profile || d.default || '').trim().toLowerCase()" in text
    assert "String(p.name || '').trim().toLowerCase() === active" in text
    assert "profilesData.find(usable) || profilesData[0]" in text
    assert "profilesData.find(p => !!p.has_api_key) || pick || profilesData[0]" not in text


def test_root_chat_prompts_and_starts_native_chatgpt_oauth_recovery() -> None:
    text = _read(CHAT_HTML_PATH)

    assert "function shouldPromptChatGPTConnection(assistantText) {" in text
    assert "if (!isChatGPTOAuthProfile(state.profile)) return false;" in text
    assert "/^(?:the )?chatgpt(?: oauth| model)? (?:is not|isn't) connected\\b/i" in text
    assert "await maybePromptChatGPTConnection(acc);" in text
    assert "status.needs_login === true && status.logged_in !== true" in text
    assert "overlay.id = 'tc-chatgpt-connect-prompt';" in text
    assert "Connect ChatGPT to Thomas" in text
    assert "Your ChatGPT or Codex app sign-in is separate from Thomas's local connection." in text
    assert "fetch('/api/openai-codex/login', {" in text
    assert "body: JSON.stringify({ profile: state.profile || 'openai_codex', timeout_s: 300 })" in text


def test_root_chat_surfaces_gpt56_models_and_distinct_reasoning_efforts() -> None:
    text = _read(CHAT_HTML_PATH)

    assert "async function hydrateProfileModels() {" in text
    assert "fetch('/api/openai-codex/models?profile=' + encodeURIComponent(p.name))" in text
    assert "body: JSON.stringify({ advanced: { model: { active_profile: profileName, model_id: modelId } } })" in text
    assert "m.available === false ? ' · unavailable on this connection'" in text
    assert "['none', 'None']" in text
    assert "['xhigh', 'xHigh']" in text
    assert "['max', 'Max']" in text


def test_root_chat_canvas_hint_requires_visual_object_and_action() -> None:
    text = _read(CHAT_HTML_PATH)

    assert "function detectVisualIntent(text)" in text
    assert "playable (browser )?game|interactive (chart|graph|dashboard|site|app|visual)" in text
    assert "return visual.test(lc) && (action.test(lc) || leading.test(lc));" in text
    assert "_pendingCanvasIntent = !!detectVisualIntent(text);" in text


def test_chat_runtime_prefers_visible_model_selector_over_setup_profile() -> None:
    text = _read_all_runtime_js()
    assert "const selectedProfile = modelSelector.value || setupProviderSelector.value;" in text
    assert "const selectedProfile = setupProviderSelector.value || modelSelector.value;" not in text


def test_chat_runtime_scopes_model_state_to_active_profile_and_skips_inactive_saved_profiles() -> None:
    text = _read_all_runtime_js()
    assert "function resolveStoredModelSelection(profileName = '', { allowLocalBackup = false } = {}) {" in text
    assert (
        "const savedProfileReady = savedProfileMeta && (savedProfileMeta.has_api_key || savedProfileMeta.active);"
        in text
    )
    assert "const targetProfile = savedProfileReady" in text
    assert "applyProfileSelection(targetProfile, { allowLocalBackup: !hasPersistedProfile });" in text
    assert "const model = (activeProfile === safeString(profileName) ? safeString(activeModelOverride) : '')" in text
    assert "model_id: safeString(specialty?.modelId) || resolveActiveModelIdForProfile(profile) || undefined," in text
    assert "activeModelOverride = savedModelId ||" not in text


def test_chat_runtime_persists_easy_setup_and_specialty_model_preferences() -> None:
    text = _read_all_runtime_js()
    assert "function resolveEasySetupSelectedProfile() {" in text
    assert "active_profile: selectedProfile," in text
    assert "model_id: selectedModelId," in text
    assert "role_profiles: specialtyPatch.role_profiles," in text
    assert "role_model_ids: specialtyPatch.role_model_ids," in text
    assert "function resolveSpecialtyModelSelection(roleRaw = '', fallbackProfileRaw = '') {" in text
    assert "model_id: safeString(specialty?.modelId) || resolveActiveModelIdForProfile(profile) || undefined," in text


def test_chat_runtime_provider_picker_expands_inline_and_routes_inactive_profiles_to_setup() -> None:
    text = _read_all_runtime_js()
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
    assert "ChatGPT (OpenAI) selected. Run connection test." in text
    assert "Ready now" not in text
    assert "Needs connection" not in text
    assert (
        "const preferredModel = resolveStoredModelSelection(profileName, { allowLocalBackup }) || defaultModel;" in text
    )
    assert "setupShowAllProviders" not in text


def test_chat_runtime_uses_profile_aware_composer_subbar_and_payload_helper() -> None:
    text = _read_all_runtime_js() + "\n" + _read(COMPOSER_CONTROLS_PATH)
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
    text = _read_all_runtime_js()
    assert "function buildDelegationRuntimeState(delegations, { sessionId = '' } = {}) {" in text
    assert (
        "const delegationResp = await fetchJsonSafe(`/api/v2/chat/session/${encodeURIComponent(sid)}/delegations`);"
        in text
    )
    assert "void refreshTaskContinuity({ sessionOverride: _delegationSessionId, force: true });" in text


def test_chat_runtime_preserves_stream_chunk_spacing_and_server_mic_capture() -> None:
    text = _read_all_runtime_js()
    assert "function streamChunkString(value) {" in text
    assert "const textChunk = streamChunkString(chunk);" in text
    assert "const evtText = streamChunkString(evt.text || evt.delta || evt.content);" in text
    assert "const micTranscribeEndpoint = '/api/v2/chat/transcribe';" in text
    assert "navigator.mediaDevices?.getUserMedia" in text
    assert "new MediaRecorder(stream" in text
    assert "await transcribeMicBlob(new Blob(parts, { type: mimeType }))" in text
    assert "Server transcription is unavailable right now. Falling back to browser speech recognition." in text


def test_chat_runtime_renders_hover_timestamps_and_inline_edit_panel() -> None:
    text = _read_all_runtime_js()
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


def test_chat_runtime_uses_structured_office_delegation_bridge() -> None:
    text = _read_all_runtime_js()
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
    sync_start = text.index("function _syncDelegationWorkerVisual(evt, status, taskText) {")
    sync_end = text.index("function _delegationActivityId(evt) {", sync_start)
    sync_block = text[sync_start:sync_end]
    assert "officeSyncStructuredDelegationTask(evt, status, taskText);" in sync_block
    assert "officeBeginTeleportSequence(" not in sync_block
    assert "_syncDelegationWorkerVisual(evt, status, taskText);" in text


def test_chat_css_supports_footer_actions_settings_scroll_and_new_robot_idles() -> None:
    bubble_css = _read(ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "chat-game-animations.css")
    settings_css = _read(ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "settings-panel.css")
    robot_css = _read(ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "chat-robot-animations.css")
    office_layout_css = _read_many(
        [
            ROOT / "thomas" / "server" / "web" / "css" / "layout_parts" / "layout-workspace.css",
            ROOT / "thomas" / "server" / "web" / "css" / "layout_parts" / "layout-responsive.css",
        ]
    )
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
