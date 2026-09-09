"""Channel verification harness for Thomas channel providers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from thomas.channels.p075_channel_provider_interface_contract import (
    ProviderContractRequest,
    run_provider_contract,
)
from thomas.channels.p080_channel_login_command import ChannelLoginRequest, channel_login
from thomas.core.config import AppConfig
from thomas.marketplace.channels._catalog import (
    CHANNEL_PROVIDER_NAMES,
    build_provider_contract_config,
    local_validation_checks,
    provider_configured,
    provider_online_probe,
    resolve_provider_settings,
    verification_fixture,
)

ProbeStatus = Literal["passed", "failed", "skipped"]
EvidenceLevel = Literal["contract", "configured", "live", "failed"]


@dataclass(frozen=True)
class ChannelVerificationRequest:
    config: AppConfig | Any
    providers: Sequence[str] | None = None
    include_live: bool = False
    configured_only: bool = False
    timeout_seconds: float = 5.0
    message: str = "Thomas channel verification probe"


@dataclass(frozen=True)
class ChannelVerificationProbe:
    name: str
    status: ProbeStatus
    ok: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelVerificationProviderResult:
    provider: str
    configured: bool
    overall_ok: bool
    evidence_level: EvidenceLevel
    probes: list[ChannelVerificationProbe] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "configured": self.configured,
            "overall_ok": self.overall_ok,
            "evidence_level": self.evidence_level,
            "probes": [asdict(probe) for probe in self.probes],
        }


@dataclass(frozen=True)
class ChannelVerificationReport:
    ok: bool
    include_live: bool
    providers: list[ChannelVerificationProviderResult]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "include_live": self.include_live,
            "summary": dict(self.summary),
            "providers": [provider.to_dict() for provider in self.providers],
        }


def run_channel_verification(request: ChannelVerificationRequest) -> ChannelVerificationReport:
    selected = _normalize_provider_selection(request.providers)
    results: list[ChannelVerificationProviderResult] = []

    for provider in selected:
        settings = resolve_provider_settings(request.config, provider)
        configured = provider_configured(provider, settings)
        if request.configured_only and not configured:
            continue
        results.append(
            _verify_provider(
                provider=provider,
                settings=settings,
                configured=configured,
                include_live=request.include_live,
                timeout_seconds=request.timeout_seconds,
                message=request.message,
            )
        )

    summary = _build_summary(results)
    return ChannelVerificationReport(
        ok=summary["providers_failed"] == 0,
        include_live=request.include_live,
        providers=results,
        summary=summary,
    )


def format_verification_report_human(report: ChannelVerificationReport) -> str:
    lines = [
        f"Channel verification: {'OK' if report.ok else 'FAIL'}",
        (
            f"Providers: {report.summary['providers_total']} total, "
            f"{report.summary['providers_passed']} passed, "
            f"{report.summary['providers_failed']} failed"
        ),
    ]
    for provider in report.providers:
        state = "PASS" if provider.overall_ok else "FAIL"
        lines.append(f"- {provider.provider}: {state} [{provider.evidence_level}]")
        for probe in provider.probes:
            if probe.status == "passed":
                continue
            detail = _human_probe_detail(probe)
            lines.append(f"  - {probe.name}: {probe.status}{detail}")
    return "\n".join(lines) + "\n"


def _normalize_provider_selection(providers: Sequence[str] | None) -> list[str]:
    if not providers:
        return list(CHANNEL_PROVIDER_NAMES)
    seen: set[str] = set()
    selected: list[str] = []
    for provider in providers:
        name = str(provider or "").strip().lower()
        if not name:
            continue
        if name not in CHANNEL_PROVIDER_NAMES:
            raise ValueError(f"unknown provider: {name}")
        if name in seen:
            continue
        seen.add(name)
        selected.append(name)
    return selected


def _verify_provider(
    *,
    provider: str,
    settings: dict[str, str],
    configured: bool,
    include_live: bool,
    timeout_seconds: float,
    message: str,
) -> ChannelVerificationProviderResult:
    probes: list[ChannelVerificationProbe] = []
    fixture = verification_fixture(provider)
    merged_contract_config = {**fixture.config, **build_provider_contract_config(provider, settings)}
    contract_recipient = settings.get("target") or fixture.recipient

    login_result = channel_login(ChannelLoginRequest(channel=provider))
    probes.append(
        ChannelVerificationProbe(
            name="login_entrypoint",
            status="passed" if login_result.ok else "failed",
            ok=bool(login_result.ok),
            details={"message": login_result.message},
        )
    )

    describe_result = run_provider_contract(
        ProviderContractRequest(
            provider=provider,
            action="describe",
            config=merged_contract_config,
        )
    )
    probes.append(_probe_from_contract("contract_describe", describe_result))

    dry_run_result = run_provider_contract(
        ProviderContractRequest(
            provider=provider,
            action="send",
            config=merged_contract_config,
            recipient=str(contract_recipient),
            message=str(message or fixture.message),
            dry_run=True,
        )
    )
    probes.append(_probe_from_contract("contract_dry_run_send", dry_run_result))

    if configured:
        checks = local_validation_checks(provider, settings)
        ok = all(bool(check.get("ok")) for check in checks)
        probes.append(
            ChannelVerificationProbe(
                name="configured_local_validation",
                status="passed" if ok else "failed",
                ok=ok,
                details={"checks": checks},
            )
        )
    else:
        probes.append(
            ChannelVerificationProbe(
                name="configured_local_validation",
                status="skipped",
                ok=True,
                details={"reason": "provider_not_configured"},
            )
        )

    if include_live and configured:
        live = provider_online_probe(provider, settings, float(timeout_seconds))
        probes.append(
            ChannelVerificationProbe(
                name="live_health_check",
                status="passed" if bool(live.get("ok")) else "failed",
                ok=bool(live.get("ok")),
                details=dict(live),
            )
        )
    elif include_live:
        probes.append(
            ChannelVerificationProbe(
                name="live_health_check",
                status="skipped",
                ok=True,
                details={"reason": "provider_not_configured"},
            )
        )

    overall_ok = all(probe.status != "failed" for probe in probes)
    return ChannelVerificationProviderResult(
        provider=provider,
        configured=configured,
        overall_ok=overall_ok,
        evidence_level=_evidence_level(probes, include_live),
        probes=probes,
    )


def _probe_from_contract(name: str, response: Any) -> ChannelVerificationProbe:
    ok = bool(getattr(response, "ok", False))
    error = getattr(response, "error", None)
    result = getattr(response, "result", None)
    details: dict[str, Any] = {}
    if result is not None:
        details["result"] = result
    if error is not None:
        details["error"] = {
            "code": getattr(error, "code", "unknown"),
            "message": getattr(error, "message", ""),
            "details": getattr(error, "details", {}),
        }
    return ChannelVerificationProbe(
        name=name,
        status="passed" if ok else "failed",
        ok=ok,
        details=details,
    )


def _evidence_level(probes: Sequence[ChannelVerificationProbe], include_live: bool) -> EvidenceLevel:
    if any(probe.status == "failed" for probe in probes):
        return "failed"
    live_probe = next((probe for probe in probes if probe.name == "live_health_check"), None)
    if live_probe is not None and live_probe.status == "passed":
        return "live"
    validation_probe = next((probe for probe in probes if probe.name == "configured_local_validation"), None)
    if validation_probe is not None and validation_probe.status == "passed":
        return "configured"
    if include_live:
        return "contract"
    return "contract"


def _build_summary(results: Sequence[ChannelVerificationProviderResult]) -> dict[str, int]:
    probe_counts = {"passed": 0, "failed": 0, "skipped": 0}
    for result in results:
        for probe in result.probes:
            probe_counts[probe.status] += 1
    return {
        "providers_total": len(results),
        "providers_passed": sum(1 for result in results if result.overall_ok),
        "providers_failed": sum(1 for result in results if not result.overall_ok),
        "probes_passed": probe_counts["passed"],
        "probes_failed": probe_counts["failed"],
        "probes_skipped": probe_counts["skipped"],
    }


def _human_probe_detail(probe: ChannelVerificationProbe) -> str:
    if probe.status == "skipped":
        reason = str(probe.details.get("reason") or "").strip()
        return f" ({reason})" if reason else ""
    if probe.status == "failed":
        error = probe.details.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "").strip()
            return f" ({message})" if message else ""
    return ""
