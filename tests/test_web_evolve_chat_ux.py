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
    assert "model_id: resolveActiveModelIdForProfile(resolvedProfile) || undefined," in text
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
