from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_JS = ROOT / "thomas" / "server" / "web" / "js" / "app_runtime_primary.mjs"
TASK_CSS = ROOT / "thomas" / "server" / "web" / "css" / "components_parts" / "part-005a.css"
MISSION_CSS = ROOT / "thomas" / "server" / "web" / "css" / "layout_parts" / "part-002.css"
SIDEBAR_CSS = ROOT / "thomas" / "server" / "web" / "css" / "layout_parts" / "part-001a.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mission_runtime_panel_and_stream_contract() -> None:
    js = _read(RUNTIME_JS)
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


def test_chat_presence_alert_is_disabled() -> None:
    js = _read(RUNTIME_JS)
    task_css = _read(TASK_CSS)
    mission_css = _read(MISSION_CSS)
    sidebar_css = _read(SIDEBAR_CSS)

    assert "const TASK_CONTINUITY_REFRESH_INTERVAL_MS = 2800;" in js
    assert "async function fetchTaskContinuitySessionActivity(" in js
    assert "function ensureTaskContinuityRuntimeUi(" in js
    assert "function syncTaskContinuityPanelVisibility(" in js
    assert "function removeChatAgentPresenceUi()" in js
    assert "function ensureChatAgentPresenceUi()" in js
    assert "root.remove();" in js
    assert "function chatAgentPresenceShouldBeVisible()" in js
    assert "function setChatAgentPresence(activity)" in js
    assert "void activity;" in js
    assert "Click to inspect delegated work" not in js
    assert ".task-continuity-panel {" in task_css
    assert ".chat-agent-presence {" in task_css
    assert "display: none !important;" in task_css
    assert ".mission-runtime-panel.is-focused {" in mission_css
    assert ".nav-item::before {" in sidebar_css
    assert "display: none;" in sidebar_css
    assert ".nav-item.active::before {" in sidebar_css
    assert "animation: none;" in sidebar_css
