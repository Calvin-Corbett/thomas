from __future__ import annotations

import json
from pathlib import Path

from thomas.plugins.certification import build_plugin_update_plan_from_state, certify_extension_catalog


def _write_pack(root: Path, *, pack_id: str, manifest_version: str, catalog_version: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    pack_dir = root / pack_id
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "hooks.py").write_text("def register(registry):\n    return None\n", encoding="utf-8")
    (pack_dir / "README.md").write_text(f"# {pack_id}\n", encoding="utf-8")
    (pack_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": pack_id,
                "name": f"{pack_id} extension",
                "version": manifest_version,
                "entrypoint": "hooks.py",
                "capabilities": ["healthcheck"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "catalog.json").write_text(
        json.dumps(
            {
                "packs": [
                    {
                        "id": pack_id,
                        "name": f"{pack_id} extension",
                        "version": catalog_version,
                        "entrypoint": "hooks.py",
                        "capabilities": ["healthcheck"],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return pack_dir


def test_certify_extension_catalog_reports_expected_shape() -> None:
    payload = certify_extension_catalog()
    assert payload["ok"] is True
    assert int(payload["summary"]["total"]) >= 480
    assert int(payload["summary"]["catalog_invalid"]) == 0


def test_build_plugin_update_plan_from_state_uses_catalog_versions(tmp_path: Path) -> None:
    catalog_root = tmp_path / "extensions"
    pack_dir = _write_pack(
        catalog_root,
        pack_id="pack-test-updatable",
        manifest_version="1.0.0",
        catalog_version="1.2.0",
    )
    payload = build_plugin_update_plan_from_state(
        [{"name": "pack-test-updatable", "path": str(pack_dir)}],
        catalog_root=catalog_root,
    )
    assert payload["ok"] is True
    assert int(payload["summary"]["total"]) == 1
    assert int(payload["summary"]["update"]) == 1
    action = payload["actions"][0]
    assert action["id"] == "pack-test-updatable"
    assert action["latest_version"] == "1.2.0"
