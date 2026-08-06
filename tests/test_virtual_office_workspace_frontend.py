import json
from pathlib import Path

from tests.web_ui_source import read_app_js_source

REPO_ROOT = Path(__file__).resolve().parents[1]
LAYOUT_DEBUG_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "layout_styles" / "layout-debug-panel.css"
VIRTUAL_OFFICE_CSS = REPO_ROOT / "thomas" / "server" / "web" / "css" / "virtual_office_workspace.css"
APP_RUNTIME_LOADER = REPO_ROOT / "thomas" / "server" / "web" / "js" / "app_runtime_loader.js"
RUNTIME_DIR = REPO_ROOT / "thomas" / "server" / "web" / "js" / "runtime"
OFFICE_AGENT_ELEMENT = RUNTIME_DIR / "office_agent_element.js"
OFFICE_AGENT_CHAT_PANELS = RUNTIME_DIR / "office_agent_chat_panels.js"
OFFICE_MAP_SCENE = RUNTIME_DIR / "office_map_scene.js"
OFFICE_MAP_VIEWPORT = RUNTIME_DIR / "office_map_state_viewport.js"
OFFICE_ASSET_DETAIL_RENDERER = RUNTIME_DIR / "office_asset_detail_renderer.js"
OFFICE_WORKSPACE_RUNTIME = RUNTIME_DIR / "022_virtual_office_06.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_virtual_office_mode_is_reinserted_by_runtime() -> None:
    js = read_app_js_source()
    assert "button.id = 'navOfficeBtn';" in js
    assert "setSidebarNavMode('office');" in js
    assert "Search office" in js
    assert "id: 'office'" in js


def test_virtual_office_runtime_contracts_are_committed_sources() -> None:
    map_js = _read(OFFICE_MAP_SCENE)
    chat_js = _read(OFFICE_AGENT_CHAT_PANELS)
    workspace_js = _read(OFFICE_WORKSPACE_RUNTIME)
    runtime_js = read_app_js_source()

    assert "function officeRenderDraftMapScene(options = {})" in map_js
    assert "officePopulateDraftGlobalAgentLayer(agentLayer, state, renderNow, initialAgentAssignments, 'scene');" in map_js
    assert "officeDraftCreateAssetElement(space, asset, state)" in map_js
    assert "officeDraftHandleAgentClick" in runtime_js
    assert "officeBindDraftAgentChatPanel(panel);" in chat_js
    assert "officeDraftPersistLayout(state);" in workspace_js
    assert "function officeStartMissionStream()" in runtime_js
    assert "const url = '/api/mission/stream?interval=1.8';" in runtime_js
    assert "Accept: 'application/x-ndjson'" in runtime_js


def test_virtual_office_initial_camera_frames_the_active_room_when_full_map_is_too_small() -> None:
    viewport_js = _read(OFFICE_MAP_VIEWPORT)

    assert "function officeDraftFocusSpaceZoom(space, viewport)" in viewport_js
    assert "function officeDraftApplyFocusedViewport(state, focusSpace, viewport)" in viewport_js
    assert "if (fitZoom >= OFFICE_DRAFT_LEGIBLE_MIN_ZOOM)" in viewport_js
    assert "if (officeDraftApplyFocusedViewport(state, focusSpace, viewport)) return;" in viewport_js
    assert "viewport.width < 640 ? 0.38 : (viewport.width < 900 ? 0.5 : 0.64)" in viewport_js
    assert "minimap as the whole-office navigator" in viewport_js


def test_split_runtime_loader_boots_after_all_office_chunks() -> None:
    loader = _read(APP_RUNTIME_LOADER)
    chunk_041 = _read(RUNTIME_DIR / "041_model_setup_settings_02.js")
    manifest = json.loads(_read(RUNTIME_DIR / "manifest.json"))

    assert "'044_model_setup_settings_05.js'," in loader
    assert "'048_ui_studio_canvas.js'," in loader
    assert "function bootstrapRuntime()" in loader
    assert "await bootstrapRuntime();" in loader
    assert "window.addEventListener('DOMContentLoaded', __thomasBootstrapApp" not in chunk_041
    assert "queueMicrotask(() => __thomasBootstrapApp());" not in chunk_041
    assert "044_model_setup_settings_05.js" in manifest
    assert manifest[-1] == "048_ui_studio_canvas.js"


def test_virtual_office_agent_selection_text_and_cosmetics_are_tight() -> None:
    js = read_app_js_source()
    css = _read(LAYOUT_DEBUG_CSS)

    assert "const densityAllowsNames = Math.max(1, Number(total) || 1) <= 3 || zoom >= 0.72;" in js
    assert "showName: focused || (densityAllowsNames && zoom >= OFFICE_DRAFT_AGENT_NAME_ZOOM)," in js
    assert (
        "const speechText = typeof officeVisibleSpeech === 'function' ? officeVisibleSpeech(agent, now) : safeString(agent?.speech);"
        in js
    )
    assert "const speechContext = activity === 'talking' || activity === 'paused' || activity === 'dropped';" in js
    assert "showBubble: Boolean(safeString(speechText) && speechContext)," in js
    assert 'data-office-draft-agent-selection="1"' not in js
    assert 'class="office-live-agent-name" data-office-draft-agent-name="1"' in js
    assert 'class="office-live-agent-bubble" data-office-draft-agent-bubble="1"' in js
    assert "el.className = 'office-live-agent';" in js
    assert "officeDraftSetStyleValue(el, 'zIndex', selected ? '80'" in js
    assert "const selectionEl = el.querySelector('[data-office-draft-agent-selection=\"1\"]');" not in js
    assert "transform:translateX(0) translateY(6px) scale(.92)" in js
    assert "transform:translateX(0) translateY(0) scale(1)" in js
    assert "const bubbleLeft = Number(placement.x) > (Number(space?.width) || 0) - 260;" in js
    assert "officeDraftSetStyleValue(bubbleEl, 'left', bubbleLeft ? 'auto' : '136px');" in js
    assert "officeDraftSetStyleValue(bubbleEl, 'right', bubbleLeft ? '136px' : 'auto');" in js
    assert 'class="office-live-agent-robot" data-office-draft-agent-robot="1"' in js

    pixel_agent_block = css[css.index(".office-pixel-agent {") : css.index(".office-pixel-agent.facing-left")]
    assert "display: block;" in pixel_agent_block
    headset_before = css[
        css.index(".office-pixel-agent.costume-headset::before") : css.index(
            ".office-pixel-agent.costume-headset::after"
        )
    ]
    assert "border-bottom" not in headset_before
    assert "border-radius: 22px 22px 0 0" not in headset_before
    assert "box-shadow:" in headset_before
    assert ".office-pixel-agent.costume-headset::after" in css


def test_virtual_office_modern_shell_uses_shared_chat_tokens_and_eyes_mark() -> None:
    css = _read(VIRTUAL_OFFICE_CSS)
    index = _read(REPO_ROOT / "thomas" / "server" / "web" / "index.html")

    assert "#officeWorkspace.office-modern-workspace" in css
    assert "color: var(--c-text);" in css
    assert "var(--c-bg)" in css
    assert "var(--c-sidebar)" in css
    assert "var(--c-border)" in css
    assert "var(--c-accent)" in css
    assert "color-mix(in srgb, var(--office-room-shell)" in css
    assert "color-mix(in srgb, var(--office-room-floor)" in css
    assert 'var(--font-sans, "Manrope", system-ui, sans-serif)' in css
    assert "#officeWorkspace .office-map-brand" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "/static/css/virtual_office_workspace.css?v=__THOMAS_WEB_BUILD__" in index
    for ui_id in (
        "virtual-office.shell",
        "virtual-office.stage",
        "virtual-office.map",
        "virtual-office.minimap",
        "virtual-office.action.follow",
    ):
        assert f'data-ui-id="{ui_id}"' in index


def test_virtual_office_live_ui_registers_stable_editor_contracts() -> None:
    agent_js = _read(OFFICE_AGENT_ELEMENT)
    asset_detail_js = _read(OFFICE_ASSET_DETAIL_RENDERER)
    chat_js = _read(OFFICE_AGENT_CHAT_PANELS)
    map_js = _read(OFFICE_MAP_SCENE)
    workspace_js = _read(OFFICE_WORKSPACE_RUNTIME)

    assert "el.dataset.uiId = 'virtual-office.agent';" in agent_js
    assert "el.dataset.uiInstanceKey = safeString(agent?.id);" in agent_js
    assert "el.dataset.uiPolicy = 'protected live-map-item';" in agent_js
    assert "part.className = 'office-asset-detail';" in asset_detail_js
    assert "var(--c-accent-line" in asset_detail_js
    assert "function officeDraftChatMessageInstanceKey(agentId, entry)" in chat_js
    assert "Math.abs(officeStableHash(seed)).toString(36)" in chat_js
    assert 'data-ui-id="virtual-office.chat-message"' in chat_js
    assert 'data-ui-instance-key="${escapeHtml(instanceKey)}"' in chat_js
    assert "id: 'virtual-office.agent-chat'" in chat_js
    assert "id: 'virtual-office.agent-roster'" in chat_js
    assert "id: 'virtual-office.asset'" in map_js
    assert "instanceKey: assetId" in map_js
    assert "id: 'virtual-office.room'" in map_js
    assert "id: 'virtual-office.map-toolbar'" in map_js
    assert "brandMark.className = 'thomas-eyes-mark office-map-brand';" in map_js
    assert "id: 'virtual-office.brand'" in map_js
    assert "policy: 'protected controls'" in map_js
    assert "officeWorkspace.dataset.uiId = 'virtual-office.shell';" in workspace_js
    assert "officeDebugToggleBtn.dataset.uiPolicy = 'protected controls';" in workspace_js
    assert "officeDebugOverlay.dataset.uiPolicy = 'protected critical-status';" in workspace_js


def test_virtual_office_draft_map_runtime_hooks_present() -> None:
    js = read_app_js_source()
    assert "const OFFICE_DRAFT_MAP_SIZE = 8400;" in js
    assert "const OFFICE_DRAFT_MAP_MIN_ZOOM = 0.12;" in js
    assert "const OFFICE_DRAFT_MINIMAP_SIZE = 220;" in js
    assert "const OFFICE_DRAFT_LAYOUT_STORAGE_KEY = 'thomas.office.draft.layout.v1';" in js
    assert "const OFFICE_DRAFT_AUTOSAVE_STORAGE_KEY = 'thomas.office.draft.autosave.v1';" in js
    assert "const OFFICE_RUNTIME_SCHEMA_VERSION = 2;" in js
    assert "const OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION = 19;" in js
    assert "const OFFICE_DRAFT_UNDO_LIMIT = 48;" in js
    assert "const OFFICE_DRAFT_ASSET_SCALE_OPTIONS = Object.freeze([0.6, 0.75, 0.9, 1, 1.15, 1.25]);" in js
    assert "const OFFICE_DRAFT_ASSET_RENDER_SCALE = 0.74;" in js
    assert "const OFFICE_DRAFT_ROOM_FLOOR_PALETTES = Object.freeze({" in js
    assert "const OFFICE_DRAFT_ASSET_LIBRARY = Object.freeze({" in js
    assert "const OFFICE_DRAFT_ASSET_COLORWAYS = Object.freeze({" in js
    assert "const OFFICE_MISSION_ROOM_TO_OFFICE_ROOM = Object.freeze({" in js
    assert (
        "const OFFICE_AGENT_COSTUME_POOL = ['none', 'cap', 'visor', 'headset', 'bowtie', 'toolbelt', 'satchel', 'scarf', 'badge', 'tablet', 'wrench', 'mug'];"
        in js
    )
    assert "const OFFICE_DRAFT_AGENT_NAV_VERSION = 13;" in js
    assert "const OFFICE_DRAFT_AGENT_ROUTE_EPSILON = 8;" in js
    assert "const OFFICE_DRAFT_AGENT_WAYPOINT_EPSILON = 14;" in js
    assert "const OFFICE_DRAFT_AGENT_OBSTACLE_MARGIN = 54;" in js
    assert "const OFFICE_DRAFT_AGENT_LOCAL_GRID_NODE_LIMIT = 900;" in js
    assert "const OFFICE_DRAFT_AGENT_HALLWAY_GRAPH_NODE_LIMIT = 700;" in js
    assert "const OFFICE_DRAFT_AGENT_STUCK_REPLAN_MS = 900;" in js
    assert "const OFFICE_DRAFT_AGENT_HARD_CLAMP_RETRY_MS = 1600;" in js
    assert "const OFFICE_DRAFT_AGENT_BLOCKED_TARGET_MS = 30000;" in js
    assert "const OFFICE_DRAFT_AGENT_WANDER_DWELL_MIN_MS = 4200;" in js
    assert "const OFFICE_DRAFT_AGENT_MANUAL_PIN_MS = 12500;" in js
    assert "const OFFICE_DRAFT_AGENT_ANIMATIONS = Object.freeze([" in js
    assert "function officePixelAgentMarkup(extraClass = '', inlineStyle = '')" in js
    assert "vending_machine: {" in js
    assert "workstation: {" in js
    assert "focus_pod: {" in js
    assert "reception_counter: {" in js
    assert "conference_table: {" in js
    assert "kitchen_island: {" in js
    assert "floor_sign: {" in js
    assert "phone_booth: {" in js
    assert "tea_station: {" in js
    assert "dual_monitor: {" in js
    assert "carpet: {" in js
    assert "terrazzo: {" in js
    assert "function officeDraftDefaultLayoutSnapshot()" in js
    assert "const OFFICE_DRAFT_DEFAULT_LAYOUT_OFFSET_SCALE = 0.74;" in js
    assert "const OFFICE_DRAFT_DEFAULT_ROOM_SCALE_BY_ID = Object.freeze({" in js
    assert "minWidth: 1180, minHeight: 780" in js
    assert "minWidth: 840, minHeight: 560" in js
    assert "lobby: { scaleX: 0.58, scaleY: 0.58, minWidth: 840, minHeight: 560, offsetScale: 0.76 }" in js
    assert "function officeDraftCompactDefaultSpace(space, options = {})" in js
    assert "const minWidth = Math.max(720, Math.min(1500, Number(options.minWidth) || 880));" in js
    assert "function officeDraftCompactDefaultLayoutSpaces(spacesRaw)" in js
    assert "const OFFICE_DRAFT_DEFAULT_UPRIGHT_ASSET_TYPES = new Set([" in js
    assert "const OFFICE_DRAFT_DEFAULT_LAYOUT_ASSET_OVERRIDES = Object.freeze({" in js
    assert "'mail_cart-242': { x: 245, y: 565 }" in js
    assert "'vending_machine-31': { x: 70, y: 155 }" in js
    assert "const OFFICE_DRAFT_DEFAULT_INTERACTION_CLEARANCE_TYPES = new Set([" in js
    assert "'vending_machine'" in js
    assert "function officeDraftDefaultAssetInteractionClearanceRects(asset, roomWidthRaw = 0, roomHeightRaw = 0)" in js
    assert "reservedRects.push(...officeDraftDefaultAssetInteractionClearanceRects(" in js
    assert "'couch-1': { x: 260, y: 385 }" in js
    assert "'focus_pod-38': { x: 115, y: 150 }" in js
    assert "'loveseat-255': { x: 300, y: 230 }" in js
    assert "'data_wall-270': { x: 330, y: 92 }" in js
    assert "'rug-264': { x: 255, y: 285 }" in js
    assert "'round_table-274': { x: 455, y: 405 }" in js
    assert "function officeDraftPolishDefaultLayoutSpaces(spacesRaw)" in js
    assert "const scanStepX = Math.max(86, Math.round(Number(dimensions.width || 0) * 0.68));" in js
    assert "scoreCandidates({ allowPlacedOverlap: false, allowReservedOverlap: true });" in js
    assert "scoreCandidates({ allowPlacedOverlap: true, allowReservedOverlap: true });" in js
    assert (
        "spaces: officeDraftFitSpacesToMapBounds(officeDraftPolishDefaultLayoutSpaces(officeDraftCompactDefaultLayoutSpaces(spaces)))"
        in js
    )
    assert "function officeDraftStoredLayoutIsLegacy(snapshotRaw)" in js
    assert "function officeDraftFitSpacesToMapBounds(spacesRaw)" in js
    assert "function officeEnsureDraftMapState()" in js
    assert "function officeDraftRoomPalette(paletteId)" in js
    assert "function officeDraftSelectedSpace()" in js
    assert "function officeDraftFindAsset(assetId)" in js
    assert "function officeDraftSpaceAtWorldPoint(worldX, worldY)" in js
    assert "function officeDraftRotationOptions()" in js
    assert "function officeDraftNormalizeRotation(value)" in js
    assert "function officeDraftSnap(value, gridSize, enabled = true)" in js
    assert "function officeDraftInitialFocusSpace(stateRaw = officeEnsureDraftMapState())" in js
    assert "function officeDraftAssetDefaultColorVariant(assetType)" in js
    assert "function officeDraftNormalizeRoomId(roomIdRaw, fallbackRaw = '')" in js
    assert "function officeDraftLoadStoredLayout()" in js
    assert "function officeDraftLoadAutosavePreference()" in js
    assert "function officeDraftSetAutosavePreference(enabledRaw, stateRaw = officeEnsureDraftMapState())" in js
    assert "function officeDraftPersistLayout(stateRaw = officeEnsureDraftMapState(), options = {})" in js
    assert "function officeDraftManualSaveLayout(event)" in js
    assert "function officeDraftApplySnapshot(snapshotRaw, stateRaw = officeEnsureDraftMapState(), options = {})" in js
    assert "function officeDraftCommitLayoutChange(previousSnapshot, stateRaw = officeEnsureDraftMapState())" in js
    assert "function officeDraftUndoLastChange(event)" in js
    assert "function officeDraftPlaceAssetInSpace(space, assetType, worldX, worldY, options = {})" in js
    assert "function officeDraftCreateCouchElement(space, asset, state)" in js
    assert "function officeDraftUseLightweightAssetRender(state, asset)" in js
    assert "function officeDraftAddAssetSurfaceDetail(root, scaled, baseWidthRaw, baseHeightRaw, color = {})" in js
    assert (
        "function officeDraftAddAssetPixelDetail(root, scaled, baseWidthRaw, baseHeightRaw, color = {}, typeRaw = '', shapeRaw = '')"
        in js
    )
    assert "function officeDraftAddAssetQualityOverlay(root, asset, state)" in js
    assert "root.dataset.officeAssetQualityDetail = '16px';" in js
    assert "if (type === 'rug' || shape === 'rug') {" in js
    assert "root.replaceChildren();" in js
    assert "function officeDraftDecorateLightweightAssetElement(root, type, shape, color, descriptor)" in js
    assert (
        "root.style.boxShadow = 'inset 0 2px 0 rgba(255,255,255,0.20), inset 0 -7px 12px rgba(0,0,0,0.18), 0 7px 12px rgba(2,8,18,0.18)';"
        in js
    )
    assert "officeDraftAddAssetSurfaceDetail(root, scaled, baseWidth, baseHeight, { accent, line });" in js
    assert (
        "officeDraftAddAssetPixelDetail(root, scaled, baseWidth, baseHeight, { accent, line, surface, body }, type, shape);"
        in js
    )
    assert "return officeDraftAddAssetQualityOverlay(element, asset, state);" in js
    assert "if (type === 'fridge') {" in js
    assert "} else if (type === 'data_wall') {" in js
    assert "} else if (type === 'map_table') {" in js
    assert "} else if (type === 'microscope') {" in js
    assert "} else if (type === 'focus_pod') {" in js
    assert "if (type === 'water_cooler') {" in js
    assert "if (type === 'microwave') {" in js
    assert "if (type === 'snack_shelf') {" in js
    assert "if (type === 'kitchen_island' || type === 'recipe_counter' || type === 'snack_table') {" in js
    assert "if (type === 'arcade_cabinet') {" in js
    assert "function officeDraftCreateLightweightAssetElement(space, asset, state)" in js
    assert "const lightweightVisualScale = zoom <= 0.2 ? 2.7 : (zoom <= 0.26 ? 2.25 : 1.72);" in js
    assert "root.dataset.officeDraftAssetLightweightScale = String(lightweightVisualScale);" in js
    assert "function officeDraftCreateAssetElement(space, asset, state)" in js
    assert "element.style.zIndex = '0';" in js
    assert "function officeDraftOverviewAssetKind(typeRaw, shapeRaw = '')" in js
    assert "function officeDraftOverviewAssetVisualSpec(typeRaw, shapeRaw, zoomRaw)" in js
    assert "function officeDraftCreateOverviewAssetDetail(root, kind, color = {})" in js
    assert "function officeDraftCreateOverviewAssetDots(space, assetsRaw = [], stateRaw = null)" in js
    assert "item.dataset.officeDraftOverviewAssetKind = spec.kind;" in js
    assert "officeDraftCreateOverviewAssetDetail(item, spec.kind, color);" in js
    assert "function syncModelSetupCurrentLabel({ force = false, profile = '' } = {})" in js
    assert "const placeholderLabels = new Set(['', 'loading...', 'model setup', 'connection & defaults']);" in js
    assert "if (typeof syncModelSetupCurrentLabel === 'function') syncModelSetupCurrentLabel({ force: true });" in js
    assert "function officeRenderDraftMapEditorPanel()" in js
    assert "function officeToggleDraftEditor(event)" in js
    assert "function officeDraftAddCatalogAsset(assetType)" in js
    assert "function officeDraftBeginCatalogPlacement(assetType, pointerId, clientX, clientY)" in js
    assert "function officePrepareDraftMapShell()" in js
    assert "function officeBindDraftMapControls()" in js
    assert "function officeHandleDraftMapClick(event)" in js
    assert "function officeHandleDraftMapWheel(event)" in js
    assert "function officeDraftMapInputActive()" in js
    assert "if (officeDraftMapInputActive()) return;" in js
    assert "function officeRenderDraftMapMinimap()" in js
    assert "function officeRenderDraftMapMinimapThrottled(force = false)" in js
    assert "function officeDraftMapWheelPassesThrough(event)" in js
    assert "if (officeDraftMapWheelPassesThrough(event)) return;" in js
    assert "event.deltaMode === 1 ? 14 : (event.deltaMode === 2 ? 120 : 1)" in js
    assert "Math.exp(-clampedDelta * 0.0009)" in js
    assert "officeApplyDraftMapTransform({ deferMinimap: true });" in js
    assert "function officeApplyDraftMapGridBackground(state, offsetX, offsetY)" in js
    assert "function officeToggleDraftMinimapMinimized(event)" in js
    assert "function officeHandleDraftMinimapPointerDown(event)" in js
    assert "function officeHandleDraftMinimapResizePointerDown(event)" in js
    assert "function officeDraftHomeRoomIdForAgent(agent)" in js
    assert "function officeDraftAgentEligibleForWander(agent, now = performance.now())" in js
    assert "function officeDraftEnsureAgentWanderTarget(agent, now = performance.now())" in js
    assert "function officeDraftChooseWanderSpace(agent, now = performance.now())" in js
    assert "agent.draftWanderSequence = sequence;" in js
    assert "stats.wanderTargets = (Number(stats.wanderTargets) || 0) + 1;" in js
    assert "function officeDraftSpaceForAgent(agent)" in js
    assert "if (!task && remoteRoomId === 'room-support' && homeRoomId !== 'room-support') return homeRoomId;" in js
    assert (
        "if (!task && officeDraftNormalizeRoomId(currentRoom?.id) === 'room-support' && homeRoomId !== 'room-support') return homeRoomId;"
        in js
    )
    assert "function officeDraftAgentAssignmentMap(state = officeEnsureDraftMapState())" in js
    assert "function officeDraftAgentCommandActive(agent, now = performance.now())" in js
    assert "function officeDraftMaybeCompleteAgentCommand(agent, now = performance.now())" in js
    assert "function officeDraftPushAgentOfficeMemory(agent, entryRaw = {})" in js
    assert "function officeDraftApplyAgentChatCommand(agent, textRaw)" in js
    assert "function officeDraftInferCommandActionFromInteraction(interactionRaw)" in js
    assert "function officeDraftCommandContainsAnyTerm(commandText, termsRaw = [])" in js
    assert "function officeDraftCommandAssetTerms(asset)" in js
    assert "function officeDraftAssetMatchesCommandText(asset, commandText)" in js
    assert "function officeDraftAgentCommandRuleScore(rule, commandText)" in js
    assert "score += 100 + Math.min(60, term.length * 3);" in js
    assert "OFFICE_DRAFT_AGENT_COMMAND_ASSET_RULES.forEach((rule, index) => {" in js
    assert "const OFFICE_DRAFT_AGENT_COMMAND_ASSET_RULES = Object.freeze([" in js
    assert (
        "terms: ['coke', 'cola', 'soda', 'pop', 'vending', 'vending machine', 'coke machine', 'soda machine', 'drink machine']"
        in js
    )
    assert "id: 'focus'," in js
    assert "terms: ['focus', 'focus pod', 'deep work', 'quiet pod', 'quiet room', 'concentrate', 'concentration']" in js
    assert "id: 'support'," in js
    assert "id: 'design'," in js
    assert "focus_pod: ['pod', 'quiet pod', 'deep work pod', 'focus booth']" in js
    assert "green_screen: ['backdrop', 'recording backdrop']" in js
    assert "microphone: ['mic', 'recording mic']" in js
    assert "network_switch: ['network box', 'switch']" in js
    assert "ticket_kiosk: ['ticket terminal', 'ticket station']" in js
    assert "workstation: ['computer', 'monitor', 'coding station']" in js
    assert "const OFFICE_DRAFT_AGENT_COMMAND_ROOM_ALIASES = Object.freeze({" in js
    assert "const explicitMatch = rule && officeDraftAssetMatchesAgentCommandRule(asset, rule);" in js
    assert "const labelMatch = officeDraftAssetMatchesCommandText(asset, commandText);" in js
    assert (
        "function officeDraftCommandAssetScore(asset, space, rule, commandText, spaceIndex, labelMatch = false)" in js
    )
    assert "if (labelMatch) score += 360;" in js
    assert "officeDraftCommandAssetScore(asset, space, rule, commandText, spaceIndex, labelMatch)" in js
    assert "const action = safeString(rule?.action) || officeDraftInferCommandActionFromInteraction(interaction);" in js
    assert "const commandResult = officeDraftApplyAgentChatCommand(agent, text);" in js
    assert "agent.lastOfficeChatCommandHandled = Boolean(commandResult);" in js
    assert "if (officeDraftAgentCommandActive(agent)) return base * 1.16;" in js
    assert (
        "function officeDraftAgentWalkPlacement(space, agent, index, total, now = performance.now(), targetAsset = null)"
        in js
    )
    assert (
        "function officeDraftSpreadAgentTargetPoint(space, pointRaw, index = 0, total = 1, seed = 0, obstaclesRaw = null)"
        in js
    )
    assert "function officeDraftLayerElementMap(layer)" in js
    assert "function officeDraftResolveAgentElementOverlaps(layer)" in js
    assert "if (node.dataset.officeAgentOverview === '1') return null;" not in js
    assert "item.node.dataset.officeAgentOverlapResolved = '1';" in js
    assert "item.node.style.setProperty('transition', 'none', 'important');" in js
    assert "function officeDraftClampResolvedAgentItemToSpace(item)" in js
    assert "function officeDraftSpreadDuplicateResolvedAgentItem(item, duplicateIndex = 1)" in js
    assert "if (globalLayer && item.node.dataset.officeAgentRouteActive === '1')" in js
    assert "const minX = 132;" in js
    assert "0(?:px)?\\)(.*)$/" in js
    assert (
        "function officeDraftUpdateAgentElement(el, space, agent, index, total, state, now = performance.now())" in js
    )
    assert "function officeDraftAgentPropLabel(agent)" in js
    assert "Current office action: ${commandLine}." in js
    assert "activeTask?.title || agent?.lastOfficeActionMemory" in js
    assert "officeBusEmit('agent.office_command_complete'" in js
    assert "officePersistRuntimeState(Number(now) || performance.now(), { force: true });" in js
    assert 'class="office-live-agent-can" data-office-draft-agent-can="1"' in js
    assert "officeDraftSetStyleValue(canEl, 'display', activity === 'drink' ? 'inline-flex' : 'none');" in js
    assert "function officeDraftAgentSocialLine(agent, space, index, total, activity, now = performance.now())" in js
    assert (
        "function officePopulateDraftGlobalAgentLayer(layer, state, now = performance.now(), assignmentsOverride = null, renderSource = 'direct')"
        in js
    )
    assert "function officeDraftMaybeFocusOccupiedRoom(state, assignments)" in js
    assert "function officeDraftCatalogIconMarkup(assetType, color = {})" in js
    assert "function officeRenderDraftAgentRosterPanel()" in js
    assert "function officeDraftSpaceDoorPoint(space, networkRaw = null)" in js
    assert "function officeDraftSpaceDoorInteriorPoint(space, networkRaw = null)" in js
    assert "function officeDraftAssetObstacleRect(space, asset, marginRaw = OFFICE_DRAFT_AGENT_OBSTACLE_MARGIN)" in js
    assert "const OFFICE_DRAFT_WALL_MOUNTED_ASSET_TYPES = new Set([" in js
    assert "'sticky_note_wall'" in js
    assert "'data_wall'" in js
    assert "if (OFFICE_DRAFT_WALL_MOUNTED_ASSET_TYPES.has(type)) return false;" in js
    assert "function officeDraftLineSegmentIntersectsRect(a, b, rect, padding = 0)" in js
    assert "function officeDraftPointObstacleClearance(point, obstaclesRaw = [])" in js
    assert "function officeDraftClampWorldPointToWalkable(pointRaw, space, obstaclesRaw = null)" in js
    assert "function officeDraftInitialMotionSpaceForAgent(agent, targetSpace)" in js
    assert "function officeDraftCheapAgentTargetWorldPoint(space, agent, index = 0, total = 1)" in js
    assert "function officeDraftSegmentClearInSpace(a, b, space, obstaclesRaw = null)" in js
    assert "function officeDraftFindOrthogonalLocalRoute(space, start, target, obstaclesRaw = null)" in js
    assert "const OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS = 18;" in js
    assert "function officeDraftRouteSolveDeadline(budgetMs = OFFICE_DRAFT_AGENT_ROUTE_SOLVE_BUDGET_MS)" in js
    assert "function officeDraftRouteDeadlineExceeded(deadlineRaw)" in js
    assert "function officeDraftFindLocalRoute(space, startRaw, targetRaw, obstaclesRaw = null, deadlineRaw = 0)" in js
    assert "if (xValues.length * yValues.length > OFFICE_DRAFT_AGENT_LOCAL_GRID_NODE_LIMIT)" in js
    assert "const previousSkipRoutePlanning = state.agentLayerSkipRoutePlanning;" in js
    assert "const skipRoutePlanning = previousSkipRoutePlanning === true;" in js
    assert "function officeDraftAssetApproachCandidates(space, asset, seed = 0, obstaclesRaw = null)" in js
    assert "function officeDraftAssetApproachAnchor(space, obstaclesRaw = null)" in js
    assert "function officeDraftChooseAssetApproachPoint(space, agent, targetAsset, seed = 0, options = {})" in js
    assert "const targetDims = officeDraftAssetDimensions(targetAsset.type, targetAsset.scale);" in js
    assert "const shouldRouteSearch = allowRouteSearch" in js
    assert "localRoute = officeDraftFindLocalRoute(space, anchor, point, obstacles, deadline);" in js
    assert "const assetDistance = Math.hypot(point.x - targetCenter.x, point.y - targetCenter.y);" in js
    assert "+ (Math.max(0, assetDistance - 230) * 8)" in js
    assert (
        "const directedActivity = state === 'working' || state === 'break' || intent === 'task' || intent === 'break';"
        in js
    )
    assert (
        "if (!directedActivity && !new Set(['room-coffee', 'room-break', 'room-pods']).has(roomId)) return null;" in js
    )
    assert "const primaryTypesByRoom = {" in js
    assert (
        "'room-engineering': ['workstation', 'desk', 'standing_desk', 'lab_bench', 'code_terminal', 'dual_monitor']"
        in js
    )
    assert "if (primaryAsset) return primaryAsset;" in js
    assert "if (!safeString(agent?.taskId)" in js
    assert "return targetWorld;" in js
    assert "const blockedTargetSignature = targetSignature;" in js
    assert "officeDraftRememberBlockedTarget(motion, blockedTargetSignature, currentNow);" in js
    assert "const slotIndex = Math.max(0, Math.min(totalAgents - 1, Number(index) || 0));" in js
    assert "const columns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(totalAgents))));" in js
    assert "function officeDraftRouteSegmentObstacleViolation(a, b, spacesRaw, networkRaw = null)" in js
    assert "function officeDraftAutoHallwayNetwork(spacesRaw)" in js
    assert "function officeDraftHallwayNetworkSignature(spacesRaw)" in js
    assert "cacheState.hallwayNetworkCache = { signature, network };" in js
    assert "hallwayNetworkCache: null" in js
    assert "missionAgentLayerDirty: false" in js
    assert "function officeDraftChooseVerticalConnectorX(laneA, laneB, rects)" in js
    assert "function officeDraftBuildHallwayRouteGraph(networkRaw, extraPointsRaw = [])" in js
    assert "if (pointByKey.size > OFFICE_DRAFT_AGENT_HALLWAY_GRAPH_NODE_LIMIT)" in js
    assert "function officeDraftFindHallwayRoute(networkRaw, fromRaw, toRaw, deadlineRaw = 0)" in js
    assert (
        "function officeDraftRouteBetweenWorldPoints(startWorldRaw, targetSpace, targetWorldRaw, networkRaw = null)"
        in js
    )
    assert (
        "function officeDraftAgentWorldPlacement(space, agent, index, total, now = performance.now(), targetAsset = null)"
        in js
    )
    assert (
        "if (skipRoutePlanning && cachedMotion && Number(cachedMotion.navVersion) === OFFICE_DRAFT_AGENT_NAV_VERSION"
        in js
    )
    assert "const cachedRouteActive = Array.isArray(cachedMotion.route)" in js
    assert "officeDraftAdvanceAgentMotion(agent, cachedMotion, currentNow);" in js
    assert "officeDraftAdvanceAgentCheapMotion(agent, cachedMotion, currentNow);" in js
    assert (
        "if (!routeStillActive && (cachedMotion.needsReplan === true || distanceToTarget > OFFICE_DRAFT_AGENT_ROUTE_EPSILON))"
        in js
    )
    assert "state.agentRoutePlanDeferred = true;" in js
    assert "const deferredTarget = officeDraftCheapAgentTargetWorldPoint(space, agent, index, total);" in js
    assert "targetX: deferredTarget.x" in js
    assert "targetY: deferredTarget.y" in js
    assert "targetSignature: `deferred:${safeString(space?.id)}:${deferredTarget.x},${deferredTarget.y}`" in js
    assert "needsReplan: true" in js
    assert "function officeDraftAgentAnimation(agent, activity, now = performance.now())" in js
    assert "function officeEnsureDraftAgentMotionStyles()" in js
    assert "function officeDraftHandleAgentClick(event, agentId)" in js
    assert (
        "function officeDraftRenderSingleAgentElement(agent, stateRaw = null, now = performance.now(), renderSource = 'single-agent')"
        in js
    )
    assert "function officeDraftHandleAgentPointerDown(event, agentId)" in js
    assert "function officeDraftHandleAgentPointerMove(event)" in js
    assert "function officeDraftHandleAgentPointerUp(event)" in js
    assert "officeDraftRenderSingleAgentElement(agent, state, performance.now(), 'agent-drag');" in js
    assert "agent.draftManualPinUntil = now + OFFICE_DRAFT_AGENT_MANUAL_PIN_MS;" in js
    assert "function officeDraftDrawMiniHallwayNetwork(ctx, network, scale)" in js
    assert "function officeDraftCorridorPath(from, to)" in js
    assert "function officeDraftViewportPadding(state)" in js
    assert "function officeDraftSpaceIntersectsViewport(space, viewportRaw, paddingRaw = 0)" in js
    assert "room.dataset.officeDraftDetail = renderDetailedSpace ? '1' : '0';" in js
    assert "room.appendChild(officeDraftCreateOverviewAssetDots(space, roomAssets, state));" in js
    assert "state.agentLayerSkipRoutePlanning = true;" in js
    assert "officeDraftScheduleDeferredRoutePlan(state, renderNow);" in js
    assert "const attachedAgentLayer = officeScene.querySelector('[data-office-draft-agent-layer=\"global\"]');" in js
    assert "officeDraftResolveAgentElementOverlaps(attachedAgentLayer);" in js
    assert "function officeRenderDraftRoomConnectors(plane, state)" in js
    assert "function officeDraftDebugSnapshot()" in js
    assert "function officeMissionRoomToOfficeRoomId(roomRaw, entry = {})" in js
    assert "function officeEnsureMissionAgent(entry, roomId, now = performance.now())" in js
    assert "function officeUpsertMissionTask(entry, agent, roomId, now = performance.now())" in js
    assert "function officeRefreshDraftMapAfterMissionChange(now = performance.now(), options = {})" in js
    assert "function officeMissionAgentAlreadyDraftRouting(agent, roomId, task)" in js
    assert "const draftAlreadyHeadingThere = officeMissionAgentAlreadyDraftRouting(agent, roomId, task);" in js
    assert "state.missionAgentLayerDirty = true;" in js
    assert "const missionDirty = state.missionAgentLayerDirty === true;" in js
    assert "'mission-stream-deferred'" in js
    assert "if (!force && (Number(now) || performance.now()) - lastAt < dynamicRenderInterval) return;" in js
    assert "state.missionAgentLayerDirty = false;" in js
    assert "officeRefreshDraftMapAfterMissionChange(now, { requiresSceneRender });" in js
    assert "translate3d(" in js
    assert "lastInputMode: safeString(state?.lastInputMode)" in js
    assert "lastPanDeltaScreen: Number(state?.lastPanDeltaScreen) || 0" in js
    assert "hallwaySegments: Number(network?.segments?.length) || 0" in js
    assert "hallwayDoors: Number(network?.doors?.size) || 0" in js
    assert "hallwayNodes: Number(network?.nodes?.length) || 0" in js
    assert "draftAgentRoutes: draftRoutes.length" in js
    assert "draftAgentWallViolations: draftRouteWallViolations.length" in js
    assert "draftAgentObstacleViolations: draftRouteObstacleViolations.length" in js
    assert "draftAgentNavVersion: OFFICE_DRAFT_AGENT_NAV_VERSION" in js
    assert "draftAgentWanderTargets: navStats.reduce((sum, stats) => sum + (Number(stats.wanderTargets) || 0), 0)" in js
    assert "draftAgentDragRenders: Number(state?.agentLayerRenderSources?.['agent-drag']) || 0" in js
    assert "draftAgentMaxJump: navStats.reduce((max, stats) => Math.max(max, Number(stats.maxJump) || 0), 0)" in js
    assert "draftAgentAnimationsAvailable: OFFICE_DRAFT_AGENT_ANIMATIONS.length" in js
    assert "Lounge" in js
    assert "Software Lab" in js
    assert "Cafeteria" in js
    assert "const OFFICE_DRAFT_LAYOUT_SCHEMA_VERSION = 19;" in js
    assert "roomId: 'room-engineering'" in js
    assert "floorPalette: 'terrazzo'" in js
    assert "rotation: 0" in js
    assert "assets: [" in js
    assert "agentLayer.dataset.officeDraftAgentLayer = 'global';" in js
    assert "pixelEl.style.setProperty('--agent-primary', palette.primary);" in js
    assert "couch: {" in js
    assert "officeScenePanzoom.style.setProperty('--office-zoom', '1');" in js
    assert "const focusSpace = officeDraftInitialFocusSpace(state);" in js
    assert "state.selectedSpaceId = safeString(focusSpace.id);" in js
    assert "const boundedSpaces = officeDraftFitSpacesToMapBounds(normalizedSpaces);" in js


def test_virtual_office_workspace_wires_editor_roster_and_agents() -> None:
    js = read_app_js_source()
    assert "officeWorkspace.remove();" not in js
    assert "officeEditorToggleBtn.style.display = 'none';" in js
    assert "officeWorkspace?.querySelector('.office-bottom-dock')" in js
    assert "mapToolbar.classList.add('office-map-toolbar');" in js
    assert "toolbarStatus.style.display = 'none';" in js
    assert "officeMinimap.style.height = `${state.minimapSize}px`;" in js
    assert (
        "officeMinimap.style.cursor = state.minimapLocked ? 'default' : (state.minimapPointerMode === 'panel' && state.minimapPointerId !== null ? 'grabbing' : 'default');"
        in js
    )
    assert 'data-office-minimap-lock="1"' in js
    assert "officeFollowToggleBtn.textContent = state.minimapMinimized ? 'Show' : 'Hide';" in js
    assert "Virtual office minimap showing the current camera window." in js
    assert "minimapBtn.textContent = 'Minimap';" in js
    assert "editorBtn.textContent = 'Layout';" in js
    assert "rosterBtn.textContent = 'Agent Roster';" in js
    assert "chatBtn.textContent = 'Chat';" in js
    assert "saveBtn.textContent = 'Save';" in js
    assert "editorToolbarBtn.textContent = 'Layout';" in js
    assert "rosterToolbarBtn.textContent = 'Agent Roster';" in js
    assert "chatToolbarBtn.textContent = 'Chat';" in js
    assert "undoBtn.textContent = 'Back';" in js
    assert "saveToolbarBtn.textContent = 'Save';" in js
    assert "undoToolbarBtn.textContent = 'Back';" in js
    assert "panel.dataset.officeEditorPanel = '1';" in js
    assert "panel.dataset.officeAgentRosterPanel = '1';" in js
    assert "panel.dataset.officeAgentChatPanel = '1';" in js
    assert "officeSceneWrap.addEventListener('click', officeHandleDraftMapClick);" in js
    assert "officeSceneWrap.addEventListener('mousemove', officeHandleDraftMapMouseMove, { passive: true });" in js
    assert "officeSceneWrap.setPointerCapture(event.pointerId);" in js
    assert "event.target.closest('input, select, textarea, [contenteditable=\"true\"]')" in js
    assert 'data-office-editor-catalog-asset="${escapeHtml(assetType)}"' in js
    assert 'data-office-catalog-icon="1"' in js
    assert 'data-office-editor-catalog-search="1"' in js
    assert 'data-office-editor-catalog-scroll="1"' in js
    assert 'data-office-editor-catalog-category="${escapeHtml(category)}"' in js
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in js
    assert "height:min(46vh,520px)" in js
    assert "overscroll-behavior:contain" in js
    assert "state.catalogScrollTop = Math.max(0, Math.round(Number(catalogScroll.scrollTop) || 0));" in js
    assert "draftState.catalogScrollTop = 0;" in js
    assert "state.catalogScrollTop = 0;" in js
    assert "editorPanel.classList.add('office-live-panel', 'office-layout-panel');" in js
    assert "Click and drag into a room to place a three-seat couch." in js
    assert "data-office-editor-rotation-step" in js
    assert 'data-office-editor-grid-toggle="1"' in js
    assert "${state.autosaveEnabled ? 'Autosave On' : 'Autosave Off'}" in js
    assert 'data-office-editor-autosave-toggle="1"' in js
    assert 'data-office-editor-save="1"' in js
    assert "Save Layout" in js
    assert "data-office-editor-asset-color" in js
    assert "data-office-editor-asset-scale" in js
    assert "costume-toolbelt" in js
    assert "officePixelAgentMarkup(costumeClass, paletteStyle)" in js
    assert "Select a placed asset to edit its color, change its scale, and rotate it with A / D." in js
    assert "A / D rotate selected asset" in js
    assert "space.floorPalette = safeString(floorBtn.dataset.officeEditorFloorPalette) || 'tan';" in js
    assert (
        "officeDraftBeginCatalogPlacement(catalogBtn.dataset.officeEditorCatalogAsset, event.pointerId, event.clientX, event.clientY);"
        in js
    )
    assert "state.gridEnabled = !state.gridEnabled;" in js
    assert "state.rotationStep = Number(rotationBtn.dataset.officeEditorRotationStep) || 15;" in js
    assert "state.catalogPendingType = safeString(assetType);" in js
    assert "room.appendChild(officeDecorateDraftAssetUiNode(officeDraftCreateAssetElement(space, previewAsset, state), space, previewAsset));" in js
    assert "id: 'catalog-preview'" in js
    assert "colorVariant: officeDraftAssetDefaultColorVariant(pendingType)" in js
    assert "officeSceneWrap.style.cursor = 'copy';" in js
    assert "officeSceneWrap.style.cursor = 'not-allowed';" in js
    assert "const assetId = `${pendingType}-${state.nextAssetId++}`;" in js
    assert "state.catalogPendingType = '';" in js
    assert "officeDraftPersistLayout(state);" in js
    assert "officeDraftPersistLayout(state, { force: true });" in js
    assert "officeDraftCommitLayoutChange(previousSnapshot, state);" in js
    assert "officeDraftSetAutosavePreference(state.autosaveEnabled === false, state);" in js
    assert "officeDraftManualSaveLayout(event);" in js
    assert "officeDraftUndoLastChange(event);" in js
    assert "officeToggleDraftAgentRoster(event);" in js
    assert "officeToggleDraftAgentChat(event);" in js
    assert "function officeRenderDraftAgentChatPanel(options = {})" in js
    assert "async function officeDraftSendAgentChatMessage(agentIdRaw = '')" in js
    assert "function officeDraftAgentChatSessionId(agent)" in js
    assert "function officeDraftAgentChatModelLabel(agent)" in js
    assert "const providerLabel = profile && typeof formatProviderDisplay === 'function'" in js
    assert "if (providerLabel && modelId) return `${providerLabel} - ${modelId}`;" in js
    assert "function officeDraftJoinAgentChatChunks(chunksRaw = [])" in js
    assert "function officeDraftBuildAgentChatRequestPayload(agent, userTextRaw)" in js
    assert "async function officeDraftRequestAgentChatReply(agent, userTextRaw)" in js
    assert "const chatEndpoint = '/api/v2/chat';" in js
    assert "payload.session_id = officeDraftAgentChatSessionId(agent);" in js
    assert "payload.office_agent_chat = {" in js
    assert "payload.model_id = modelId || undefined;" in js
    assert "officeDraftAgentChatFallbackReply" not in js
    assert "officeHandleMention(agent, mentionText)" not in js
    assert "officeDraftOpenAgentChat(agent.id, { prime: false });" in js
    assert 'data-office-agent-chat-input="1"' in js
    assert 'data-office-agent-chat-send="1"' in js
    assert "Thinking...</div>" in js
    assert "Waiting on ${escapeHtml(chatModelLabel)}" not in js
    assert "chatPanel.classList.add('office-live-panel');" in js
    assert 'class="office-chat-log" data-office-agent-chat-log="1"' in js
    assert 'class="office-field" data-office-agent-chat-input="1" rows="3"' in js
    assert 'data-office-roster-field="chatProfile"' in js
    assert 'data-office-roster-field="chatModelId"' in js
    assert "if (target.closest('[data-office-agent-chat-panel=\"1\"]')) return true;" in js
    assert "if (event.target.closest('[data-office-agent-chat-panel=\"1\"]')) return;" in js
    assert 'data-office-roster-field="specialty"' in js
    assert 'data-office-roster-field="personality"' in js
    assert "data-office-draft-connectors" in js
    assert "data-office-draft-hallway-path" in js
    assert "shadow.setAttribute('data-office-draft-hallway-path', 'shadow');" in js
    assert "curb.setAttribute('data-office-draft-hallway-path', 'curb');" in js
    assert "lane.setAttribute('data-office-draft-hallway-path', 'lane');" in js
    assert "data-office-draft-hallway-node" in js
    assert "data-office-draft-door-pad" in js
    assert "const network = officeDraftAutoHallwayNetwork(spaces);" in js
    assert "officeDraftDrawMiniHallwayNetwork(ctx, network, scale);" in js
    assert "const network = officeDraftAutoHallwayNetwork(state.spaces);" in js
    assert 'data-office-draft-agent-bubble="1"' in js
    assert 'data-office-draft-agent-status="1"' in js
    assert 'data-office-draft-agent-prop="1"' in js
    assert "function officeDraftSetDatasetValue(el, key, value)" in js
    assert "function officeDraftSetStyleValue(el, prop, value)" in js
    assert "function officeDraftSetCssVariable(el, name, value)" in js
    assert "officeDraftSetDatasetValue(el, 'officeAgentAnimation', animation);" in js
    assert "officeDraftSetDatasetValue(el, 'officeAgentRouteActive', placement.routeActive ? '1' : '0');" in js
    assert "officeDraftPauseAgentForUser(agent, space, performance.now());" in js
    assert "agent.draftPinnedRoomId = roomId;" in js
    assert "officeDraftRouteBetweenWorldPoints(startWorld, space, targetWorld, network);" in js
    assert (
        "function officeDraftFastRouteBetweenWorldPoints(startWorldRaw, targetSpace, targetWorldRaw, networkRaw = null)"
        in js
    )
    assert "if (safeString(officeEnsureDraftMapState()?.agentRoutePlanningSource) === 'route-plan')" in js
    assert (
        "return officeDraftFastRouteBetweenWorldPoints(startWorldRaw, targetSpace, targetWorldRaw, networkRaw);" in js
    )
    assert "officeDraftFindLocalRoute(startSpace, startWorld, targetWorld, null, deadline)" in js
    assert "const localExit = officeDraftFindLocalRoute(startSpace, startWorld, startInterior, null, deadline);" in js
    assert (
        "const localEntry = officeDraftFindLocalRoute(targetSpace, targetInterior, targetWorld, null, deadline);" in js
    )
    assert "const OFFICE_DRAFT_AGENT_LOCAL_CANDIDATE_LIMIT = 76;" in js
    assert "const OFFICE_DRAFT_AGENT_LOCAL_EDGE_LIMIT = 1400;" in js
    assert "const OFFICE_DRAFT_AGENT_DEBUG_SEGMENT_LIMIT = 180;" in js
    assert "const OFFICE_DRAFT_AGENT_SPEED_MIN = 22;" in js
    assert "const OFFICE_DRAFT_AGENT_SPEED_MAX = 58;" in js
    assert "const OFFICE_DRAFT_AGENT_SPEED_SCALE = 18;" in js
    assert "const OFFICE_DRAFT_AGENT_RENDER_INTERVAL_MS = 48;" in js
    assert "const OFFICE_DRAFT_AGENT_RENDER_BACKOFF_MAX_MS = 180;" in js
    assert "const OFFICE_DRAFT_AGENT_LAYER_CHUNK_BUDGET_MS = 18;" in js
    assert "const OFFICE_DRAFT_AGENT_ROUTE_PLANS_PER_RENDER = 1;" in js
    assert "const OFFICE_DRAFT_AGENT_INPUT_RENDER_INTERVAL_MS = 96;" in js
    assert "const OFFICE_DRAFT_AGENT_POINTER_QUIET_MS = 340;" in js
    assert "const OFFICE_DRAFT_AGENT_ROUTE_PLAN_INPUT_QUIET_MS = 900;" in js
    assert "const OFFICE_DRAFT_AGENT_NAME_ZOOM = 0.44;" in js
    assert "const OFFICE_DRAFT_AGENT_STATUS_ZOOM = 0.88;" in js
    assert "const OFFICE_DRAFT_AGENT_PROP_ZOOM = 0.78;" in js
    assert (
        "function officeDraftAgentUiVisibility(state, agent, activity, selected, now = performance.now(), total = 1)"
        in js
    )
    assert "function officeDraftAdvanceAgentCheapMotion(agent, motion, now = performance.now())" in js
    assert "function officeDraftConsumeRoutePlanBudget(stateRaw = null)" in js
    assert "function officeDraftScheduleDeferredRoutePlan(stateRaw = null, now = performance.now())" in js
    assert "function officeDraftInputMotionRenderAllowed(state, now = performance.now())" in js
    assert "const routePlanningSource = new Set(['route-plan', 'agent-chat-command']).has(sourceKey);" in js
    assert "const previousRoutePlanningSource = state.agentRoutePlanningSource;" in js
    assert "state.agentRoutePlanningSource = sourceKey;" in js
    assert "state.agentRoutePlanningSource = previousRoutePlanningSource || '';" in js
    assert "const previousSkipRoutePlanning = state.agentLayerSkipRoutePlanning;" in js
    assert "if (!routePlanningSource || state.agentLayerQuietMotionRender === true)" in js
    assert "state.agentLayerSkipRoutePlanning = previousSkipRoutePlanning === true;" in js
    assert (
        "state.agentRoutePlansRemaining = (skipRoutePlanning || state.agentLayerQuietMotionRender === true || !routePlanningSource)"
        in js
    )
    assert "function officeDraftAgentHasPendingRoutePlan(agent, nowRaw = performance.now())" in js
    assert "const routePlanPendingAgents = sourceKey === 'route-plan'" in js
    assert "state.agentRoutePlanCursor = routePlanPendingAgents.length" in js
    assert "const OFFICE_DRAFT_AGENT_ROUTE_PLAN_MIN_INTERVAL_MS = 1600;" in js
    assert "const OFFICE_DRAFT_AGENT_ROUTE_PLAN_BOOT_QUIET_MS = 2800;" in js
    assert "renderNow + OFFICE_DRAFT_AGENT_ROUTE_PLAN_BOOT_QUIET_MS" in js
    assert "if (state.agentRoutePlanDeferred)" in js
    assert "officeDraftScheduleDeferredRoutePlan(state, currentNow);" in js
    assert "state.agentLayerQuietMotionRender = quietMotionRender;" in js
    assert "officeDraftAdvanceAgentCheapMotion(agent, cachedMotion, currentNow);" in js
    assert "const dynamicRenderInterval = previousRenderCost > OFFICE_DRAFT_AGENT_RENDER_OVERLOAD_MS" in js
    assert "state.agentLayerRenderCursor = (startCursor + normalProcessed) % Math.max(1, normalAgents.length);" in js
    assert "const priorityAgentIds = new Set([" in js
    assert "source: 'agent-layer-chunk'" in js
    assert "quietMotionRender ? 'quiet-motion' : source" in js
    assert "&& state?.agentLayerQuietMotionRender !== true" in js
    assert "state.agentRoutePlanDeferred = routeDeferred || routePlanHasMoreAgents;" in js
    assert "agentRoutePlanDeferred: false" in js
    assert "const clicked = clickedAt > 0 && clickedAt + 6600 > (Number(now) || performance.now());" in js
    assert "function officeDraftAgentRenderQuietActive(state, now = performance.now())" in js
    assert "function officeDraftSceneRenderQuietActive(state, now = performance.now())" in js
    assert "function officeDraftRoutePlanQuietActive(state, now = performance.now())" in js
    assert "function officeHandleDraftMapMouseMove(event)" in js
    assert "function officeDraftCancelAgentHoverRender(stateRaw = null)" in js
    assert "officeDraftCancelAgentHoverRender(state);" in js
    assert "window.clearTimeout(state.agentRoutePlanTimer);" in js
    assert "function officeDraftScheduleSceneRenderAfterInput(state, now = performance.now())" in js
    assert "function officeDraftFlushSceneOrAgentLayerAfterInput(state, source)" in js
    assert "if (state.agentFocusInitialized === true) return false;" in js
    assert "if (officeDraftSceneRenderQuietActive(state, timerNow))" in js
    assert "if ((Number(state.agentLayerQuietUntil) || 0) > currentNow) return true;" in js
    assert (
        "if ((currentNow - (Number(state.lastPointerIntentAt) || 0)) < OFFICE_DRAFT_AGENT_POINTER_QUIET_MS) return true;"
        in js
    )
    assert "if ((Number(state.routePlanQuietUntil) || 0) > currentNow) return true;" in js
    assert "state.agentLayerQuietUntil = state.lastWheelAt + OFFICE_DRAFT_AGENT_WHEEL_QUIET_MS + 80;" in js
    assert "state.routePlanQuietUntil = state.lastWheelAt + OFFICE_DRAFT_AGENT_ROUTE_PLAN_INPUT_QUIET_MS;" in js
    assert "state.agentLayerQuietUntil = state.lastPanAt + OFFICE_DRAFT_AGENT_PAN_QUIET_MS + 80;" in js
    assert "if (state.sceneRenderDeferred) {" in js
    assert "if (source === 'route-plan' && officeDraftRoutePlanQuietActive(state, now))" in js
    assert "const quietActive = !force && officeDraftAgentRenderQuietActive(state, now);" in js
    assert "if (quietActive && !quietMotionRender) return;" in js
    assert "if (options?.force !== true && officeDraftSceneRenderQuietActive(state, renderNow))" in js
    assert "state.agentLayerRenderCount = (Number(state.agentLayerRenderCount) || 0) + 1;" in js
    assert (
        "state.agentLayerRenderSources[sourceKey] = (Number(state.agentLayerRenderSources[sourceKey]) || 0) + 1;" in js
    )
    assert "state.agentLayerForceRender = force;" in js
    assert "const agentTarget = event.target.closest('[data-office-draft-agent-id]');" in js
    assert "officeDraftHandleAgentPointerDown(event, agentTarget.dataset.officeDraftAgentId);" in js
    assert "state.panSettleTimer = window.setTimeout(() => {" in js
    assert "officeDraftFlushSceneOrAgentLayerAfterInput(state, 'pan-settle');" in js
    assert "state.wheelSettleTimer = window.setTimeout(() => {" in js
    assert "officeDraftFlushSceneOrAgentLayerAfterInput(state, 'wheel-settle');" in js
    assert "currentState.agentHoverRenderTimer = window.setTimeout(() => {" in js
    assert "source: 'hover-leave'" not in js
    assert "edgeCandidates.slice(0, OFFICE_DRAFT_AGENT_LOCAL_EDGE_LIMIT)" in js
    assert "draftRouteSegmentsChecked >= OFFICE_DRAFT_AGENT_DEBUG_SEGMENT_LIMIT" in js
    assert "draftAgentRouteSegmentsChecked" in js
    assert "function officeDraftStepInsideDoorCorridor" in js
    assert "function officeDraftStepOnHallway" in js
    assert "if (officeDraftStepOnHallway(current, next)) return next;" in js
    assert "const eased = [0.75, 0.5, 0.33, 0.2].find((factor) => {" in js
    assert "if (officeDraftStepInsideDoorCorridor(space, current, next)) return next;" in js
    assert "if (officeDraftStepOnHallway(a, b, network)) return null;" in js
    target_signature = js[
        js.index("function officeDraftAgentTargetSignature") : js.index("function officeDraftConstrainAgentStep")
    ]
    assert "safeString(agent?.intent)" not in target_signature
    target_world = js[
        js.index("function officeDraftAgentTargetWorldPoint") : js.index("function officeDraftRouteBetweenWorldPoints")
    ]
    assert "|target|${index}" not in target_world
    assert "const seed = officeStableHash(`${safeString(space?.id)}|${safeString(agent?.id)}|target`);" in target_world
    assert (
        "const approach = officeDraftChooseAssetApproachPoint(space, agent, targetAsset, seed, { routeAware });"
        in target_world
    )
    assert (
        "if (approach) return officeDraftSpreadAgentTargetPoint(space, approach, index, total, seed);" in target_world
    )
    pause_handler = js[
        js.index("function officeDraftPauseAgentForUser") : js.index("function officeDraftHandleAgentClick")
    ]
    assert "agent.state = 'yield';" not in pause_handler
    assert "agent.intent = 'talk';" not in pause_handler
    assert "agent.draftInteractionIntent = 'talk';" in pause_handler
    click_handler = js[
        js.index("function officeDraftHandleAgentClick") : js.index("function officeDraftAgentMotionForDrag")
    ]
    assert (
        "officeRenderDraftAgentLayerOnly(performance.now(), { force: true, source: 'agent-click' });" in click_handler
    )
    assert "officeRenderDraftMapScene();" not in click_handler
    assert "if (officeDraftHandleAgentPointerMove(event)) return;" in js
    assert "if (officeDraftHandleAgentPointerUp(event)) return;" in js
    assert (
        "function officeDraftNearestAgentIdAtClient(clientXRaw, clientYRaw, maxDistanceRaw = 82, preferredAgentIdRaw = '')"
        in js
    )
    assert "const preferredAgentId = safeString(preferredAgentIdRaw);" in js
    assert "const score = distance - (agentId && agentId === preferredAgentId ? maxDistance + 1000 : 0);" in js
    assert "const nearbyAgentId = officeDraftNearestAgentIdAtClient(event.clientX, event.clientY);" in js
    map_pointer_down = js[
        js.index("function officeHandleDraftMapPointerDown") : js.index("function officeHandleDraftMapPointerMove")
    ]
    assert "const preferredAgentId = safeString(state.hoveredAgentId);" in map_pointer_down
    assert "preferredAgentId ? 124 : 56" in map_pointer_down
    assert "preferredAgentId," in map_pointer_down
    assert "officeDraftHandleAgentPointerDown(event, nearbyAgentId);" in map_pointer_down
    assert "pointer-events: auto !important;" in js
    agent_pointer_down = js[
        js.index("function officeDraftHandleAgentPointerDown") : js.index(
            "function officeDraftClampAgentDropPointToSpace"
        )
    ]
    assert "officeSceneWrap.setPointerCapture(event.pointerId);" in agent_pointer_down
    assert "officeDraftHandleAgentClick(event, safeString(agentId));" not in agent_pointer_down
    assert "state.suppressAgentClickUntil = performance.now() + 320;" not in agent_pointer_down
    agent_pointer_up = js[
        js.index("function officeDraftHandleAgentPointerUp") : js.index("function officeDraftCreateAgentElement")
    ]
    assert "officeSceneWrap.releasePointerCapture(event.pointerId);" in agent_pointer_up
    assert "officeDraftHandleAgentClick(event, safeString(agent.id));" in agent_pointer_up
    assert "state.suppressAgentClickUntil = performance.now() + 320;" in agent_pointer_up
    assert "state.suppressAgentClickUntil = performance.now() + 320;" in js
    assert "const initialAgentAssignments = officeDraftAgentAssignmentMap(state);" in js
    assert "officePopulateDraftGlobalAgentLayer(agentLayer, state, renderNow, initialAgentAssignments, 'scene');" in js
    assert "if (officeState) officeState.lastDraftAgentRenderAt = renderNow;" in js
    assert (
        "officePopulateDraftGlobalAgentLayer(layer, state, now, assignments, quietMotionRender ? 'quiet-motion' : source);"
        in js
    )
    assert "if (officeDraftMaybeFocusOccupiedRoom(state, assignments)) return;" in js
    assert "state.agentFocusInitialized = true;" in js
    assert "state.userSelectedSpace = true;" in js
    assert "if (!state || state.userSelectedSpace === true) return false;" in js
    assert "officeDraftSetDatasetValue(el, 'officeAgentActivity', activity);" in js
    assert "officeDraftSetDatasetValue(el, 'officeAgentLabelVisible', visibility.showName ? '1' : '0');" in js
    assert "officeDraftSetStyleValue(nameEl, 'display', visibility.showName ? 'block' : 'none');" in js
    assert "officeDraftSetStyleValue(statusEl, 'display', visibility.showStatus ? 'block' : 'none');" in js
    assert "officeDraftSetStyleValue(propEl, 'display', visibility.showProp ? 'flex' : 'none');" in js
    assert "const bubbleText = visibility.showBubble ? speech : '';" in js
    assert "return 'with team';" in js
    assert "'room-support': ['I can take that.', 'Reply drafted.', 'Ticket triaged.']" in js
    assert "Coke" in js
    assert "const OFFICE_DRAFT_MOTION_TIMER_MS = 48;" in js
    assert "const OFFICE_DRAFT_MOTION_MAX_PAINT_GAP_MS = 260;" in js
    assert "function officeDraftMapLoopActive()" in js
    assert "function officeEnsureDraftMotionTimer()" in js
    assert "function officeStopDraftMotionTimer()" in js
    assert "function officeTickDraftMotionFrame(frameNow, wallNow)" in js
    assert "function officeDraftOverviewMode(state)" in js
    assert "function officeDraftCreateOverviewAssetDots(space, assetsRaw = [], stateRaw = null)" in js
    assert "layer.dataset.officeDraftOverviewAssets = '1';" in js
    assert "room.dataset.officeDraftOverview = overviewMode ? '1' : '0';" in js
    assert '[data-office-agent-overview="1"]' in js
    assert "contain: layout style;" in js
    assert "contain: layout style paint;" not in js
    assert "pointer-events: auto !important;" in js
    assert "const overviewAgent = officeDraftOverviewMode(state)" in js
    assert "officeDraftSetDatasetValue(el, 'officeAgentOverview', overviewAgent ? '1' : '0');" in js
    assert "if (overviewAgent) {" in js
    assert (
        "officeDraftSetStyleValue(el, 'transform', `translate3d(${Math.round(offsetX + placement.x - 24)}px, ${Math.round(offsetY + placement.y - 24)}px, 0)`);"
        in js
    )
    assert "if (zoom <= 0.32)" in js
    assert "const draftTimer = Boolean(options.draftTimer);" in js
    assert "if (draftTimer) {" in js
    assert "function officeTickDraftAgentTaskStates(now)" in js
    assert "function officeTickDraftAgentTaskState(agent, now)" in js
    assert "function officeDraftMotionPaintFresh(now = performance.now())" in js
    assert "function officeEnsureDraftPerformanceStyles()" in js
    assert "office-draft-performance-styles" in js
    assert "document.body.classList.toggle('office-active', isOffice);" in js
    assert "body.office-active #te-space-root" in js
    assert "display: none !important;" in js
    assert '#officeWorkspace [data-office-map-plane="1"] *' in js
    assert "root.dataset.officeDraftAssetLightweight = '1';" in js
    assert "if (officeDraftUseLightweightAssetRender(state, asset))" in js
    assert "animation: none !important;" in js
    assert "box-shadow: none !important;" in js
    assert "filter: none !important;" in js
    assert "officeEnsureDraftPerformanceStyles();" in js
    assert "currentWallNow - lastPaintWall > OFFICE_DRAFT_MOTION_MAX_PAINT_GAP_MS" in js
    assert "if (!officeDraftMotionPaintFresh(currentNow))" in js
    assert "if (lastTickAt && currentFrameNow - lastTickAt < OFFICE_DRAFT_MOTION_TIMER_MS) return;" in js
    assert "const dt = officeClamp((currentWallNow - lastWall) / 1000, 0.01, 0.12);" in js
    assert "officeTick(currentFrameNow, dt, { background: false, draftTimer: true });" in js
    assert "officeTickDraftAgentTaskStates(now);" in js
    assert "officeState.lastDraftOfficeTickAt = currentFrameNow;" in js
    assert "const draftMapActive = typeof officeDraftMapPlane === 'function' && officeDraftMapPlane();" in js
    assert "const draftMapActive = officeDraftMapLoopActive();" in js
    assert "officeState.lastDraftMotionPaintWallAt = wallNow;" in js
    assert "officeState.lastDraftMotionPaintAt = frameNow;" in js
    assert "officeEnsureDraftMotionTimer();" in js
    assert "officeTickDraftMotionFrame(frameNow, wallNow);" in js
    assert "officeStopDraftMotionTimer();" in js
    assert "if ((event.ctrlKey || event.metaKey) && safeString(event.key).toLowerCase() === 'z')" in js
    assert "colorVariant: 'caramel'" in js
    assert "scale: 1" in js
    assert "'software-lab': { scaleX: 0.64, scaleY: 0.62, minWidth: 1180, minHeight: 780" in js
    assert "cafeteria: { scaleX: 0.62, scaleY: 0.58, minWidth: 1040, minHeight: 760" in js
    assert "'support-desk': { scaleX: 0.6, scaleY: 0.6, minWidth: 900, minHeight: 680" in js
    assert "officeMinimap.addEventListener('pointerdown', officeHandleDraftMinimapPointerDown);" in js
    assert "resizeHandle.setAttribute('aria-label', 'Resize minimap');" in js
    assert "officeConfigureDynamicUi(resizeHandle, {" in js
    assert "if (state.minimapRenderTimer) return;" in js
    assert "roomLabel.className = 'office-room-label';" in js
    assert "room.className = 'office-live-room';" in js
    assert "top: 58px;" in _read(VIRTUAL_OFFICE_CSS)
    assert "action: 'food'," in js
    assert "action: 'print'," in js
    assert "action: 'charge'," in js
    assert "action: 'monitor'," in js
    assert "action: 'record'," in js
    assert "function officeDraftAgentCommandVerb(agent, actionRaw)" in js
    assert "if (action === 'drink') return `${grabbed(prop, 'drink')} at`;" in js
    assert "if (action === 'charge') return 'plugged into';" in js
    assert "['work', 'research', 'print', 'charge', 'monitor', 'record'].includes(action)" in js
    assert "if (activity === 'drink') {" in js


def test_virtual_office_legacy_standalone_duplicates_are_removed() -> None:
    web_root = REPO_ROOT / "thomas" / "server" / "web"
    for relative_path in (
        "virtual_office.html",
        "virtual_office.script01_part01.js",
        "virtual_office.script01_part02.js",
        "virtual_office.style01.css",
        "static/virtual_office.html",
        "static/virtual_office.script01_part01.js",
        "static/virtual_office.script01_part02.js",
        "static/virtual_office.style01.css",
    ):
        assert not (web_root / relative_path).exists(), relative_path
