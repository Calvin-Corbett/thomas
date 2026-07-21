from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MISSION_ROUTE_PATH = ROOT / "thomas" / "server" / "routes" / "mission.py"
MISSION_HTML_PATH = ROOT / "thomas" / "server" / "web" / "mission.html"
MISSION_CSS_PATH = ROOT / "thomas" / "server" / "web" / "mission.style01.css"
MISSION_JS_PATH = ROOT / "thomas" / "server" / "web" / "mission.script01.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mission_page_uses_modern_shell_and_shared_edit_runtime() -> None:
    text = _read(MISSION_HTML_PATH)
    assert "Thomas Mission Control" in text
    assert "Mission pulse" in text
    assert "Live work" in text
    assert "Mission queue" in text
    assert "Recent signals" in text
    assert 'class="thomas-eyes-mark"' in text
    assert "data-thomas-theme-select" in text
    for theme in ("nebula", "dark", "light", "aurora", "sandstone"):
        assert f'value="{theme}"' in text

    assets = (
        "/static/css/workspace_shell.css",
        "/static/css/ui_edit_mode.css",
        "/static/js/workspace_shell.js",
        "/static/js/ui_edit_layout.js",
        "/static/js/ui_edit_mode.js",
    )
    positions = [text.index(asset) for asset in assets]
    assert positions == sorted(positions)


def test_mission_runtime_uses_canonical_apis_and_bounded_refresh() -> None:
    text = _read(MISSION_JS_PATH)
    assert "const STREAM_URL = '/api/mission/stream?interval=3'" in text
    assert "const JOBS_REFRESH_MS = 15000" in text
    assert "const FALLBACK_REFRESH_MS = 8000" in text
    assert "`/api/mission/control${fresh ? '?fresh=1' : ''}`" in text
    assert "'/api/mission/jobs?limit=180'" in text
    assert "/api/mission/approvals/autonomy/" in text
    assert "/api/mission/approvals/guardrails/resolve" in text
    for obsolete in ("'/api/missions'", "'/api/agents'", "'/api/approvals'"):
        assert obsolete not in text


def test_mission_regions_register_editable_and_protected_contracts() -> None:
    html = _read(MISSION_HTML_PATH)
    script = _read(MISSION_JS_PATH)
    for ui_id in (
        "mission.workspace",
        "mission.hero",
        "mission.pulse",
        "mission.metrics",
        "mission.create-panel",
        "mission.live-work",
        "mission.jobs",
        "mission.approvals",
        "mission.activity",
    ):
        assert f'data-ui-id="{ui_id}"' in html
    assert 'data-ui-policy="protected controls"' in html
    assert "critical=true;preserveHandlers=true;preserveA11y=true" in html
    assert 'data-ui-instance-key="${escapeHtml(key)}"' in script
    assert 'data-ui-id="mission.${escapeHtml(type)}.${escapeHtml(key)}"' in script
    assert "contain=parent;container=${escapeHtml(container)};collision=avoid" in script
    for dynamic_id in ("agent-card", "job-card", "approval-card", "signal-card"):
        assert f"instanceAttrs('{dynamic_id}'" in script
    assert "protectedAttrs('job-actions'" in script
    assert "protectedAttrs('approval-actions'" in script
    assert "preserveHandlers=true;preserveA11y=true" in script


def test_mission_styles_cover_themes_embed_and_source_caps() -> None:
    css = _read(MISSION_CSS_PATH)
    shared_css = _read(ROOT / "thomas" / "server" / "web" / "css" / "workspace_shell.css")
    for theme in ("dark", "light", "aurora", "sandstone"):
        assert f'html[data-thomas-theme="{theme}"]' in shared_css
    assert "--c-bg:" not in css
    assert ".thomas-eyes-mark" not in css
    assert "html.is-embedded .mission-chrome" in css
    assert "html.is-embedded .mission-world { display: none !important; }" in css
    assert "html.is-embedded body { background: var(--c-bg); }" not in css
    assert "html.is-embedded .mission-app { background: transparent !important; }" in css
    assert "html.is-embedded { color-scheme: normal !important; }" in css
    assert len(css.splitlines()) <= 600
    assert len(_read(MISSION_JS_PATH).splitlines()) <= 800
    assert len(_read(MISSION_HTML_PATH).splitlines()) <= 1000


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
        "/mission",
        "/api/mission/control",
        "/api/mission/stream",
        "/api/mission/jobs",
        "/api/mission/jobs/{job_id}/cancel",
        "/api/mission/autopilot/objectives",
        "/api/mission/benchmarks/run",
    ):
        assert f'"{path}"' in text, f"Missing route: {path}"
    assert "register_mission_routes(" in _read(MISSION_ROUTE_PATH)
