from __future__ import annotations

from pathlib import Path

from tests.web_ui_source import read_app_js_source


ROOT = Path(__file__).resolve().parents[1]
MISSION_ROUTE_PATH = ROOT / "thomas" / "server" / "routes" / "mission.py"
MISSION_HTML_PATH = ROOT / "thomas" / "server" / "web" / "mission.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mission_page_contains_operator_controls() -> None:
    text = _read(MISSION_HTML_PATH)
    assert "Mission Control" in text
    assert "Open Office" in text
    assert "Show Idle" in text
    assert "Agent Activity" in text


def test_mission_routes_register_core_control_and_autopilot_endpoints() -> None:
    text = _read(MISSION_ROUTE_PATH)

    required_paths = (
        "/mission",
        "/api/mission/control",
        "/api/mission/stream",
        "/api/mission/jobs",
        "/api/mission/jobs/{job_id}/cancel",
        "/api/mission/autopilot/objectives",
        "/api/mission/benchmarks/run",
    )
    for path in required_paths:
        assert f'"{path}"' in text

    assert "register_mission_routes(" in text


def test_runtime_includes_mission_refresh_and_stream_wiring() -> None:
    text = read_app_js_source()
    assert "async function missionRefresh" in text
    assert "fetch('/api/mission/control')" in text
    assert "/api/mission/stream?interval=1.8" in text
    assert "Mission Control refresh failed." in text
    assert "void missionRefresh({ force: true, silent: true });" in text
