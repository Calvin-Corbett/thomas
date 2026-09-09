"""CAP-074: BYO custom-connector support -- conformance harness + registry.

Acceptance line: "Create a documented first-class custom-connector path with a
conformance harness."

These tests prove the harness end to end against hermetic fake connectors:
* a well-formed connector PASSES conformance and registers;
* a connector missing a method / returning a malformed envelope / mis-declaring
  a capability FAILS, with the precise failing check named;
* a certified connector is invokable through the registry;
* the harness is deterministic.

No network, no credentials, no external service -- BYO is a framework.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from thomas.integrations.byo_connector import (
    ENVELOPE_KEYS,
    BaseConnector,
    ConformanceError,
    ConnectorRegistry,
    make_envelope,
    run_conformance,
)


# ---------------------------------------------------------------------------
# Fake connectors (the hermetic "third parties")
# ---------------------------------------------------------------------------
class GoodConnector(BaseConnector):
    """A fully conformant connector built on the provided base class."""

    def metadata(self) -> Mapping[str, Any]:
        return {"name": "acme", "version": "1.2.0", "description": "Acme widgets"}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [
            {"action": "echo", "description": "echo params back", "sample": {"msg": "hi"}},
            {"action": "add", "description": "add two numbers", "sample": {"a": 2, "b": 3}},
        ]

    def handle(self, action: str, params: Mapping[str, Any]) -> Any:
        if action == "echo":
            return {"echoed": params.get("msg")}
        if action == "add":
            return {"sum": int(params["a"]) + int(params["b"])}
        raise KeyError(action)


class RawGoodConnector:
    """A conformant connector implemented WITHOUT the base class (raw protocol)."""

    def metadata(self) -> Mapping[str, Any]:
        return {"name": "raw", "version": "0.1"}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [{"action": "ping"}]

    def invoke(self, action: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        if action == "ping":
            return make_envelope(action, ok=True, result="pong")
        return make_envelope(action, ok=False, error=f"unknown action: {action}")

    def health(self) -> Mapping[str, Any]:
        return {"ok": True, "status": "healthy"}


class MissingHealthConnector:
    """Missing the health() method entirely -> methods_present must fail."""

    def metadata(self) -> Mapping[str, Any]:
        return {"name": "nohealth", "version": "1.0"}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [{"action": "ping"}]

    def invoke(self, action: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        return make_envelope(action, ok=True, result="pong")


class MalformedEnvelopeConnector(BaseConnector):
    """invoke returns a dict missing the required keys -> invoke_envelope fails."""

    def metadata(self) -> Mapping[str, Any]:
        return {"name": "malformed", "version": "1.0"}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [{"action": "go"}]

    def invoke(self, action: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        # Deliberately wrong shape: no 'ok'/'error' keys.
        return {"action": action, "result": 42}


class MisdeclaredCapabilityConnector(BaseConnector):
    """Declares an action that invoke does not actually serve -> invoke_envelope fails.

    The declared action 'phantom' is not handled, so BaseConnector.invoke
    returns an ok=False envelope for it, which the harness (expecting ok=True
    for a declared capability) flags.
    """

    def metadata(self) -> Mapping[str, Any]:
        return {"name": "misdeclared", "version": "1.0"}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [{"action": "real"}, {"action": "phantom"}]

    def handle(self, action: str, params: Mapping[str, Any]) -> Any:
        if action == "real":
            return "ok"
        raise KeyError(action)


class RaisingErrorConnector:
    """invoke RAISES on an unknown action instead of returning an envelope."""

    def metadata(self) -> Mapping[str, Any]:
        return {"name": "raiser", "version": "1.0"}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [{"action": "ok"}]

    def invoke(self, action: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        if action == "ok":
            return make_envelope(action, ok=True, result=1)
        raise ValueError("boom")  # violates the error-envelope contract

    def health(self) -> Mapping[str, Any]:
        return {"ok": True}


class BadMetadataConnector(BaseConnector):
    """metadata() has no version -> metadata_wellformed fails."""

    def metadata(self) -> Mapping[str, Any]:
        return {"name": "nometa"}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [{"action": "go"}]

    def handle(self, action: str, params: Mapping[str, Any]) -> Any:
        return "ok"


class EmptyCapabilitiesConnector(BaseConnector):
    """No declared capabilities -> capabilities_declared fails."""

    def metadata(self) -> Mapping[str, Any]:
        return {"name": "empty", "version": "1.0"}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return []


class BadHealthConnector(BaseConnector):
    """health() lacks a bool 'ok' -> health_reports fails."""

    def metadata(self) -> Mapping[str, Any]:
        return {"name": "sickhealth", "version": "1.0"}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [{"action": "go"}]

    def handle(self, action: str, params: Mapping[str, Any]) -> Any:
        return "ok"

    def health(self) -> Mapping[str, Any]:
        return {"status": "unknown"}  # missing bool 'ok'


class HangingConnector:
    """invoke blocks forever -> timeout_handled fails (bounded by the harness)."""

    def metadata(self) -> Mapping[str, Any]:
        return {"name": "hang", "version": "1.0"}

    def capabilities(self) -> Sequence[Mapping[str, Any]]:
        return [{"action": "slow"}]

    def invoke(self, action: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        time.sleep(30)  # far past the test budget
        return make_envelope(action, ok=True)

    def health(self) -> Mapping[str, Any]:
        return {"ok": True}


# ---------------------------------------------------------------------------
# A well-formed connector PASSES conformance and registers
# ---------------------------------------------------------------------------
def test_good_connector_is_certified() -> None:
    report = run_conformance(GoodConnector())
    assert report.certified is True
    assert report.failing() == []
    # Every contract check is present and passing.
    names = [c.check for c in report.checks]
    assert names == [
        "methods_present",
        "metadata_wellformed",
        "capabilities_declared",
        "invoke_envelope",
        "error_handled",
        "timeout_handled",
        "health_reports",
    ]
    assert all(c.passed for c in report.checks)


def test_raw_protocol_connector_is_certified() -> None:
    # Certification does not require subclassing BaseConnector.
    report = run_conformance(RawGoodConnector())
    assert report.certified is True


def test_certifying_register_accepts_good_connector() -> None:
    registry = ConnectorRegistry()
    report = registry.register(GoodConnector())
    assert report.certified is True
    assert "acme" in registry
    assert registry.names() == ["acme"]


# ---------------------------------------------------------------------------
# Missing method / malformed envelope / mis-declared capability FAIL precisely
# ---------------------------------------------------------------------------
def test_missing_method_fails_methods_present() -> None:
    report = run_conformance(MissingHealthConnector())
    assert report.certified is False
    first = report.first_failure()
    assert first is not None
    assert first.check == "methods_present"
    assert "health" in first.detail


def test_malformed_envelope_fails_invoke_envelope() -> None:
    report = run_conformance(MalformedEnvelopeConnector())
    assert report.certified is False
    failed = {c.check for c in report.failing()}
    assert "invoke_envelope" in failed
    detail = report.check("invoke_envelope").detail
    assert "missing keys" in detail


def test_misdeclared_capability_fails_invoke_envelope() -> None:
    report = run_conformance(MisdeclaredCapabilityConnector())
    assert report.certified is False
    check = report.check("invoke_envelope")
    assert check.passed is False
    assert "phantom" in check.detail


def test_raising_on_unknown_action_fails_error_handled() -> None:
    report = run_conformance(RaisingErrorConnector())
    assert report.certified is False
    check = report.check("error_handled")
    assert check.passed is False
    assert "ValueError" in check.detail


def test_bad_metadata_fails_metadata_wellformed() -> None:
    report = run_conformance(BadMetadataConnector())
    assert report.certified is False
    check = report.check("metadata_wellformed")
    assert check.passed is False
    assert "version" in check.detail


def test_empty_capabilities_fails_capabilities_declared() -> None:
    report = run_conformance(EmptyCapabilitiesConnector())
    assert report.certified is False
    check = report.check("capabilities_declared")
    assert check.passed is False


def test_bad_health_fails_health_reports() -> None:
    report = run_conformance(BadHealthConnector())
    assert report.certified is False
    check = report.check("health_reports")
    assert check.passed is False


def test_hanging_invoke_fails_timeout_handled() -> None:
    report = run_conformance(HangingConnector(), timeout=0.2)
    assert report.certified is False
    check = report.check("timeout_handled")
    assert check.passed is False
    assert "budget" in check.detail


# ---------------------------------------------------------------------------
# Registry refuses non-conformant connectors by default
# ---------------------------------------------------------------------------
def test_register_refuses_uncertified_connector() -> None:
    registry = ConnectorRegistry()
    with pytest.raises(ConformanceError) as excinfo:
        registry.register(MalformedEnvelopeConnector())
    assert "malformed" in str(excinfo.value)
    # Rejected connector was NOT stored.
    assert len(registry) == 0
    # The attached report names the failing check.
    assert "invoke_envelope" in {c.check for c in excinfo.value.report.failing()}


def test_register_without_certify_stores_but_reports_failure() -> None:
    registry = ConnectorRegistry()
    report = registry.register(BadMetadataConnector(), certify=False)
    assert report.certified is False
    assert "nometa" in registry


# ---------------------------------------------------------------------------
# A certified connector is invokable through the registry
# ---------------------------------------------------------------------------
def test_certified_connector_invokable_through_registry() -> None:
    registry = ConnectorRegistry()
    registry.register(GoodConnector())

    envelope = registry.invoke("acme", "add", {"a": 4, "b": 5})
    assert set(envelope).issuperset(ENVELOPE_KEYS)
    assert envelope["ok"] is True
    assert envelope["action"] == "add"
    assert envelope["result"] == {"sum": 9}
    assert envelope["error"] == ""


def test_registry_invoke_unknown_action_returns_error_envelope() -> None:
    registry = ConnectorRegistry()
    registry.register(GoodConnector())
    envelope = registry.invoke("acme", "nope", {})
    assert envelope["ok"] is False
    assert envelope["action"] == "nope"
    assert envelope["error"]


def test_registry_invoke_times_out_without_hanging() -> None:
    registry = ConnectorRegistry(timeout=0.2)
    # Store without certification so we can exercise the registry timeout guard.
    registry.register(HangingConnector(), certify=False)
    envelope = registry.invoke("hang", "slow", {})
    assert envelope["ok"] is False
    assert "timeout" in envelope["error"]


def test_discover_lists_registered_connectors() -> None:
    registry = ConnectorRegistry()
    registry.register(GoodConnector())
    registry.register(RawGoodConnector())
    discovered = registry.discover()
    names = [item["name"] for item in discovered]
    assert names == ["acme", "raw"]
    acme = next(item for item in discovered if item["name"] == "acme")
    assert acme["actions"] == ["add", "echo"]
    assert acme["certified"] is True
    assert acme["metadata"]["version"] == "1.2.0"


def test_unregister_removes_connector() -> None:
    registry = ConnectorRegistry()
    registry.register(GoodConnector())
    assert registry.unregister("acme") is True
    assert "acme" not in registry
    assert registry.unregister("acme") is False


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_conformance_is_deterministic() -> None:
    connector = GoodConnector()
    reports = [run_conformance(connector) for _ in range(5)]
    baseline = reports[0].to_dict()
    for report in reports[1:]:
        assert report.to_dict() == baseline


def test_failure_report_is_deterministic() -> None:
    connector = MalformedEnvelopeConnector()
    reports = [run_conformance(connector).to_dict() for _ in range(5)]
    assert all(r == reports[0] for r in reports)


def test_report_shape_stable_after_early_short_circuit() -> None:
    # Even when validation short-circuits (missing method), the report still
    # carries all seven checks in canonical order -> stable for callers.
    report = run_conformance(MissingHealthConnector())
    names = [c.check for c in report.checks]
    assert names == [
        "methods_present",
        "metadata_wellformed",
        "capabilities_declared",
        "invoke_envelope",
        "error_handled",
        "timeout_handled",
        "health_reports",
    ]
