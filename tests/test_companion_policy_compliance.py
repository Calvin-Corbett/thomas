from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from thomas.companion.kernel import CompanionKernel
from thomas.companion.policy import PolicyComplianceService, resolve_policy_profile
from thomas.companion.update import BundleVerifier


def _write_bundle(
    tmp_path: Path,
    *,
    secret: str,
    payload: dict | None = None,
) -> Path:
    bundle_dir = tmp_path / "bundle"
    payload_file = bundle_dir / "payload" / "modules" / "companion.home" / "ui" / "screen.json"
    payload_file.parent.mkdir(parents=True, exist_ok=True)
    payload_file.write_text(
        json.dumps(payload or {"screen": "home", "components": [{"type": "text", "value": "hi"}]}) + "\n",
        encoding="utf-8",
    )
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


def test_policy_profile_resolution_ios_app_store() -> None:
    profile_id = resolve_policy_profile(
        platform="ios",
        distribution_channel="app_store",
        storefront_region="US",
    )
    assert profile_id == "ios_app_store"


def test_compliance_blocks_digital_without_store_billing(tmp_path: Path) -> None:
    kernel = CompanionKernel(tmp_path / "companion")
    bundle = _write_bundle(tmp_path, secret="topsecret")
    verifier = BundleVerifier(kernel, secret="topsecret", require_signature=True)
    verify_report = verifier.verify_bundle(bundle)

    service = PolicyComplianceService(kernel)
    report = service.check_bundle(
        bundle_dir=bundle,
        verify_report=verify_report,
        platform="ios",
        distribution_channel="app_store",
        storefront_region="US",
        commerce_model="digital_in_app",
        store_billing_enabled=False,
    )

    assert report.ok is False
    codes = {item.code for item in report.violations}
    assert "commerce.store_billing_required" in codes


def test_compliance_blocks_store_profile_without_storefront_region(tmp_path: Path) -> None:
    kernel = CompanionKernel(tmp_path / "companion")
    bundle = _write_bundle(tmp_path, secret="topsecret")
    verifier = BundleVerifier(kernel, secret="topsecret", require_signature=True)
    verify_report = verifier.verify_bundle(bundle)

    service = PolicyComplianceService(kernel)
    report = service.check_bundle(
        bundle_dir=bundle,
        verify_report=verify_report,
        platform="ios",
        distribution_channel="app_store",
        storefront_region="",
        commerce_model="physical_or_off_app",
    )

    assert report.ok is False
    codes = {item.code for item in report.violations}
    assert "targeting.storefront_region_required" in codes


def test_compliance_blocks_ugc_without_required_controls(tmp_path: Path) -> None:
    kernel = CompanionKernel(tmp_path / "companion")
    bundle = _write_bundle(tmp_path, secret="topsecret")
    verifier = BundleVerifier(kernel, secret="topsecret", require_signature=True)
    verify_report = verifier.verify_bundle(bundle)

    service = PolicyComplianceService(kernel)
    report = service.check_bundle(
        bundle_dir=bundle,
        verify_report=verify_report,
        platform="android",
        distribution_channel="play_store",
        storefront_region="US",
        ugc_enabled=True,
        moderation_controls=["report"],
        age_gate_enabled=False,
    )

    assert report.ok is False
    codes = {item.code for item in report.violations}
    assert "ugc.moderation_controls_missing" in codes
    assert "ugc.age_gate_required" in codes


def test_compliance_passes_safe_payload(tmp_path: Path) -> None:
    kernel = CompanionKernel(tmp_path / "companion")
    bundle = _write_bundle(
        tmp_path,
        secret="topsecret",
        payload={
            "screen": "home",
            "commerce_model": "physical_or_off_app",
            "ugc_enabled": False,
            "components": [
                {"type": "container", "children": [{"type": "text", "value": "hi"}]},
            ],
        },
    )
    verifier = BundleVerifier(kernel, secret="topsecret", require_signature=True)
    verify_report = verifier.verify_bundle(bundle)

    service = PolicyComplianceService(kernel)
    report = service.check_bundle(
        bundle_dir=bundle,
        verify_report=verify_report,
        platform="android",
        distribution_channel="play_store",
        storefront_region="US",
        runtime_capability_set=["push", "storage"],
        required_capabilities=["push"],
    )

    assert report.ok is True
    assert report.violations == []
