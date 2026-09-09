from __future__ import annotations

from pathlib import Path

from thomas.core.ui_workflow_engine import UIWorkflowEngine


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_ui_workflow_engine_audit_detects_token_and_motion_issues(tmp_path: Path) -> None:
    _write(
        tmp_path / "css" / "tokens.css",
        ":root { --surface-bg: #0a0a0a; --spacing-md: 16px; }",
    )
    _write(
        tmp_path / "css" / "layout.css",
        ".layout { background: var(--surface-bg); padding: var(--spacing-md); }",
    )
    _write(
        tmp_path / "css" / "components.css",
        """
.btn {
  color: #ff00ff;
  background: var(--missing-token);
  animation: pulse 600ms linear infinite;
}
@keyframes pulse { from { opacity: 0.6; } to { opacity: 1; } }
""",
    )
    _write(tmp_path / "js" / "app.js", "console.log('ui app');")
    _write(tmp_path / "index.html", "<html><body><main><section>Test</section></main></body></html>")

    engine = UIWorkflowEngine(
        ui_root=tmp_path,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )
    report = engine.audit_ui_consistency()

    assert int(report.get("unresolved_token_count") or 0) >= 1
    assert int(report.get("hardcoded_color_count") or 0) >= 1
    assert int(report.get("animation_count") or 0) >= 1
    assert int(report.get("reduced_motion_mentions") or 0) == 0
    assert int(report.get("warning_count") or 0) >= 2
    assert int(report.get("score") or 0) < 100


def test_ui_workflow_engine_search_assets_aggregates_and_dedupes() -> None:
    engine = UIWorkflowEngine(
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )

    engine._search_openverse = lambda q, limit: (  # type: ignore[method-assign]
        [
            {
                "provider": "openverse",
                "id": "ov-1",
                "title": "Openverse Hero",
                "thumbnail_url": "https://cdn.example/ov-thumb.jpg",
                "asset_url": "https://cdn.example/shared.jpg",
                "source_url": "https://openverse.org/image/ov-1",
                "creator": "openverse-user",
                "license": "CC-BY",
            }
        ],
        {"provider": "openverse", "ok": True, "count": 1},
    )
    engine._search_unsplash = lambda q, limit: (  # type: ignore[method-assign]
        [
            {
                "provider": "unsplash",
                "id": "un-1",
                "title": "Unsplash Hero",
                "thumbnail_url": "https://images.unsplash.com/un-1-small.jpg",
                "asset_url": "https://cdn.example/shared.jpg",
                "source_url": "https://unsplash.com/photos/un-1",
                "creator": "unsplash-user",
                "license": "Unsplash License",
            },
            {
                "provider": "unsplash",
                "id": "un-2",
                "title": "Unsplash Alt",
                "thumbnail_url": "https://images.unsplash.com/un-2-small.jpg",
                "asset_url": "https://images.unsplash.com/un-2-full.jpg",
                "source_url": "https://unsplash.com/photos/un-2",
                "creator": "unsplash-user-2",
                "license": "Unsplash License",
            },
        ],
        {"provider": "unsplash", "ok": True, "count": 2},
    )

    report = engine.search_assets("hero gradient", limit=5, providers=["openverse", "unsplash"])

    assert report.get("ok") is True
    assert int(report.get("count") or 0) == 2
    providers = list(report.get("providers") or [])
    assert len(providers) == 2
    assets = list(report.get("assets") or [])
    assert len(assets) == 2
    ids = {str(item.get("id") or "") for item in assets if isinstance(item, dict)}
    assert "ov-1" in ids
    assert "un-2" in ids


def test_ui_workflow_engine_list_effects_filtering() -> None:
    engine = UIWorkflowEngine(
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )
    all_effects = engine.list_effects()
    motion = engine.list_effects(category="motion")
    assert len(all_effects) >= 5
    assert len(motion) >= 1
    assert all(str(item.get("category") or "") == "motion" for item in motion)


def test_ui_workflow_engine_review_ui_edits_checks_structure_not_prompt_words(tmp_path: Path) -> None:
    css_path = tmp_path / "thomas" / "server" / "web" / "css" / "components.css"
    _write(
        css_path,
        """
.card {
  animation: pulse 300ms ease;
  color: #ff0000;
}
""",
    )

    engine = UIWorkflowEngine(
        ui_root=(tmp_path / "thomas" / "server" / "web"),
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )

    report = engine.review_ui_edits(
        intent="Build analytics dashboard with charts and filters",
        changed_paths=["thomas/server/web/css/components.css"],
        strict=True,
    )

    assert report.get("ok") is True
    assert str(report.get("verdict") or "") == "fail"
    issues = report.get("issues") if isinstance(report.get("issues"), list) else []
    issue_ids = {str(item.get("id") or "") for item in issues if isinstance(item, dict)}
    assert "review.intent_alignment_low" not in issue_ids
    assert "review.motion_reduced_missing" in issue_ids
