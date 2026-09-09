from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from thomas.channels.p097_channel_verification_harness import (
    ChannelVerificationRequest,
    run_channel_verification,
)


def _fake_config(root: Path) -> SimpleNamespace:
    return SimpleNamespace(memory=SimpleNamespace(root_path=root))


def _write_channels_store(root: Path, payload: dict[str, object]) -> None:
    path = root / ".thomas" / "channels.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_channel_verification_contract_mode_without_saved_credentials(tmp_path: Path) -> None:
    report = run_channel_verification(
        ChannelVerificationRequest(
            config=_fake_config(tmp_path),
            providers=["telegram", "slack"],
            include_live=False,
        )
    )

    assert report.ok is True
    assert report.summary["providers_total"] == 2
    for provider in report.providers:
        assert provider.overall_ok is True
        assert provider.evidence_level == "contract"
        probe_names = {probe.name: probe for probe in provider.probes}
        assert probe_names["login_entrypoint"].status == "passed"
        assert probe_names["contract_describe"].status == "passed"
        assert probe_names["contract_dry_run_send"].status == "passed"
        assert probe_names["configured_local_validation"].status == "skipped"


def test_channel_verification_live_mode_for_configured_channel(monkeypatch, tmp_path: Path) -> None:
    _write_channels_store(
        tmp_path,
        {
            "providers": {
                "slack": {
                    "webhook": "https://hooks.slack.com/services/T/B/C",
                    "updated_at": "2026-03-28T00:00:00Z",
                }
            }
        },
    )

    monkeypatch.setattr(
        "thomas.marketplace.channels.p097_channel_verification_harness.provider_online_probe",
        lambda name, settings, timeout_s: {"ok": True, "status": 200, "payload": {"provider": name}},
    )

    report = run_channel_verification(
        ChannelVerificationRequest(
            config=_fake_config(tmp_path),
            providers=["slack", "telegram"],
            include_live=True,
            configured_only=True,
        )
    )

    assert report.ok is True
    assert report.summary["providers_total"] == 1
    provider = report.providers[0]
    assert provider.provider == "slack"
    assert provider.evidence_level == "live"
    live_probe = next(probe for probe in provider.probes if probe.name == "live_health_check")
    assert live_probe.status == "passed"
