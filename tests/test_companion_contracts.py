from __future__ import annotations

import pytest

from thomas.marketplace.companion.contracts import ModuleContract, UpdateBundleManifest


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


def test_default_surface_type_is_omitted_from_signed_payload() -> None:
    """A manifest signed before surface_type existed must still canonicalize identically.

    to_dict() feeds canonical_json_for_signature(), so emitting the field
    unconditionally would invalidate the signature of every bundle already
    signed in the field.
    """
    module = ModuleContract.from_dict(
        {
            "id": "companion.home",
            "version": "0.1.0",
            "entrypoint": "modules/companion.home/ui/screen.json",
            "slots": ["home.main"],
            "permissions": ["ui.render"],
            "ui_schema_version": "0.1.0",
            "display_name": "Home",
            "description": "starter",
        }
    )
    assert module.surface_type == "declarative"
    assert "surface_type" not in module.to_dict()


def test_explicit_surface_type_is_covered_by_the_signature() -> None:
    """An explicit surface_type must appear in the signed payload, so it cannot be flipped."""
    module = ModuleContract.from_dict(
        {
            "id": "companion.home",
            "version": "0.1.0",
            "entrypoint": "modules/companion.home/ui/screen.html",
            "slots": ["home.main"],
            "permissions": ["ui.render"],
            "ui_schema_version": "0.1.0",
            "display_name": "Home",
            "description": "starter",
            "surface_type": "surface",
        }
    )
    assert module.to_dict()["surface_type"] == "surface"


def test_unknown_surface_type_is_rejected() -> None:
    with pytest.raises(ValueError):
        ModuleContract.from_dict(
            {
                "id": "companion.home",
                "version": "0.1.0",
                "entrypoint": "modules/companion.home/ui/screen.json",
                "slots": ["home.main"],
                "permissions": ["ui.render"],
                "ui_schema_version": "0.1.0",
                "display_name": "Home",
                "description": "starter",
                "surface_type": "native_code",
            }
        )
