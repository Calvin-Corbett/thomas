from __future__ import annotations

from pathlib import Path

from tests.web_ui_source import read_app_js_source

ROOT = Path(__file__).resolve().parents[1]
MISSION_ROUTE_PATH = ROOT / "thomas" / "server" / "routes" / "mission.py"
MISSION_HTML_PATH = ROOT / "thomas" / "server" / "web" / "mission.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mission_page_contains_operator_controls() -> None:
    # mission.html was rebuilt around the new operator vocabulary: missions,
    # agents, approvals, and activity. The legacy "Open Office" / "Show Idle"
    # buttons were retired with the surface refresh — the test now asserts
    # the still-present labels that gate the same operator workflows.
    text = _read(MISSION_HTML_PATH)
    assert "Mission Control" in text
    assert "Active Agents" in text
    assert "Approvals Queue" in text
    assert "Activity Feed" in text


def test_mission_routes_register_core_control_and_autopilot_endpoints() -> None:
    # After the modular refactor (mission.py is now a facade over
    # mission_tasks/mission_cron/mission_approvals/mission_workflows/
    # mission_benchmark_routes/mission_control_routes), the route literals are
    # spread across the sibling files. Concatenate them all so the contract
    # still asserts every required path is registered *somewhere* in the
    # mission stack.
    mission_dir = MISSION_ROUTE_PATH.parent
    text_chunks: list[str] = []
    for module_name in (
        "mission.py",
        "mission_tasks.py",
        "mission_cron.py",
        "mission_approvals.py",
        "mission_workflows.py",
        "mission_control_routes.py",
        "mission_benchmark_routes.py",
    ):
        candidate = mission_dir / module_name
        if candidate.is_file():
            text_chunks.append(candidate.read_text(encoding="utf-8"))
    text = "\n".join(text_chunks)

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
        assert f'"{path}"' in text, f"Missing route: {path}"

    # The facade still owns `register_mission_routes` (the public entry).
    assert "register_mission_routes(" in _read(MISSION_ROUTE_PATH)


def test_runtime_includes_mission_refresh_and_stream_wiring() -> None:
    text = read_app_js_source()
    assert "async function missionRefresh" in text
    assert "fetch('/api/mission/control')" in text
    assert "/api/mission/stream?interval=1.8" in text
    assert "Mission Control refresh failed." in text
    assert "void missionRefresh({ force: true, silent: true });" in text
