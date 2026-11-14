"""Every model run gets a prompt-cache key of its own, so its calls stay on the machines holding the call before.

On 2026-11-06 the token log showed 47.7% of gpt-6.1-sol's prompt tokens served from cache: the Build lead sent no
key, and every helper of one mode and model shared one, so every run piled onto the same few machines. Regression for
thomas.core.llm_streaming_codex._run_cache_key and the per-helper key in build_agent_team.
"""

from __future__ import annotations

from thomas.core import capture_context
from thomas.core.llm_streaming_codex import _run_cache_key


def _key_in(run: str) -> str:
    token = capture_context.set_capture_run(run)
    try:
        return _run_cache_key()
    finally:
        capture_context.reset(token)


def test_one_run_keeps_one_key() -> None:
    assert _key_in("run-a") == _key_in("run-a")


def test_two_runs_get_two_keys() -> None:
    assert _key_in("run-a") != _key_in("run-b")


def test_the_key_is_short_and_does_not_name_the_run() -> None:
    key = _key_in("conversation-1234-turn-7")
    assert key.startswith("thomas-run-") and len(key) <= 40 and "conversation" not in key


def test_outside_a_run_there_is_no_key() -> None:
    assert capture_context.current() is None
    assert _run_cache_key() == ""
