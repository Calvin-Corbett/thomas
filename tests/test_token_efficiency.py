"""Tests for CAP-095 release-level token-efficiency engineering.

Acceptance line: "Record retry rate and first-pass success per release against
the token ledger."
"""

from __future__ import annotations

import json

import pytest

from thomas.core.token_efficiency import (
    ENV_PATH,
    ReleaseComparison,
    TokenEfficiencyLedger,
)


@pytest.fixture()
def ledger_path(tmp_path):
    return tmp_path / "efficiency.json"


def test_mixed_runs_yield_correct_retry_and_first_pass_rates(ledger_path):
    ledger = TokenEfficiencyLedger(path=ledger_path)
    # 4 runs: 2 first-pass successes, 1 retried success, 1 retried failure.
    ledger.record_run("v1", attempts=1, succeeded=True, tokens=100)
    ledger.record_run("v1", attempts=1, succeeded=True, tokens=100)
    ledger.record_run("v1", attempts=2, succeeded=True, tokens=300)
    ledger.record_run("v1", attempts=3, succeeded=False, tokens=400)

    report = ledger.release_report("v1")

    assert report.runs == 4
    # 2 of 4 runs needed at least one retry.
    assert report.retry_rate == 0.5
    # 2 of 4 runs succeeded on the first attempt.
    assert report.first_pass_rate == 0.5


def test_tokens_accumulate_and_tokens_per_success_is_correct(ledger_path):
    ledger = TokenEfficiencyLedger(path=ledger_path)
    ledger.record_run("v1", attempts=1, succeeded=True, tokens=200)
    ledger.record_run("v1", attempts=2, succeeded=True, tokens=600)
    ledger.record_run("v1", attempts=1, succeeded=False, tokens=200)

    report = ledger.release_report("v1")

    # Tokens accumulate across every run in the release (the token ledger).
    assert report.total_tokens == 1000
    # Two of the three runs succeeded -> 1000 tokens / 2 successes = 500.
    assert report.successes == 2
    assert report.tokens_per_success == 500.0


def test_all_first_pass_release_has_zero_retry_rate(ledger_path):
    ledger = TokenEfficiencyLedger(path=ledger_path)
    for _ in range(5):
        ledger.record_run("clean", attempts=1, succeeded=True, tokens=50)

    report = ledger.release_report("clean")

    assert report.runs == 5
    assert report.retry_rate == 0.0
    assert report.first_pass_rate == 1.0
    assert report.tokens_per_success == 50.0


def test_compare_releases_shows_improvement(ledger_path):
    ledger = TokenEfficiencyLedger(path=ledger_path)
    # Baseline: only half succeed first-pass, and it burns 1000 tokens/success.
    ledger.record_run("v1", attempts=1, succeeded=True, tokens=1000)
    ledger.record_run("v1", attempts=3, succeeded=True, tokens=3000)
    ledger.record_run("v1", attempts=2, succeeded=False, tokens=2000)
    # Candidate: all first-pass, and much cheaper per success.
    ledger.record_run("v2", attempts=1, succeeded=True, tokens=400)
    ledger.record_run("v2", attempts=1, succeeded=True, tokens=400)

    base = ledger.release_report("v1")
    cand = ledger.release_report("v2")
    comparison = ledger.compare_releases("v1", "v2")

    assert isinstance(comparison, ReleaseComparison)
    # Higher first-pass success in the candidate.
    assert cand.first_pass_rate > base.first_pass_rate
    assert comparison.first_pass_improved is True
    assert comparison.first_pass_delta > 0.0
    # Lower tokens-per-success in the candidate.
    assert cand.tokens_per_success is not None and base.tokens_per_success is not None
    assert cand.tokens_per_success < base.tokens_per_success
    assert comparison.tokens_per_success_improved is True
    assert comparison.tokens_per_success_delta is not None
    assert comparison.tokens_per_success_delta < 0.0
    # Both dimensions improved -> overall improvement.
    assert comparison.improved is True


def test_compare_releases_no_improvement_when_regressed(ledger_path):
    ledger = TokenEfficiencyLedger(path=ledger_path)
    ledger.record_run("v1", attempts=1, succeeded=True, tokens=100)
    ledger.record_run("v2", attempts=2, succeeded=True, tokens=800)

    comparison = ledger.compare_releases("v1", "v2")

    # v2 has worse first-pass (0.0 vs 1.0) and higher tokens/success.
    assert comparison.first_pass_improved is False
    assert comparison.tokens_per_success_improved is False
    assert comparison.improved is False


def test_persistence_round_trips(ledger_path):
    ledger = TokenEfficiencyLedger(path=ledger_path)
    ledger.record_run("v1", attempts=1, succeeded=True, tokens=100)
    ledger.record_run("v1", attempts=2, succeeded=False, tokens=250)
    ledger.record_run("v2", attempts=1, succeeded=True, tokens=90)

    # File exists and is valid JSON.
    assert ledger_path.exists()
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert "v1" in payload["releases"]

    # A fresh ledger over the same path recovers identical reports.
    reloaded = TokenEfficiencyLedger(path=ledger_path)
    original = ledger.release_report("v1")
    recovered = reloaded.release_report("v1")
    assert recovered.to_dict() == original.to_dict()
    assert reloaded.release_report("v2").total_tokens == 90
    assert reloaded.releases() == ["v1", "v2"]


def test_empty_release_is_handled(ledger_path):
    ledger = TokenEfficiencyLedger(path=ledger_path)

    report = ledger.release_report("never-recorded")

    assert report.runs == 0
    assert report.retry_rate == 0.0
    assert report.first_pass_rate == 0.0
    assert report.total_tokens == 0
    assert report.successes == 0
    # tokens_per_success is undefined (None) rather than a divide-by-zero.
    assert report.tokens_per_success is None


def test_env_var_overrides_path(tmp_path, monkeypatch):
    target = tmp_path / "from_env.json"
    monkeypatch.setenv(ENV_PATH, str(target))
    ledger = TokenEfficiencyLedger()
    ledger.record_run("v1", attempts=1, succeeded=True, tokens=10)

    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["releases"]["v1"]["total_tokens"] == 10
