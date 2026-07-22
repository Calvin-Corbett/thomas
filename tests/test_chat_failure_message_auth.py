"""Chat failure messages must name the real problem.

An expired ChatGPT sign-in takes out EVERY model. Telling someone to "choose
another model" sends them hunting through the model list for something no model
can fix -- which is exactly what happened: two different models were tried and
both reported the same thing, because the failure was never about the model.
"""

from __future__ import annotations

import pytest

from thomas.marketplace.orchestrator.brain import _chat_failure_message

# The literal text Thomas logs when the stored credential is rejected.
_REAL_401 = "Reasoning failed: Token refresh failed with HTTP 401."


@pytest.mark.parametrize(
    "error",
    [
        _REAL_401,
        "Token refresh failed with HTTP 401.",
        "oauth error: invalid_grant",
        "provider returned status 401",
        "HTTP 401 Unauthorized",
    ],
)
def test_expired_signin_tells_you_to_log_in_again(error: str) -> None:
    msg = _chat_failure_message(error)
    assert "codex login" in msg, msg
    assert "sign-in has expired" in msg, msg


def test_expired_signin_does_not_advise_switching_models() -> None:
    """The specific misdirection this fixes."""
    msg = _chat_failure_message(_REAL_401)
    assert "another model" not in msg.lower()
    # ...and it says why switching would be pointless.
    assert "won't help" in msg


def test_rate_limit_still_suggests_another_model() -> None:
    """Switching IS reasonable advice for a rate limit -- don't over-correct."""
    msg = _chat_failure_message("provider status 429 rate limit")
    assert "rate-limited" in msg
    assert "another model" in msg


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
