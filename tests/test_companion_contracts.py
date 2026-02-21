from __future__ import annotations

import pytest

from thomas.companion.contracts import ModuleContract, UpdateBundleManifest


def test_module_contract_parses_valid_payload() -> None:
    module = ModuleContract.from_dict(
        {
            "id": "companion.home",
            "version": "0.1.0",
            "entrypoint": "modules/companion.home/ui/screen.json",
            "slots": ["home.main"],
            "permissions": ["ui.render", "storage.read"],
            "ui_schema_version": "0.1.0",
            "display_name": "Home",
            "description": "starter",
        }
    )
    assert module.module_id == "companion.home"
    assert module.version == "0.1.0"
    assert "ui.render" in module.permissions


def test_module_contract_rejects_unsupported_permission() -> None:
    with pytest.raises(ValueError):
        ModuleContract.from_dict(
            {
                "id": "companion.home",
                "version": "0.1.0",
                "entrypoint": "modules/companion.home/ui/screen.json",
                "slots": ["home.main"],
                "permissions": ["ui.render", "shell.exec"],
                "ui_schema_version": "0.1.0",
                "display_name": "Home",
                "description": "starter",
            }
        )


def test_update_manifest_canonical_json_excludes_signature() -> None:
    manifest = UpdateBundleManifest.from_dict(
        {
            "schema_version": 1,
            "bundle_id": "companion.home-0.1.0",
            "created_at": "2026-02-20T00:00:00+00:00",
            "min_kernel_version": "0.1.0",
            "module": {
                "id": "companion.home",
                "version": "0.1.0",
                "entrypoint": "modules/companion.home/ui/screen.json",
                "slots": ["home.main"],
                "permissions": ["ui.render", "storage.read"],
                "ui_schema_version": "0.1.0",
                "display_name": "Home",
                "description": "starter",
            },
            "files": [
                {
                    "path": "modules/companion.home/ui/screen.json",
                    "sha256": "a" * 64,
                }
            ],
            "release_notes": "starter",
            "signature": {"algo": "hmac-sha256", "value": "b" * 64},
        }
    )
    canonical = manifest.canonical_json_for_signature()
    assert '"signature"' not in canonical
    assert '"bundle_id":"companion.home-0.1.0"' in canonical
