from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from thomas.marketplace.companion.kernel import CompanionKernel
from thomas.marketplace.companion.update import BundleVerifier, UpdateApplier


def _write_bundle(tmp_path: Path, *, secret: str) -> Path:
    bundle_dir = tmp_path / "bundle"
    payload_file = bundle_dir / "payload" / "modules" / "companion.home" / "ui" / "screen.json"
    payload_file.parent.mkdir(parents=True, exist_ok=True)
    payload_file.write_text('{"screen":"home"}\n', encoding="utf-8")
    sha = hashlib.sha256(payload_file.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "bundle_id": "companion.home-0.1.0",
        "created_at": "2026-02-20T00:00:00+00:00",
        "min_kernel_version": "0.1.0",
        "module": {
            "id": "companion.home",
            "version": "0.1.0",
            "entrypoint": "modules/companion.home/ui/screen.json",
            "slots": ["home.main"],
            "permissions": ["storage.read", "ui.render"],
            "ui_schema_version": "0.1.0",
            "display_name": "Home",
            "description": "starter",
        },
        "files": [{"path": "modules/companion.home/ui/screen.json", "sha256": sha}],
        "release_notes": "starter",
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    manifest["signature"] = {"algo": "hmac-sha256", "value": sig}
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return bundle_dir


def test_bundle_verifier_accepts_valid_signed_bundle(tmp_path: Path) -> None:
    kernel = CompanionKernel(tmp_path / "companion")
    kernel.init_layout()
    bundle = _write_bundle(tmp_path, secret="topsecret")
    verifier = BundleVerifier(kernel, secret="topsecret", require_signature=True)
    report = verifier.verify_bundle(bundle)
    assert report.ok is True
    assert report.errors == []
    assert report.module is not None
    assert report.module.module_id == "companion.home"


def test_update_applier_writes_module_files_and_registry(tmp_path: Path) -> None:
    kernel = CompanionKernel(tmp_path / "companion")
    kernel.init_layout()
    bundle = _write_bundle(tmp_path, secret="topsecret")
    verifier = BundleVerifier(kernel, secret="topsecret", require_signature=True)
    applier = UpdateApplier(kernel, verifier=verifier)

    dry = applier.apply_bundle(bundle, dry_run=True)
    assert dry["ok"] is True
    assert dry["dry_run"] is True

    live = applier.apply_bundle(bundle, dry_run=False)
    assert live["ok"] is True
    dst = kernel.paths.modules_dir / "companion.home" / "ui" / "screen.json"
    assert dst.exists()
    registry_payload = json.loads(kernel.paths.registry_file.read_text(encoding="utf-8"))
    assert "companion.home" in (registry_payload.get("modules") or {})
