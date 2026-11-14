"""Chat failure messages must name the real problem.

An unattributed access-token 401 does not prove whether the live Codex login works.
A verified live-token refusal or a rejected refresh token warrants new sign-in advice.
"""

from __future__ import annotations

import pytest

from thomas.marketplace.orchestrator.brain import _chat_failure_message

# The refresh-token 401 raised after a rejected stored refresh credential.
_REAL_401 = "Reasoning failed: Token refresh failed with HTTP 401."


@pytest.mark.parametrize(
    "error",
    [
        "oauth error: invalid_grant",
        "provider returned status 401",
        "HTTP 401 Unauthorized",
    ],
)
def test_ambiguous_auth_failure_does_not_diagnose_live_login(error: str) -> None:
    msg = _chat_failure_message(error)
    assert "codex login" not in msg, msg
    assert "sign-in has expired" not in msg, msg


def test_refresh_401_names_signin_remedy_and_working_alternative() -> None:
    """A rejected refresh token needs a new sign-in, unlike an unattributed 401."""
    msg = _chat_failure_message(_REAL_401)
    assert "codex login" in msg
    assert "Local model" in msg
    assert "refresh token" in msg
    # must not imply the whole system is down
    assert "no model can be reached" not in msg


def test_rejected_live_login_names_server_reason_and_signin_remedy() -> None:
    from thomas.core import model_auth_health

    model_auth_health.record_auth_success()
    msg = _chat_failure_message(
        "ChatGPT/Codex HTTP 401: The live Codex login was revoked or invalidated by the server. "
        "Run `codex login` to sign in again."
    )
    assert "revoked or invalidated" in msg
    assert "codex login" in msg
    assert "expired" not in msg
    assert model_auth_health._LAST_AUTH_FAILURE is not None
    model_auth_health.record_auth_success()


def test_second_stored_401_with_same_live_token_requires_signin_and_records_health() -> None:
    from thomas.core import model_auth_health

    model_auth_health.record_auth_success()
    msg = _chat_failure_message(
        "ChatGPT/Codex HTTP 401: The stored token was revoked or invalidated by the server. "
        "A retry with a different stored token was also rejected. "
        "The live Codex login still contains the rejected stored token."
    )
    assert "codex login" in msg
    assert "expired" not in msg
    assert model_auth_health._LAST_AUTH_FAILURE is not None
    model_auth_health.record_auth_success()


def test_refresh_401_records_auth_failure_but_stored_access_401_does_not() -> None:
    from thomas.core import model_auth_health

    model_auth_health.record_auth_success()
    _chat_failure_message("ChatGPT/Codex HTTP 401: The stored token was revoked or invalidated by the server.")
    assert model_auth_health._LAST_AUTH_FAILURE is None
    _chat_failure_message(_REAL_401)
    assert model_auth_health._LAST_AUTH_FAILURE is not None
    model_auth_health.record_auth_success()


def test_expired_live_login_reports_expiry_only_when_verified() -> None:
    msg = _chat_failure_message("ChatGPT/Codex HTTP 401: The live Codex login was expired by the server.")
    assert "server expired your live Codex login" in msg
    assert "codex login" in msg
    assert "revoked" not in msg


def test_rate_limit_still_suggests_another_model() -> None:
    """Switching IS reasonable advice for a rate limit -- don't over-correct.

    It is now named advice: the models offered are the ones that answered at the
    catalog's last check, rather than "choose another model" with no list.
    """
    msg = _chat_failure_message("provider status 429 rate limit", alternatives=("Local",))
    assert "rate limit" in msg
    assert "I can answer on Local meanwhile" in msg
    assert "model menu" in msg


def test_a_rate_limit_with_nowhere_to_switch_says_so() -> None:
    """You met the old text with no second model: "there was no other model I could choose"."""
    msg = _chat_failure_message("provider status 429 rate limit")
    assert "said nothing about which limit or when it resets" in msg
    assert "No other model on this machine is ready" in msg


def test_unreachable_model_still_reports_a_reach_problem() -> None:
    msg = _chat_failure_message("ConnectError: connection refused")
    assert "couldn't reach" in msg


def test_not_connected_still_points_at_easy_setup() -> None:
    msg = _chat_failure_message("oauth account not connected")
    assert "Easy Setup" in msg


def test_unknown_failure_keeps_the_generic_fallback() -> None:
    msg = _chat_failure_message("something nobody has seen before")
    assert "couldn't get an answer" in msg


def test_empty_error_does_not_raise() -> None:
    assert _chat_failure_message(None)
    assert _chat_failure_message("")
