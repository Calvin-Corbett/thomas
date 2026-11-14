"""Praxis must distinguish a busy provider from an exhausted account."""

from thomas.server.praxis.quota import QuotaClassifier, choose_credential, park_child, re_admit_due


def test_short_429_storm_stays_transient_and_success_resets_streak() -> None:
    classifier = QuotaClassifier()
    for index in range(5):
        decision = classifier.observe("account-a", status=429, now=1000 + index * 200)
        assert decision.kind == "transient"
    assert classifier.observe("account-a", status=200, now=1900).kind == "clean"
    assert classifier.observe("account-a", status=429, now=2000).kind == "transient"


def test_six_429s_over_fifteen_minutes_mark_only_that_credential_exhausted() -> None:
    classifier = QuotaClassifier()
    for index in range(5):
        classifier.observe("account-a", status=429, now=1000 + index * 190)
    decision = classifier.observe("account-a", status=429, now=1960)
    assert (decision.kind, decision.reason, decision.retry_at) == ("quota", "429_streak", 2260)
    assert classifier.observe("account-b", status=429, now=1960).kind == "transient"


def test_explicit_quota_and_long_reset_are_detected_without_generic_rate_limit_false_positive() -> None:
    classifier = QuotaClassifier()
    explicit = classifier.observe("a", status=403, error={"error": {"code": "insufficient_quota"}}, now=1000)
    assert (explicit.kind, explicit.reason) == ("quota", "provider_quota")
    long_reset = classifier.observe("b", status=429, headers={"Retry-After": "901"}, now=1000)
    assert (long_reset.kind, long_reset.retry_at) == ("quota", 1901)
    short_reset = classifier.observe("c", status=429, headers={"Retry-After": "30"}, now=1000)
    assert (short_reset.kind, short_reset.retry_at) == ("transient", 1030)
    generic = classifier.observe("d", status=429, error={"code": "rate_limit_exceeded"}, now=1000)
    assert generic.kind == "transient"


def test_same_provider_failover_is_automatic_other_provider_requires_consent() -> None:
    pool = {"codex-a": "codex", "codex-b": "codex", "claude-a": "claude"}
    exhausted = {"codex-a": 2000}
    assert (
        choose_credential("codex-a", credentials=pool, exhausted_until=exhausted, allowed_providers=(), now=1000)
        == "codex-b"
    )
    exhausted["codex-b"] = 2000
    assert (
        choose_credential("codex-a", credentials=pool, exhausted_until=exhausted, allowed_providers=(), now=1000)
        is None
    )
    assert (
        choose_credential(
            "codex-a", credentials=pool, exhausted_until=exhausted, allowed_providers={"claude"}, now=1000
        )
        == "claude-a"
    )


def test_parked_continuation_releases_active_state_and_reenters_fifo() -> None:
    classifier = QuotaClassifier()
    decision = classifier.observe("account-a", status=429, error={"code": "quota_exceeded"}, now=1000)
    first = {"agent_id": "agent-1", "state": "running", "attempt_started_at": 700}
    later = {"agent_id": "agent-2", "state": "running", "attempt_started_at": 710}
    park_child(first, decision)
    park_child(later, decision)
    assert first["state"] == "quota_wait" and first["attempt_started_at"] is None
    assert re_admit_due((later, first), now=1200) == []
    assert [row["agent_id"] for row in re_admit_due((later, first), now=1300)] == ["agent-1", "agent-2"]
    assert first["state"] == later["state"] == "starting"


def test_available_alternate_wakes_parked_child_before_reset() -> None:
    row = {"agent_id": "agent-1", "state": "running"}
    decision = QuotaClassifier().observe("account-a", status=429, headers={"Retry-After": "901"}, now=1000)
    park_child(row, decision)
    assert re_admit_due([row], now=1001, available=["account-b"]) == [row]
