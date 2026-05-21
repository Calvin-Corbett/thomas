from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / "thomas" / "server" / "web" / "js" / "runtime"
CHAT_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "chat-game-animations.css"
SUGGESTION_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "easy-setup-ui.css"
LAYOUT_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "layout_parts" / "layout-app-shell.css"
ROBOT_STATUS_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "tool-calls-chat.css"
ROBOT_DOCK_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "chat-robot-animations.css"
ROBOT_PORTAL_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "robot-portal-animations.css"
BRAIN_PY = REPO_ROOT / "thomas" / "marketplace" / "orchestrator" / "brain.py"
COMPONENT_ICON_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "composer-attachments.css"
INDEX_HTML = REPO_ROOT / "thomas" / "server" / "web" / "index.html"
TOGGLE_SIDEBAR_MODULE = REPO_ROOT / "thomas" / "server" / "web" / "js" / "modules" / "060_togglesidebarcollapsed.js"
TOGGLE_SIDEBAR_RUNTIME_MODULE = (
    REPO_ROOT / "thomas" / "server" / "web" / "js" / "src" / "runtime_modules" / "060_togglesidebarcollapsed.js"
)


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
    modules = [_read(TOGGLE_SIDEBAR_MODULE), _read(TOGGLE_SIDEBAR_RUNTIME_MODULE)]

    assert '<span class="nav-chat-robot-wrap"' not in index_html
    assert ".nav-chat-robot-wrap {" in components_css
    assert "display: none !important;" in components_css
    assert all("const stripNavChatRobot = () => {" in content for content in modules)
    assert all(
        "label.querySelectorAll('.nav-chat-robot-wrap, .nav-chat-robot, .pixel-agent').forEach((node) => node.remove());"
        in content
        for content in modules
    )

    assert ".sidebar-search-input-wrap input {" in layout_css
    assert "background: transparent !important;" in layout_css
    assert "border: 0 !important;" in layout_css
    assert "border-radius: 0 !important;" in layout_css
    assert "appearance: none;" in layout_css
    assert "-webkit-appearance: none;" in layout_css
    assert "navChatBtn.addEventListener('click', (event) => {" in js
    assert "setChatListExpanded(!chatListExpanded);" in js
    assert "if (globalSearchInput) globalSearchInput.focus();" not in js


def test_chat_robot_uses_shared_pixel_agent_markup() -> None:
    js = _read_all_runtime_js()
    status_css = _read(ROBOT_STATUS_CSS)
    dock_css = _read(ROBOT_DOCK_CSS)

    assert "landed.className = 'chat-robot-landed pixel-agent pixel-agent-blue';" in js
    assert 'class="chat-robot-agent chat-robot-world-agent"' in js
    assert 'class="office-agent-head"' in js
    assert 'class="office-agent-body"' in js
    assert 'class="office-agent-leg office-agent-leg-left"' in js

    assert ".chat-robot-agent .agent-head {" in status_css
    assert ".chat-robot-agent .agent-body {" in status_css
    assert ".chat-robot-agent .agent-leg {" in status_css
    assert ".chat-robot-landed .agent-head {" in dock_css
    assert ".chat-robot-landed .agent-body {" in dock_css
    assert ".chat-robot-landed .agent-leg {" in dock_css


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
