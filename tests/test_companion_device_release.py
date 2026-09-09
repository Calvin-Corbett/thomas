from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from thomas.marketplace.companion.audit import CompanionAuditLog
from thomas.marketplace.companion.devices import DeviceRegistry
from thomas.marketplace.companion.kernel import CompanionKernel
from thomas.marketplace.companion.releases import ReleaseRegistry
from thomas.marketplace.companion.update import BundleVerifier


def _write_bundle(tmp_path: Path, *, secret: str, version: str) -> Path:
    bundle_dir = tmp_path / f"bundle-{version}"
    payload_file = bundle_dir / "payload" / "modules" / "companion.home" / "ui" / "screen.json"
    payload_file.parent.mkdir(parents=True, exist_ok=True)
    payload_file.write_text(json.dumps({"screen": "home", "version": version}) + "\n", encoding="utf-8")
    sha = hashlib.sha256(payload_file.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "bundle_id": f"companion.home-{version}",
        "created_at": "2026-02-20T00:00:00+00:00",
        "min_kernel_version": "0.1.0",
        "module": {
            "id": "companion.home",
            "version": version,
            "entrypoint": "modules/companion.home/ui/screen.json",
            "slots": ["home.main"],
            "permissions": ["storage.read", "ui.render"],
            "ui_schema_version": "0.1.0",
            "display_name": "Home",
            "description": "starter",
        },
        "files": [{"path": "modules/companion.home/ui/screen.json", "sha256": sha}],
        "release_notes": f"v{version}",
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    manifest["signature"] = {"algo": "hmac-sha256", "value": sig}
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return bundle_dir


def test_device_release_update_resolution_and_audit(tmp_path: Path) -> None:
    kernel = CompanionKernel(tmp_path / "companion")
    kernel.init_layout()
    devices = DeviceRegistry(kernel)
    releases = ReleaseRegistry(kernel)
    audit = CompanionAuditLog(kernel)
    verifier = BundleVerifier(kernel, secret="topsecret", require_signature=True)

    bundle_old = _write_bundle(tmp_path, secret="topsecret", version="0.1.0")
    publish_old = releases.publish_from_bundle(
        bundle_old,
        channel="stable",
        published_by="owner",
        verifier=verifier,
    )
    assert publish_old["ok"] is True

    bundle_new = _write_bundle(tmp_path, secret="topsecret", version="0.2.0")
    publish_new = releases.publish_from_bundle(
        bundle_new,
        channel="stable",
        published_by="owner",
        verifier=verifier,
    )
    assert publish_new["ok"] is True

    device = devices.upsert(
        device_id="ios-1",
        platform="ios",
        app_version="1.0.0",
        channel="stable",
        tailscale_identity="ios-1.tailnet.ts.net",
        capabilities=[],
        installed_modules={"companion.home": "0.1.0"},
        metadata={},
    )
    assert device.device_id == "ios-1"

    updates = releases.resolve_updates(channel="stable", installed_modules=device.installed_modules)
    assert len(updates) == 1
    assert updates[0].module_version == "0.2.0"

    device2 = devices.upsert(
        device_id="ios-1",
        platform="ios",
        app_version="1.0.0",
        channel="stable",
        tailscale_identity="ios-1.tailnet.ts.net",
        capabilities=[],
        installed_modules={"companion.home": "0.2.0"},
        metadata={},
    )
    updates2 = releases.resolve_updates(channel="stable", installed_modules=device2.installed_modules)
    assert updates2 == []

    audit.append("device.updates.check", actor="owner", peer_identity=device2.tailscale_identity, details={})
    events = audit.list(limit=10)
    assert len(events) >= 1
    assert events[-1]["event_type"] == "device.updates.check"
