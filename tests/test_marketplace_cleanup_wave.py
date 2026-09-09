from __future__ import annotations

import json
from pathlib import Path

from thomas.marketplace.publisher import publish_marketplace_wave
from thomas.marketplace.surface_policy import classify_marketplace_row, family_requires_strict_entrypoint


def _write_extension_pack(
    root: Path, plugin_id: str, *, manifest: dict, readme: bool = True, hooks: bool = True
) -> None:
    pack_dir = root / plugin_id
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if hooks:
        (pack_dir / "hooks.py").write_text("def register(*_args, **_kwargs):\n    return None\n", encoding="utf-8")
    if readme:
        (pack_dir / "README.md").write_text(f"# {plugin_id}\n", encoding="utf-8")
    entry_html = manifest.get("surface", {}).get("entry_html")
    if entry_html:
        entry_path = pack_dir / str(entry_html)
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        entry_path.write_text("<html><body>ok</body></html>\n", encoding="utf-8")


def _write_catalog(root: Path, packs: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "catalog.json").write_text(
        json.dumps({"generated_at": "2026-03-27T00:00:00Z", "packs": packs}, indent=2), encoding="utf-8"
    )


def test_publish_marketplace_wave_dry_run_reports_publishable_desktop_plugins(tmp_path: Path) -> None:
    extensions_root = tmp_path / "extensions"
    hosted_root = tmp_path / "hosted"
    packs = [
        {
            "id": "life-manager",
            "name": "Life Manager",
            "version": "1.0.0",
            "category": "productivity",
            "target": "desktop",
            "mode": "life_manager",
            "entrypoint": "hooks.py",
            "capabilities": ["life_manager.tasks"],
            "description": "Desktop plugin",
            "requires": ["life-manager-foundation"],
        },
        {
            "id": "life-manager-foundation",
            "name": "Life Manager Foundation",
            "version": "1.0.0",
            "category": "productivity",
            "target": "desktop",
            "mode": "life_manager_foundation",
            "entrypoint": "hooks.py",
            "capabilities": ["life_manager.foundation"],
            "description": "Dependency plugin",
        },
    ]
    _write_catalog(extensions_root, packs)
    for pack in packs:
        _write_extension_pack(
            extensions_root,
            pack["id"],
            manifest={
                "id": pack["id"],
                "plugin_id": pack["id"],
                "name": pack["name"],
                "display_name": pack["name"],
                "version": pack["version"],
                "description": pack["description"],
                "kind": "desktop_plugin",
                "mode_id": pack["mode"],
                "api_namespace": pack["id"],
                "entrypoint": "hooks.py",
                "capabilities": pack["capabilities"],
                "requires": pack.get("requires", []),
                "category": pack["category"],
                "categories": [pack["category"]],
                "surface": {
                    "entry_html": "web/index.html",
                    "title": pack["name"],
                    "surface_mode": "immersive",
                },
            },
        )

    report = publish_marketplace_wave(
        extensions_root=extensions_root,
        hosted_store_root=hosted_root,
        plugin_ids=["life-manager", "life-manager-foundation"],
        dry_run=True,
    )

    assert report["ok"] is True
    assert report["dry_run"] is True
    assert [row["plugin_id"] for row in report["published"]] == ["life-manager", "life-manager-foundation"]
    assert report["published"][0]["requires"] == ["life-manager-foundation"]
    assert not hosted_root.exists()


def test_publish_marketplace_wave_write_mode_creates_bundle_and_manifest(tmp_path: Path) -> None:
    extensions_root = tmp_path / "extensions"
    hosted_root = tmp_path / "hosted"
    catalog_row = {
        "id": "life-manager",
        "name": "Life Manager",
        "version": "1.0.0",
        "category": "productivity",
        "target": "desktop",
        "mode": "life_manager",
        "entrypoint": "hooks.py",
        "capabilities": ["life_manager.tasks"],
        "description": "Desktop plugin",
    }
    _write_catalog(extensions_root, [catalog_row])
    _write_extension_pack(
        extensions_root,
        "life-manager",
        manifest={
            "id": "life-manager",
            "plugin_id": "life-manager",
            "name": "Life Manager",
            "display_name": "Life Manager",
            "version": "1.0.0",
            "description": "Desktop plugin",
            "kind": "desktop_plugin",
            "mode_id": "life_manager",
            "api_namespace": "life-manager",
            "entrypoint": "hooks.py",
            "capabilities": ["life_manager.tasks"],
            "categories": ["productivity"],
            "surface": {
                "entry_html": "web/index.html",
                "title": "Life Manager",
                "surface_mode": "immersive",
            },
        },
    )

    report = publish_marketplace_wave(
        extensions_root=extensions_root,
        hosted_store_root=hosted_root,
        plugin_ids=["life-manager"],
        dry_run=False,
    )

    plugin_dir = hosted_root / "life-manager"
    manifest_path = plugin_dir / "manifest.json"
    bundle_path = plugin_dir / "bundle.zip"
    assert report["published"][0]["plugin_id"] == "life-manager"
    assert manifest_path.exists()
    assert bundle_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["plugin_id"] == "life-manager"
    assert manifest["publisher_id"] == "thomas-official"
    assert manifest["sha256"] == report["published"][0]["sha256"]


def test_publish_marketplace_wave_skips_valid_inventory_without_desktop_plugin_surface(tmp_path: Path) -> None:
    extensions_root = tmp_path / "extensions"
    hosted_root = tmp_path / "hosted"
    catalog_row = {
        "id": "pack-alerts-slack-detect",
        "name": "Alerts Slack Detect Extension Pack",
        "version": "1.0.0",
        "category": "alerts",
        "target": "slack",
        "mode": "detect",
        "entrypoint": "hooks.py",
        "capabilities": ["alerts.signal", "healthcheck"],
        "description": "Inventory pack",
    }
    _write_catalog(extensions_root, [catalog_row])
    _write_extension_pack(
        extensions_root,
        "pack-alerts-slack-detect",
        manifest={
            "id": "pack-alerts-slack-detect",
            "name": "Alerts Slack Detect Extension Pack",
            "version": "1.0.0",
            "entrypoint": "hooks.py",
            "capabilities": ["alerts.signal", "healthcheck"],
            "description": "Inventory pack",
        },
    )

    report = publish_marketplace_wave(
        extensions_root=extensions_root,
        hosted_store_root=hosted_root,
        plugin_ids=["pack-alerts-slack-detect"],
        dry_run=False,
    )

    assert report["published"] == []
    assert report["skipped"][0]["plugin_id"] == "pack-alerts-slack-detect"
    assert report["skipped"][0]["reason"] == "desktop_plugin_manifest_required"
    assert not hosted_root.exists()


def test_classify_marketplace_row_marks_policy_scaffold_and_hidden(monkeypatch, tmp_path: Path) -> None:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "hidden_ids": ["hidden-pack"],
                "scaffold_ids": ["proxy-pack"],
                "strict_proxy_families": ["message", "gateway"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("THOMAS_MARKETPLACE_POLICY_PATH", str(policy_path))

    hidden = classify_marketplace_row({"id": "hidden-pack"}, installable_candidate=False)
    scaffold = classify_marketplace_row({"id": "proxy-pack"}, installable_candidate=True)
    installable = classify_marketplace_row({"id": "real-pack"}, installable_candidate=True)

    assert hidden["availability"] == "hidden"
    assert hidden["promotion_status"] == "suppressed"
    assert scaffold["availability"] == "scaffold"
    assert scaffold["needs_review"] is True
    assert installable["availability"] == "installable"
    assert family_requires_strict_entrypoint("message") is True
    assert family_requires_strict_entrypoint("misc") is False


def test_classify_marketplace_row_installed_beats_scaffold_heuristics() -> None:
    """An installed runtime is proof the package is real: description words
    like 'stub' must not scaffold-hide it (it would become unmanageable in the
    marketplace UI). Explicit availability still wins."""
    policy = {"scaffold_terms": ["stub"], "scaffold_tags": ["scaffold"]}
    row = {
        "id": "community-notes",
        "description": "A notes skill plus a stub MCP server.",
        "installed": True,
    }
    installed = classify_marketplace_row(row, installable_candidate=False, policy=policy)
    assert installed["availability"] == "catalog_only"

    uninstalled = classify_marketplace_row(
        {**row, "installed": False}, installable_candidate=False, policy=policy
    )
    assert uninstalled["availability"] == "scaffold"

    explicit = classify_marketplace_row(
        {**row, "availability": "scaffold"}, installable_candidate=False, policy=policy
    )
    assert explicit["availability"] == "scaffold"
