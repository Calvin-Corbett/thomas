from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from thomas.marketplace.companion.kernel import CompanionKernel
from thomas.marketplace.companion.runtime import ModuleRuntime
from thomas.marketplace.companion.update import BundleVerifier, UpdateApplier


def _write_bundle(tmp_path: Path, *, secret: str) -> Path:
    bundle_dir = tmp_path / "bundle"
    payload_file = bundle_dir / "payload" / "modules" / "companion.home" / "ui" / "screen.json"
    payload_file.parent.mkdir(parents=True, exist_ok=True)
    payload_file.write_text('{"screen":"home","components":[{"type":"text","value":"hi"}]}\n', encoding="utf-8")
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


def test_runtime_renders_enabled_slot_payload(tmp_path: Path) -> None:
    kernel = CompanionKernel(tmp_path / "companion")
    kernel.init_layout()
    bundle = _write_bundle(tmp_path, secret="topsecret")
    applier = UpdateApplier(
        kernel,
        verifier=BundleVerifier(kernel, secret="topsecret", require_signature=True),
    )
    apply_result = applier.apply_bundle(bundle, dry_run=False)
    assert apply_result["ok"] is True

    runtime = ModuleRuntime(kernel)
    slots = runtime.slot_index()
    assert "home.main" in slots

    rendered = runtime.render_slot("home.main")
    assert rendered["count"] == 1
    first = (rendered["widgets"] or [{}])[0]
    assert first["module_id"] == "companion.home"
    assert first["payload"]["screen"] == "home"

    bootstrap = runtime.bootstrap(include_slot_payloads=True)
    assert "home.main" in (bootstrap.get("slot_payloads") or {})
