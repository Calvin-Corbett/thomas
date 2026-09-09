from __future__ import annotations

from thomas.browser.workflows import get_workflow_profile, list_workflow_profiles


def test_workflow_registry_lists_expected_volume_and_shape() -> None:
    profiles = list_workflow_profiles()
    assert len(profiles) >= 192
    ids = {str(row.get("profile_id") or "") for row in profiles}
    assert len(ids) == len(profiles)
    sample = profiles[0]
    assert sample.get("category")
    assert isinstance(sample.get("required_signals"), list)


def test_workflow_registry_lookup_returns_record() -> None:
    row = get_workflow_profile("wf_profile_001")
    assert row is not None
    assert row.get("profile_id") == "wf_profile_001"
