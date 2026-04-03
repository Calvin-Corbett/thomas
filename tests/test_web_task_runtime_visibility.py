from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
TASK_CSS = ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "part-005a.css"
MISSION_CSS = ROOT / "thomas" / "server" / "web" / "css" / "layout_parts" / "part-002.css"
SIDEBAR_CSS = ROOT / "thomas" / "server" / "web" / "css" / "layout_parts" / "part-001a.css"
MOTION_PROOF_SCRIPT = ROOT / "scripts" / "capture_chat_motion_proof.mjs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_all_runtime_js() -> str:
    """Read and concatenate all split runtime JS files in order."""
    if not RUNTIME_DIR.exists():
        return ""
    parts = sorted(RUNTIME_DIR.glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in parts)


def test_mission_runtime_panel_and_stream_contract() -> None:
    js = _read_all_runtime_js()
    mission_css = _read(MISSION_CSS)

    assert "function renderMissionRuntimeHero(" in js
    assert "function missionHandleStreamLine(" in js
    assert "async function missionStartStream(" in js
    assert "missionStartStream();" in js
    assert "missionStopStream();" in js
    assert "const MISSION_STREAM_URL = '/api/mission/stream?interval=1.2';" in js
    assert "Current Task" in js
    assert "Delegated agents" in js
    assert ".mission-runtime-panel {" in mission_css
    assert ".mission-runtime-progress-rail {" in mission_css
    assert ".mission-runtime-task {" in mission_css
    assert "function missionCreateUnavailableReason(" in js
    assert "function missionSyncCreateAvailability(" in js
    assert "Jobs unavailable ·" in js
    assert "Mission runtime unavailable:" in js
    assert "creation unavailable:" in js


def test_chat_presence_runtime_uses_platform_graph_and_motion_debug() -> None:
    js = _read_all_runtime_js()
    task_css = _read(TASK_CSS)
    mission_css = _read(MISSION_CSS)
    sidebar_css = _read(SIDEBAR_CSS)
    proof_script = _read(MOTION_PROOF_SCRIPT)

    assert "const TASK_CONTINUITY_REFRESH_INTERVAL_MS = 2800;" in js
    assert "async function fetchTaskContinuitySessionActivity(" in js
    assert "function ensureTaskContinuityRuntimeUi(" in js
    assert "function syncTaskContinuityPanelVisibility(" in js
    assert "function removeChatAgentPresenceUi()" in js
    assert "function chatWorldEnsureUi()" in js
    assert "function chatRobotWorldBuildPlatformGraph(" in js
    assert "function chatRobotWorldFindRoute(" in js
    assert "function chatRobotWorldRunDebugScenario(" in js
    assert "function chatRobotWorldSpawnDebugHelper(" in js
    assert "function chatRobotWorldSyncDebugState(" in js
    assert "function chatRobotWorldDetailLine(" in js
    assert "function delegationRowIsRenderableLive(" in js
    assert "function officePixelAgentMarkup(" in js
    assert "function chatWorldCurrentMode(" in js
    assert "function chatPhysicsWorldPrime(" in js
    assert "function chatPhysicsWorldAdvanceActor(" in js
    assert "function chatPhysicsWorldRebuildStatics(" in js
    assert "function chatPhysicsWorldStablePlatformForState(" in js
    assert "function chatPhysicsWorldSnapActorsToStableSurfaces(" in js
    assert "__THOMAS_CHAT_WORLD_DEBUG__" in js
    assert "CHAT_WORLD_MODE_PHYSICS" in js
    assert "advanced_chat_physics" in js
    assert "worldMode: chatWorldCurrentMode()" in js
    assert "bodyVelocityX" in js
    assert "function setChatAgentPresence(activity)" in js
    assert "Open Office" in js
    assert "assistant-inline-thinking-status" in js
    assert "physicsNeedsSnap" in js
    assert "${officePixelAgentMarkup()}" in js
    assert ".task-continuity-panel {" in task_css
    assert ".chat-robot-world {" in task_css
    assert ".chat-robot-world-physics {" in task_css
    assert ".assistant-inline-thinking-status {" in task_css
    assert ".chat-robot-world-route.route-door {" in task_css
    assert ".chat-robot-world-route.route-ladder {" in task_css
    assert ".chat-robot-world-route.route-lift" in task_css
    assert ".mission-runtime-panel.is-focused {" in mission_css
    assert ".nav-item::before {" in sidebar_css
    assert "display: none;" in sidebar_css
    assert ".nav-item.active::before {" in sidebar_css
    assert "animation: none;" in sidebar_css
    assert "globalThis.__THOMAS_CHAT_WORLD_DEBUG__?.getSnapshot?.()" in proof_script
    assert "motion-proof.json" in proof_script
    assert "motion-proof.html" in proof_script
    assert "--scenario" in proof_script
    assert "--physics" in proof_script
    assert "worldMode" in proof_script
    assert "runScenario" in js
    assert "labelCenterOffsetPx" in js
    assert "visualCenterOffsetPx" in js
    assert ".office-pixel-agent, .chat-robot-agent" in js
    assert "if (state.exiting) return;" in js
    assert "propKind" in js
    assert "chatAgentPresenceUpsert(specId, {" in js
    assert "window.setTimeout(() => {" in js
    assert "propKinds" in proof_script
    assert "maxLabelDriftPx" in proof_script
