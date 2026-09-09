from __future__ import annotations

import json

import pytest

from thomas.marketplace.channels.p092_channel_failure_taxonomy import (
    ChannelFailureTaxonomyError,
    FailureCategory,
    FailureTaxonomyRequest,
    InvalidTaxonomyInputError,
    MissingChannelConfigError,
    build_failure_taxonomy_report,
    classify_failure_event,
    parse_event_json,
    taxonomy_schema,
)


def test_build_report_includes_taxonomy() -> None:
    report = build_failure_taxonomy_report(FailureTaxonomyRequest())
    assert report.ok is True
    assert report.channel is None
    assert len(report.taxonomy) >= 5
    assert {entry.category for entry in report.taxonomy} >= {
        FailureCategory.AUTHENTICATION,
        FailureCategory.NETWORK,
        FailureCategory.UNKNOWN,
    }


def test_build_report_channel_specific_guidance() -> None:
    report = build_failure_taxonomy_report(FailureTaxonomyRequest(channel=" telegram "))
    assert report.ok is True
    assert report.channel == "telegram"
    # Telegram-specific remediation hints.
    assert any(
        entry.category == FailureCategory.DESTINATION_NOT_FOUND and "chat_id" in entry.remediation
        for entry in report.taxonomy
    )


def test_report_to_dict_is_machine_readable() -> None:
    report = build_failure_taxonomy_report(FailureTaxonomyRequest())
    payload = report.to_dict()
    assert payload["ok"] is True
    assert "taxonomy" in payload
    assert "classification" in payload
    json.dumps(payload)  # should be JSON-serializable


def test_schema_is_json_serializable_and_models_success_and_error() -> None:
    schema = taxonomy_schema()
    assert schema["title"] == "ChannelFailureTaxonomyResult"
    assert "oneOf" in schema
    json.dumps(schema)


def test_classify_rate_limit_event_parses_retry_after_from_message() -> None:
    classification = classify_failure_event(
        channel="telegram",
        event={"message": "Too Many Requests: retry after 7"},
    )
    assert classification.category == FailureCategory.RATE_LIMITED
    assert classification.retryable is True
    assert classification.severity.value == "transient"
    assert classification.signals.get("retry_after_seconds") == 7


def test_invalid_event_json_object_required() -> None:
    with pytest.raises(InvalidTaxonomyInputError):
        classify_failure_event(channel="telegram", event=["not", "a", "mapping"])  # type: ignore[arg-type]


def test_parse_event_json_rejects_non_object() -> None:
    with pytest.raises(InvalidTaxonomyInputError):
        parse_event_json("[1, 2, 3]")


def test_probe_requires_config() -> None:
    with pytest.raises(MissingChannelConfigError):
        build_failure_taxonomy_report(FailureTaxonomyRequest(channel="telegram", probe=True, config=None))


def test_error_to_dict_is_deterministic() -> None:
    err = ChannelFailureTaxonomyError("boom", details={"a": 1})
    payload = err.to_dict()
    assert payload["ok"] is False
    assert payload["error"]["code"] == err.error_code
    assert payload["error"]["details"]["a"] == 1
