from __future__ import annotations

from thomas.browser.workflow_runtime import (
    list_case_files,
    list_profiles,
    load_case,
    load_profile,
    validate_case_payload,
    validate_corpus,
)


def test_workflow_runtime_profile_lookup_and_listing() -> None:
    profiles = list_profiles()
    assert len(profiles) >= 192
    sample = load_profile("wf_profile_001")
    assert sample is not None
    assert sample.get("profile_id") == "wf_profile_001"


def test_workflow_runtime_case_load_and_validate() -> None:
    files = list_case_files(limit=5)
    assert len(files) == 5
    payload = load_case("0001")
    ok, errors = validate_case_payload(payload)
    assert ok is True
    assert errors == []


def test_workflow_runtime_corpus_validation_summary() -> None:
    summary = validate_corpus(limit=25)
    assert int(summary.get("total") or 0) == 25
    assert int(summary.get("invalid") or 0) == 0
