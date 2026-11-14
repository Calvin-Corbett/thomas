from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MISSION_ROUTE_PATH = ROOT / "thomas" / "server" / "routes" / "mission.py"
SYSTEM_JS_PATH = ROOT / "thomas" / "server" / "web" / "js" / "system_page.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_system_page_uses_canonical_apis_and_a_bounded_refresh() -> None:
    text = _read(SYSTEM_JS_PATH)
    assert "'/api/mission/control'" in text
    assert "`/api/mission/jobs/${encodeURIComponent(target.dataset.job)}/${target.dataset.verb}`" in text
    assert "setInterval(() => { if (!document.hidden) void refresh(); }, 5000);" in text
    for obsolete in ("'/api/missions'", "'/api/agents'", "'/api/approvals'"):
        assert obsolete not in text


def test_mission_routes_register_core_control_and_autopilot_endpoints() -> None:
    mission_dir = MISSION_ROUTE_PATH.parent
    text = "\n".join(
        (mission_dir / module_name).read_text(encoding="utf-8")
        for module_name in (
            "mission.py",
            "mission_tasks.py",
            "mission_cron.py",
            "mission_approvals.py",
            "mission_workflows.py",
            "mission_control_routes.py",
            "mission_benchmark_routes.py",
        )
        if (mission_dir / module_name).is_file()
    )
    for path in (
        "/api/mission/control",
        "/api/mission/stream",
        "/api/mission/jobs",
        "/api/mission/jobs/{job_id}/cancel",
        "/api/mission/autopilot/objectives",
        "/api/mission/benchmarks/run",
    ):
        assert f'"{path}"' in text, f"Missing route: {path}"
    assert "register_mission_routes(" in _read(MISSION_ROUTE_PATH)
