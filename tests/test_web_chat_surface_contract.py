from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "thomas" / "server" / "web" / "js" / "runtime"
MARKETPLACE_RUNTIME_JS = RUNTIME_DIR / "025_module_system_command_center_01.js"
DISPATCH_RUNTIME_JS = RUNTIME_DIR / "039_module_rendering_dispatch_02.js"
ACTION_RUNTIME_JS = RUNTIME_DIR / "013_actions_interactions_02.js"
CHAT_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "component_styles" / "chat-game-animations.css"
SUGGESTION_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "component_styles" / "easy-setup-ui.css"
LAYOUT_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "layout_styles" / "layout-app-shell.css"
ROBOT_STATUS_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "component_styles" / "tool-calls-chat.css"
ROBOT_DOCK_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "component_styles" / "chat-robot-animations.css"
ROBOT_PORTAL_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "component_styles" / "robot-portal-animations.css"
TOKEN_ECONOMY_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "token_economy.js"
TOKEN_ECONOMY_SPACE_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "token_economy_space_theme.css"
MY_STUFF_HTML = REPO_ROOT / "thomas" / "server" / "web" / "static" / "my_stuff.html"
MY_STUFF_JS = REPO_ROOT / "thomas" / "server" / "web" / "static" / "my_stuff.script01.js"
MY_STUFF_CSS = REPO_ROOT / "thomas" / "server" / "web" / "static" / "my_stuff.style01.css"
BRAIN_PY = REPO_ROOT / "thomas" / "marketplace" / "orchestrator" / "brain.py"
COMPONENT_ICON_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "component_styles" / "composer-attachments.css"
INDEX_HTML = REPO_ROOT / "thomas" / "server" / "web" / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_all_runtime_js() -> str:
    """Read and concatenate all split runtime JS files in order."""
    if not RUNTIME_DIR.exists():
        return ""
    parts = sorted(RUNTIME_DIR.glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in parts)


def test_provider_identity_uses_icons_and_model_inference() -> None:
    js = _read_all_runtime_js()
    css = _read(CHAT_CSS)
    brain = _read(BRAIN_PY)

    assert "function createProviderIdentityIcon(" in js
    assert "function resolveProviderIdentity(" in js
    assert "return 'qwen';" in js
    assert "provider.className = 'message-provider';" in js
    assert "text: 'Y'," not in js
    assert "author.textContent = isUser ? 'You' : resolveAgentName(currentPreferences);" not in js
    assert "renderMessage({ role: 'assistant', content: intro });" not in js
    assert "{{agent}} online. Give me the objective, constraints, and deadline. I will execute." not in js
    assert (
        "{{agent}} boot sequence complete. Brain not fully connected yet. Easy Setup is required, and every download/install needs your explicit approval."
        not in js
    )
    assert "content.className = isUser ? 'message-content user-bubble' : 'message-content assistant-bubble';" in js
    assert "I can also run code, search the web, manage files" not in brain
    assert "providerBrand.className = 'message-provider-brand';" not in js
    assert "providerLabel.className = 'message-provider-label';" not in js
    assert "provider.textContent = providerBits.join(' | ');" not in js
    assert "providerMark: providerIdentityMark(providerId)" not in js
    assert "mark.textContent = safeString(profileMeta.providerMark) || 'AI';" not in js

    assert ".message-row.is-user {" in css
    assert "justify-content: flex-end;" in css
    assert ".message-row.is-user .message-stack {" in css
    assert "justify-items: end;" in css
    assert ".message-actions {" in css
    assert ".message-row:hover .message-actions," in css
    assert ".msg-action-btn {" in css
    assert ".message-provider-separator {" in css
    assert ".message-model-label {" in css
    assert ".message-content::before {" in css
    assert ".message-row.is-user .message-content::before {" in css
    assert ".message-row.is-assistant .message-content::before {" in css
    assert "background: transparent;" in css
    assert "backdrop-filter: none;" in css
    assert (
        "text-shadow: 0 0 2px rgba(218, 226, 240, 0.06), 0 0 16px rgba(214, 224, 240, 0.18), 0 0 34px rgba(214, 224, 240, 0.1), 0 0 52px rgba(214, 224, 240, 0.04);"
        in css
    )
    assert (
        "text-shadow: 0 0 2px rgba(5, 8, 14, 0.08), 0 0 18px rgba(6, 10, 18, 0.28), 0 0 36px rgba(6, 10, 18, 0.16), 0 0 56px rgba(6, 10, 18, 0.07);"
        in css
    )
    assert ".message-provider-brand {" not in css
    assert ".message-provider-label {" not in css
    assert ".message-provider-icon {" not in css
    assert '.provider-identity-icon[data-provider="openai"]' in css
    assert "M249.176 323.434V298.276" in css
    assert "circle cx='12' cy='4.4'" not in css
    assert '.provider-identity-icon[data-provider="qwen"]' in css
    assert '.avatar.assistant[data-provider="qwen"]' in css


def test_suggestion_rail_contract_uses_looping_marquee() -> None:
    js = _read_all_runtime_js()
    css = _read(SUGGESTION_CSS)

    assert "assistantSuggestionBubbles.dataset.mode = 'marquee';" in js
    assert "assistantSuggestionBubbles.dataset.ready = 'false';" in js
    assert "duplicateGroup.className = 'assistant-suggestion-group is-duplicate';" in js
    assert "const pixelsPerSecond = 16;" in js
    assert "const durationSeconds = Math.max(40, Math.min(88, groupWidth / pixelsPerSecond));" in js
    assert "track.style.setProperty('--assistant-group-width'" in js
    assert "track.style.setProperty('--assistant-scroll-duration'" in js

    assert "mask-image: linear-gradient(90deg, transparent 0, #000 8%, #000 92%, transparent 100%);" in css
    assert "--assistant-scroll-duration: 40s;" in css
    assert '.assistant-suggestion-bubbles[data-mode="marquee"][data-ready="true"] .assistant-suggestion-track {' in css
    assert "animation: assistantSuggestionMarquee var(--assistant-scroll-duration) linear infinite;" in css


def test_chat_feed_layout_stays_bottom_anchored() -> None:
    css = _read(LAYOUT_CSS)

    assert "padding-top: clamp(16px, 2.8vh, 28px);" in css
    assert (
        "padding-bottom: calc(max(176px, var(--composer-offset, 176px)) + env(safe-area-inset-bottom) + 10px);" in css
    )
    assert "min-height: 100%;" in css
    assert "justify-content: flex-end;" in css


def test_robot_surface_uses_shared_frame_and_teleport_contract() -> None:
    js = _read_all_runtime_js()
    portal_css = _read(ROBOT_PORTAL_CSS)
    dock_css = _read(ROBOT_DOCK_CSS)

    assert (
        "const CHAT_ROBOT_ANIMATIONS = ['fishing', 'bouncing', 'looking', 'napping', 'waving', 'lifting', 'scanning', 'shimmy'];"
        in js
    )
    assert "const CHAT_ROBOT_DOCK_WIDTH = 31;" in js
    assert "const CHAT_ROBOT_DOCK_HEIGHT = 29;" in js
    assert "const CHAT_ROBOT_EXIT_FALL_MS = 860;" in js

    assert ".chat-robot-dock {" in portal_css
    assert "width: 31px;" in portal_css
    assert "height: 29px;" in portal_css

    assert ".chat-robot-anim-lifting {" in dock_css
    assert "@keyframes chatRobotExitPortal" in dock_css
    assert ".chat-robot-landed {" in dock_css
    assert "width: 31px;" in dock_css
    assert "height: 29px;" in dock_css


def test_sidebar_chat_label_and_search_shell_contract() -> None:
    layout_css = _read(LAYOUT_CSS)
    components_css = _read(COMPONENT_ICON_CSS)
    index_html = _read(INDEX_HTML)
    js = _read_all_runtime_js()

    assert '<span class="nav-chat-robot-wrap"' not in index_html
    assert ".nav-chat-robot-wrap {" in components_css
    assert "display: none !important;" in components_css
    # The robot markup must not come back through the live runtime either. (The
    # old check asserted a defensive stripper inside the js/modules archive
    # trees, which no page loaded; the trees are deleted, so the invariant is
    # now pinned on the code that actually runs.)
    assert "nav-chat-robot-wrap" not in js

    assert ".sidebar-search-input-wrap input {" in layout_css
    assert "background: transparent !important;" in layout_css
    assert "border: 0 !important;" in layout_css
    assert "border-radius: 0 !important;" in layout_css
    assert "appearance: none;" in layout_css
    assert "-webkit-appearance: none;" in layout_css
    assert "navChatBtn.addEventListener('click', (event) => {" in js
    assert "setChatListExpanded(!chatListExpanded);" in js
    assert "if (globalSearchInput) globalSearchInput.focus();" not in js


def test_chat_status_suppresses_ambient_robots_and_keeps_game_player() -> None:
    js = _read_all_runtime_js()
    status_css = _read(ROBOT_STATUS_CSS)
    composer_css = _read(COMPONENT_ICON_CSS)
    index_html = _read(INDEX_HTML)
    token_js = _read(TOKEN_ECONOMY_JS)
    token_css = _read(TOKEN_ECONOMY_SPACE_CSS)

    assert 'class="chat-game-bot-wrap" id="chatGameBotWrap"' in index_html
    assert 'class="chat-game-player-avatar" id="chatGameBot"' in index_html
    assert 'class="office-pixel-agent costume-headset" id="chatGameBot"' not in index_html
    assert 'id="chatGameControls"' in index_html
    assert ".chat-game-bot-wrap {" in composer_css
    assert "display: block;" in composer_css
    assert ".chat-game-player-avatar" in composer_css
    assert ".chat-game-bot-wrap .office-pixel-agent" not in composer_css

    assert "function chatWorldEnsureUi() {" in js
    assert "removeChatAgentPresenceUi();" in js
    assert 'class="chat-robot-agent chat-robot-world-agent"' not in js
    assert ".assistant-work-status-text" in status_css
    assert ".assistant-work-status-timer" in status_css
    assert "#chatAgentPresence," in status_css
    assert ".chat-robot-world," in status_css
    assert "body.te-nav-chat #officeScene .office-agent" in status_css

    assert "requestAnimationFrame" not in token_js
    assert "MutationObserver" not in token_js
    assert "function workspaceActive()" in token_js
    assert "if (_s.sse || !workspaceActive()) return;" in token_js
    assert "[data-te-container] .te-v3.is-active" in token_css
    assert "body.te-space-active" not in token_css


def test_token_economy_leads_with_tokens_and_runtime_profiles() -> None:
    token_js = _read(TOKEN_ECONOMY_JS)

    assert "<span>Token history</span>" in token_js
    assert 'data-ui-label="Runtime profile matrix"' in token_js
    assert "data-te-hdollar>TOK" in token_js
    assert "function modelTokens(detail)" in token_js
    assert "api('/api/runtime/matrix')" in token_js
    assert "SESSION TOKENS" in token_js
    assert "AVG TOK/CALL" in token_js
    assert "New token events will appear here" in token_js
    assert "function paintPricing()" in token_js
    assert "SPEND HISTORY" not in token_js
    assert "RATE CARD" not in token_js


def test_installed_plugin_nav_uses_fast_boot_refresh() -> None:
    marketplace_js = _read(MARKETPLACE_RUNTIME_JS)
    dispatch_js = _read(DISPATCH_RUNTIME_JS)

    assert "function moduleRefreshInstalledPluginNav(" in marketplace_js
    assert "moduleFetchJsonSafe('/api/marketplace/installed')" in marketplace_js
    assert "moduleSetInstalledPluginRows(rows);" in marketplace_js
    assert "moduleSetInstalledPluginRows(installedPlugins, { render: false });" in marketplace_js
    assert "void moduleRefreshInstalledPluginNav({ force: true });" in dispatch_js
    assert dispatch_js.index("void moduleRefreshInstalledPluginNav({ force: true });") < dispatch_js.index(
        "void moduleRefreshMarketplace({ force: true });"
    )


def test_my_stuff_indexes_installed_workspace_plugins() -> None:
    html = _read(MY_STUFF_HTML)
    js = _read(MY_STUFF_JS)
    css = _read(MY_STUFF_CSS)

    assert "20260624-forge-builds-1" in html
    assert 'id="installedAppsShelf"' in html
    assert '<section class="stuff-installed-shelf" id="installedAppsShelf"' in html
    assert "Loading app workspaces..." in html
    assert "Library items" in html
    assert "installedPlugins: []" in js
    assert "fetchJson(window.location.origin + '/api/marketplace/installed')" in js
    assert "function installedPluginsFromPayload(payload)" in js
    assert "async function refreshInstalledPlugins()" in js
    assert "var installedPromise = refreshInstalledPlugins();" in js
    assert "await installedPromise;" in js
    assert js.index("var installedPromise = refreshInstalledPlugins();") < js.index("fetchJson('/api/local/projects')")
    assert "function installedWorkspacePlugins()" in js
    assert "function renderInstalledAppsShelf()" in js
    assert "elements.installedAppsShelf.classList.remove('hidden');" in js
    assert "function renderInstalledAppCard(plugin)" in js
    assert "function pluginShelfRank(plugin)" in js
    assert "paper-trading" in js
    assert "function reservedModuleSlots()" in js
    assert "function projectBoardPosition(project, moduleSlots)" in js
    assert "+ cards;" in js
    assert "left_nav_behavior).toLowerCase() !== 'workspace'" in js
    assert "data-plugin-mode" in js
    assert "window.parent.setSidebarNavMode(mode);" in js
    assert "Library ready. '" in js
    assert "installed app' + (moduleCount === 1 ? '' : 's')" in js
    assert "project' + (state.projects.length === 1 ? '' : 's')" in js
    assert "+ moduleCards" not in js
    assert ".stuff-module-app {" in css
    assert ".stuff-module-icon {" in css
    assert ".stuff-installed-shelf {" in css
    assert ".stuff-installed-app {" in css
    runtime_07 = _read(RUNTIME_DIR / "035_workbench_editors_07.js")
    runtime_08 = _read(RUNTIME_DIR / "036_workbench_editors_08.js")
    assert "src: '/static/my_stuff.html?v=20260624-forge-builds-1'" in runtime_07
    assert "src: '/static/my_stuff.html?v=20260624-forge-builds-1'" in runtime_08
    assert "/static/static/my_stuff.html" not in runtime_07
    assert "/static/static/my_stuff.html" not in runtime_08


def test_paper_trading_is_promoted_high_in_workspace_nav() -> None:
    runtime_07 = _read(RUNTIME_DIR / "035_workbench_editors_07.js")
    runtime_08 = _read(RUNTIME_DIR / "036_workbench_editors_08.js")

    for js in (runtime_07, runtime_08):
        assert "promoteAfter('paper_trading', 'mission');" in js
        assert "const ordered = stored.concat(appended);" in js
        assert "return ordered;" in js


def test_chat_games_keep_deterministic_proof_hooks_and_neutral_actor_payload() -> None:
    game_js = _read(RUNTIME_DIR / "010_chat_games_01.js")
    hook_js = _read(RUNTIME_DIR / "011_chat_games_02.js")

    assert "function chatGameRenderToTextPayload()" in game_js
    assert "function chatGameAdvanceTime(ms = 16)" in hook_js
    assert "function chatGameBootFromUrl()" in hook_js
    assert "params.get('game') || params.get('chat_game')" in hook_js
    assert "window.render_game_to_text = chatGameRenderToTextPayload;" in hook_js
    assert "window.advanceTime = chatGameAdvanceTime;" in hook_js

    render_start = game_js.index("function chatGameRenderToTextPayload()")
    render_block = game_js[render_start:]
    assert "actor: {" in render_block
    assert "bot: {" not in render_block
    # The neutral payload key holds across the whole live game module, not just
    # the render block. (This used to be asserted against the js/modules archive
    # copies of chatGameStepDinoGameOver, which no page loaded; the archives are
    # deleted, so the same invariant is pinned on the live file.)
    assert "function chatGameStepDinoGameOver(" in game_js
    assert "bot: {" not in game_js


def test_failed_delegation_cards_prefer_failure_progress_over_title() -> None:
    js = _read(ACTION_RUNTIME_JS)
    setup_js = _read(RUNTIME_DIR / "003_easy_setup_onboarding_01.js")
    continuity_js = _read(RUNTIME_DIR / "006_easy_setup_onboarding_04.js")

    assert "function _delegationTask(evt) {" in js
    assert "safeString(evt?.type) === 'delegation_failed'" in js
    assert "safeString(evt?.state).toLowerCase() === 'failed'" in js
    assert "safeString(evt.last_progress || evt.summary || evt.text || evt.task || evt.current_task)" in js
    assert "safeString(evt.summary || evt.last_progress || evt.text || evt.task || evt.current_task)" in js
    assert "|| _boundExecutionIds.size === 0" in js
    assert "appendDelegationResultMessage(evt, { status, summary: cleanText });" in js
    assert "summary = summary.replace(/no a first event/gi, 'no first event');" in setup_js
    assert "void persistActiveChat({ quiet: true });" in setup_js
    assert "function appendDelegationResultMessage(evt, options = {})" in setup_js
    assert "function appendTerminalDelegationActivityResults(activity)" in continuity_js
    assert "appendTerminalDelegationActivityResults(activity);" in continuity_js


def test_model_setup_surface_uses_compact_centered_chip_and_themed_provider_dropdown() -> None:
    index_html = _read(INDEX_HTML)
    layout_css = _read(LAYOUT_CSS)
    components_css = _read(CHAT_CSS)

    assert 'id="setupProviderPickerBtn"' in index_html
    assert 'id="setupProviderMenu"' in index_html
    assert 'id="setupShowAllProviders"' not in index_html
    assert 'id="setupProfileMeta"' not in index_html

    assert ".model-select-wrapper {" in layout_css
    assert "justify-self: center;" in layout_css
    assert "width: fit-content;" in layout_css
    assert ".model-select-wrapper::before {" in layout_css
    assert "background:" in layout_css
    assert "mask-image: radial-gradient(ellipse at center" in layout_css
    assert "backdrop-filter: blur(22px) saturate(155%);" in layout_css
    assert "min-width: min(320px, calc(100vw - 136px));" not in layout_css
    assert "backdrop-filter: blur(14px) saturate(128%);" not in layout_css

    assert ".setup-provider-trigger {" in components_css
    assert ".setup-provider-trigger-state {" in components_css
    assert "display: none;" in components_css
    assert ".setup-provider-menu {" in components_css
    assert ".setup-provider-divider {" in components_css
    assert ".setup-provider-more {" in components_css
    assert '.setup-provider-option[data-state="inactive"] {' in components_css
    assert ".setup-provider-option-badge {" not in components_css
    assert "#modelSetupCurrentLabel {" in components_css
    assert ".model-setup-btn {" in components_css
    assert "background: transparent;" in components_css
