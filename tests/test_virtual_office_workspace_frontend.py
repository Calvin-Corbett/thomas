from pathlib import Path

from tests.web_ui_source import read_app_js_source, read_layout_css_source

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = REPO_ROOT / "thomas" / "server" / "web" / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_virtual_office_keyboard_and_a11y_controls_present() -> None:
    text = _read(INDEX_HTML)
    assert 'id="officeMinimapCanvas"' in text
    assert 'aria-label="Office minimap. Click or drag to pan the camera."' in text
    assert 'aria-label="Virtual office map. Drag to pan, use wheel to zoom, or use arrow keys for keyboard panning."' in text
    assert 'id="officeZoomOutBtn"' in text
    assert 'aria-label="Zoom out"' in text
    assert 'aria-label="Zoom in"' in text
    assert 'aria-label="Reset zoom to fit"' in text


def test_virtual_office_robot_editor_and_quick_actions_present() -> None:
    html = _read(INDEX_HTML)
    js = read_app_js_source()
    assert 'id="officeEditorModal"' in html
    assert 'id="officeAgentSelect"' in html
    assert 'id="officeAgentNameInput"' in html
    assert 'id="officeAgentColorInput"' in html
    assert 'id="officeAgentCostumeSelect"' in html
    assert 'id="officeActionSummonBtn"' in html
    assert 'id="officeActionBreakBtn"' in html
    assert 'id="officeActionResumeBtn"' in html
    assert "function officeRunQuickAction(actionRaw)" in js
    assert "officeRunQuickAction('summon');" in js
    assert "officeRunQuickAction('break');" in js
    assert "officeRunQuickAction('resume');" in js
    assert "if (action.startsWith('focus:')) {" in js


def test_virtual_office_camera_persistence_hooks_present() -> None:
    text = read_app_js_source()
    assert "const OFFICE_CAMERA_STORAGE_KEY = 'thomas.ui.office.camera.v1';" in text
    assert "function loadStoredOfficeCameraState()" in text
    assert "function saveStoredOfficeCameraState(snapshot)" in text
    assert "function officePersistCameraState(" in text
    assert "officePersistCameraState(now);" in text


def test_virtual_office_walkability_and_lane_reservation_logic_present() -> None:
    text = read_app_js_source()
    assert "function officeIsWalkablePoint(x, y)" in text
    assert "function officeConstrainWalkableMove(agent, fromX, fromY, toX, toY)" in text
    assert "function officeTickLaneReservations(now)" in text
    assert "officeTickLaneReservations(now);" in text
    assert "function officePointInRoomDoorThreshold(room, x, y)" in text


def test_virtual_office_traffic_and_stuck_recovery_hooks_present() -> None:
    text = read_app_js_source()
    assert "function officeComputeAgentAvoidance(agent)" in text
    assert "function officeHandleAgentStuck(agent, now)" in text
    assert "function officeSetYieldState(agent, now, awayX = 0, awayY = 0)" in text


def test_virtual_office_reduced_motion_support_present() -> None:
    app_text = read_app_js_source()
    css_text = read_layout_css_source()
    assert "function officeSyncReducedMotionPreference()" in app_text
    assert "prefers-reduced-motion: reduce" in app_text
    assert "prefers-contrast: more" in app_text
    assert ".office-workspace.reduced-motion" in css_text
    assert ".office-workspace.high-contrast" in css_text


def test_virtual_office_debug_overlay_and_event_bus_hooks_present() -> None:
    html = _read(INDEX_HTML)
    js = read_app_js_source()
    css = read_layout_css_source()
    assert 'id="officeDebugToggleBtn"' in html
    assert 'id="officeDebugOverlay"' in html
    assert "function officeRenderDebugOverlay(" in js
    assert "function officeBusEmit(" in js
    assert "function officeBusSubscribe(" in js
    assert ".office-debug-overlay" in css


def test_virtual_office_layout_and_agent_persistence_hooks_present() -> None:
    js = read_app_js_source()
    assert "const OFFICE_LAYOUT_STORAGE_KEY = 'thomas.ui.office.layout.v1';" in js
    assert "const OFFICE_AGENT_PREFS_STORAGE_KEY = 'thomas.ui.office.agent_prefs.v1';" in js
    assert "function loadStoredOfficeLayoutState()" in js
    assert "function saveStoredOfficeLayoutState(snapshot)" in js
    assert "function loadStoredOfficeAgentPrefs()" in js
    assert "function saveStoredOfficeAgentPrefs(snapshot)" in js
    assert "function officePersistLayoutState()" in js
    assert "function officePersistAgentPrefs()" in js
    assert "function officeSanitizeDynamicRoomSnapshot(roomRaw, index = 0)" in js


def test_virtual_office_runtime_persistence_and_background_tick_hooks_present() -> None:
    js = read_app_js_source()
    assert "const OFFICE_RUNTIME_STORAGE_KEY = 'thomas.ui.office.runtime.v1';" in js
    assert "function loadStoredOfficeRuntimeState()" in js
    assert "function saveStoredOfficeRuntimeState(snapshot)" in js
    assert "function officeCollectRuntimeSnapshot(now = performance.now())" in js
    assert "function officeApplyRuntimeSnapshot(snapshotRaw, now = performance.now())" in js
    assert "function officePersistRuntimeState(now = performance.now(), { force = false } = {})" in js
    assert "function officeEnsureBackgroundTickTimer()" in js
    assert "document.addEventListener('visibilitychange'" in js


def test_virtual_office_sprite_atlas_rendering_hooks_present() -> None:
    js = read_app_js_source()
    assert "function officeBuildSpriteAtlas()" in js
    assert "function officeGetSpriteAtlas()" in js
    assert "function officeRoomThemeFloorSprite(themeRaw)" in js
    assert "function officePaintSpriteFill(ctx, atlas, spriteId, x, y, w, h, tileSize = 20, opacity = 0.34)" in js


def test_virtual_office_touch_gesture_and_haptic_hooks_present() -> None:
    js = read_app_js_source()
    css = read_layout_css_source()
    assert "function officeTouchGestureDown(event)" in js
    assert "function officeTouchGestureMove(event)" in js
    assert "function officeTouchGestureEnd(event)" in js
    assert "navigator.vibrate" in js
    assert "event.pointerType === 'touch'" in js
    assert "touch-action: none;" in css


def test_virtual_office_persona_social_and_mentions_hooks_present() -> None:
    js = read_app_js_source()
    assert "const OFFICE_PERSONA_LIBRARY = {" in js
    assert "function officeBanterForAgent(agent, contextRaw = 'ambient', detail = {})" in js
    assert "function officeTickSocialIdle(now)" in js
    assert "function officeTickBreakSchedules(now)" in js
    assert "function officeParseMentionCommand(messageRaw)" in js


def test_virtual_office_task_priority_routing_hooks_present() -> None:
    js = read_app_js_source()
    assert "function officeTaskPriorityScore(task)" in js
    assert "function officeAgentTaskFitScore(agent, task)" in js
    assert ".sort((a, b) => officeTaskPriorityScore(b) - officeTaskPriorityScore(a));" in js
    assert "officeAssignTaskToAgent(nextTask, agent, now);" in js


def test_virtual_office_stream_and_reconcile_hooks_present() -> None:
    js = read_app_js_source()
    assert "function officeStartMissionStream()" in js
    assert "function officeStopMissionStream()" in js
    assert "function officeScheduleMissionStreamReconnect(delayMs = 0)" in js
    assert "function officeReconcileFromMissionPayload(payload, now = performance.now())" in js
    assert "function officeHandleMissionStreamLine(lineRaw)" in js
    assert "const url = '/api/mission/stream?interval=1.8';" in js
