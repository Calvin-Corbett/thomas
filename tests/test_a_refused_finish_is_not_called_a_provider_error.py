"""A finish that Thomas's own checks refused is not reported as a provider error.

Every error a worker raised became "provider-native worker reported a retryable
error", and the chat told you "the background execution hit a retryable provider
error". On 2026-09-22 three self-fixes ended that way while no provider had
failed: the completion gate had refused the worker's finish. The provider's own
error text still never reaches the chat; what does is whether Thomas refused it.
"""

from __future__ import annotations

from tests.test_completion_gate import _run_coding
from thomas.core.events import EventType
from thomas.server.chat_delegation_deliverable import _WorkerFatal, _WorkerRetry
from thomas.server.chat_delegation_runner_events import _worker_error


def test_a_finish_the_gate_refused_says_so(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    events = _run_coding(["Applied the fix.", "Done."])
    blocked = [event for event in events if event.type == EventType.AGENT_ERROR]
    assert blocked, "the gate must refuse this run for the test to mean anything"

    # worker_runtime turns an AGENT_ERROR into exactly this event.
    exc = _worker_error({"type": "error", "error": str(blocked[-1].data.get("error")), "retryable": True})

    assert isinstance(exc, _WorkerRetry)
    assert "provider" not in str(exc)
    assert "acceptance checks" in str(exc)


def test_a_provider_failure_keeps_its_name_and_hides_its_detail():
    exc = _worker_error({"type": "error", "error": "429 from upstream, key sk-abc123", "retryable": True})

    assert isinstance(exc, _WorkerRetry)
    assert str(exc) == "provider-native worker reported a retryable error"


def test_a_non_retryable_error_is_still_fatal():
    exc = _worker_error({"type": "error", "error": "the run was interrupted", "retryable": False})

    assert isinstance(exc, _WorkerFatal)
    assert str(exc) == "provider-native worker reported a non-retryable error"
