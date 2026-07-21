"""Acceptance tests for the Thomas Embedding SDK (CAP-131).

Proves, fully offline against the hermetic fake transport:

1. the client round-trips dispatch / list / get;
2. the AgentView exposes correct state + event feed + action handles;
3. a simulated third-party host drives a full embedded flow end to end
   (dispatch -> stream events -> render view state -> submit an approval);
4. the public API surface is stable (a contract test enumerating it).
"""

from __future__ import annotations

import inspect

import pytest

import thomas.sdk as sdk
from thomas.sdk import (
    AgentView,
    ApiError,
    FakeTransport,
    RunDetail,
    RunEvent,
    RunSummary,
    ThomasClient,
    TransportError,
    api_surface,
)


@pytest.fixture
def clock():
    """Deterministic monotonic clock injected into the fake transport."""
    state = {"t": 0}

    def _tick() -> int:
        state["t"] += 5
        return state["t"]

    return _tick


@pytest.fixture
def client(clock):
    return ThomasClient(FakeTransport(clock=clock))


# ---------------------------------------------------------------------------
# 1. Client round-trips dispatch / list / get over the fake transport
# ---------------------------------------------------------------------------


def test_client_round_trips_dispatch_list_get(client):
    run = client.dispatch("summarize the repo", session_id="s1", profile="dev")
    assert isinstance(run, RunDetail)
    assert run.run_id
    assert run.status == "waiting_approval"
    assert run.session_id == "s1"
    assert run.profile == "dev"

    # get_run returns the same run
    fetched = client.get_run(run.run_id)
    assert isinstance(fetched, RunDetail)
    assert fetched.run_id == run.run_id
    assert fetched.status == "waiting_approval"

    # list_runs surfaces it as a summary row
    rows = client.list_runs()
    assert rows and isinstance(rows[0], RunSummary)
    assert any(r.run_id == run.run_id for r in rows)

    # a second dispatch produces a distinct run, and list filters by session
    other = client.dispatch("second task", session_id="s2")
    assert other.run_id != run.run_id
    only_s1 = client.list_runs(filters={"session_id": "s1"})
    assert [r.run_id for r in only_s1] == [run.run_id]


def test_get_run_missing_raises_api_error(client):
    with pytest.raises(ApiError) as exc:
        client.get_run("does-not-exist")
    assert exc.value.status == 404


def test_dispatch_requires_prompt(client):
    with pytest.raises(ApiError) as exc:
        client.dispatch("   ")
    assert exc.value.status == 400


# ---------------------------------------------------------------------------
# 2. AgentView exposes correct state + event feed + actions
# ---------------------------------------------------------------------------


def test_agent_view_exposes_state_feed_and_actions(client):
    run = client.dispatch("do the thing")
    view = AgentView(client, run.run_id)
    state = view.refresh()

    # event feed is present and ordered
    assert isinstance(state.events, tuple)
    assert all(isinstance(e, RunEvent) for e in state.events)
    types = [e.event_type for e in state.events]
    assert types == ["run.started", "agent.message", "approval.requested"]
    assert [e.index for e in state.events] == [0, 1, 2]

    # derived state
    assert state.status == "waiting_approval"
    assert state.is_waiting_approval is True
    assert state.is_terminal is False
    assert state.last_message == "Working on: do the thing"

    # pending approval derived from the event feed
    assert len(state.pending_approvals) == 1
    approval = state.pending_approvals[0]
    assert approval.approval_id == f"{run.run_id}-ap1"
    assert approval.run_id == run.run_id

    # action handles exist and are callable
    for name in ("approve", "reject", "steer", "refresh"):
        assert callable(getattr(view.actions, name))


def test_agent_view_steer_action_appends_event(client):
    run = client.dispatch("task")
    view = AgentView(client, run.run_id)
    view.refresh()
    before = view.state.event_count
    state = view.actions.steer("focus on tests")
    assert state.event_count == before + 1
    assert state.events[-1].event_type == "steer.received"
    assert state.events[-1].payload["text"] == "focus on tests"


def test_agent_view_reject_marks_run_failed(client):
    run = client.dispatch("risky task")
    view = AgentView(client, run.run_id)
    view.refresh()
    approval_id = view.state.pending_approvals[0].approval_id
    state = view.actions.reject(approval_id, note="not allowed")
    assert state.status == "completed"
    assert state.is_terminal is True
    assert state.error == "rejected"
    assert not state.pending_approvals


# ---------------------------------------------------------------------------
# 3. Simulated third-party host drives a full embedded flow
# ---------------------------------------------------------------------------


class ThirdPartyHost:
    """A minimal stand-in for an external application embedding the SDK.

    It knows nothing of Thomas internals -- it only binds to the public
    AgentView state and action handles, exactly as a real host UI would.
    """

    def __init__(self, client: ThomasClient) -> None:
        self._client = client
        self.rendered: list[dict[str, object]] = []

    def render(self, view: AgentView) -> None:
        s = view.state
        self.rendered.append(
            {
                "status": s.status,
                "events": [e.event_type for e in s.events],
                "last_message": s.last_message,
                "approvals": [a.approval_id for a in s.pending_approvals],
            }
        )

    def run_embedded_flow(self, prompt: str) -> AgentView:
        # dispatch
        run = self._client.dispatch(prompt)
        view = AgentView(self._client, run.run_id)

        # stream events -> render
        view.refresh()
        self.render(view)

        # the host sees a required approval and acts on it
        assert view.state.pending_approvals, "expected an approval to be surfaced"
        view.actions.approve(view.state.pending_approvals[0].approval_id)

        # stream more events -> render final state
        self.render(view)
        return view


def test_third_party_host_full_embedded_flow(client):
    host = ThirdPartyHost(client)
    view = host.run_embedded_flow("ship the feature")

    # two renders captured: mid-flow (waiting) then terminal (completed)
    assert len(host.rendered) == 2
    first, last = host.rendered

    assert first["status"] == "waiting_approval"
    assert first["approvals"], "host should have seen a pending approval"
    assert "approval.requested" in first["events"]

    assert last["status"] == "completed"
    assert last["approvals"] == []
    assert "approval.resolved" in last["events"]
    assert "run.completed" in last["events"]
    assert last["last_message"] == "Approved -- finishing up."

    # final view model reflects a completed, non-blocked run
    assert view.state.is_terminal is True
    assert view.state.is_waiting_approval is False
    assert view.state.detail is not None
    assert view.state.detail.ok is True


def test_stream_events_drains_full_feed(client):
    run = client.dispatch("stream me")
    # page_size of 1 forces multiple pages, proving the pager catches up to total
    streamed = list(client.stream_events(run.run_id, page_size=1))
    total, _ = client.get_events(run.run_id)
    assert len(streamed) == total == 3
    assert [e.index for e in streamed] == [0, 1, 2]


# ---------------------------------------------------------------------------
# 4. Public API surface is stable (contract test enumerating it)
# ---------------------------------------------------------------------------


def test_public_api_surface_contract():
    surface = api_surface()

    # exports match __all__ exactly (minus the api_surface entry itself)
    expected_exports = {
        "__version__",
        "ThomasClient",
        "Transport",
        "HttpTransport",
        "FakeTransport",
        "RunSummary",
        "RunDetail",
        "RunEvent",
        "ApprovalRequest",
        "AgentView",
        "ViewState",
        "ViewActions",
        "SdkError",
        "TransportError",
        "ApiError",
    }
    assert set(surface["exports"]) == expected_exports
    # every declared export is actually importable from the package
    for name in surface["exports"]:
        assert hasattr(sdk, name), f"missing public export: {name}"

    # client method contract matches the real callables
    assert surface["client_methods"] == (
        "dispatch",
        "list_runs",
        "get_run",
        "get_events",
        "stream_events",
        "submit_approval",
        "submit_steer",
    )
    for name in surface["client_methods"]:
        assert callable(getattr(ThomasClient, name)), f"client missing method: {name}"

    # view + action + state contracts match the real objects
    for name in surface["view_methods"]:
        assert callable(getattr(AgentView, name))
    for name in surface["view_action_methods"]:
        assert callable(getattr(sdk.ViewActions, name))
    state_fields = set(sdk.ViewState.__dataclass_fields__)
    assert set(surface["view_state_fields"]) <= state_fields


def test_transport_protocol_is_satisfied_by_both_transports():
    from thomas.sdk import HttpTransport, Transport

    assert isinstance(FakeTransport(), Transport)
    assert isinstance(HttpTransport(), Transport)


def test_dispatch_signature_is_stable():
    sig = inspect.signature(ThomasClient.dispatch)
    params = list(sig.parameters)
    assert params[:2] == ["self", "prompt"]
    for kw in ("session_id", "profile", "mode", "metadata"):
        assert kw in sig.parameters


# ---------------------------------------------------------------------------
# Transport error typing (real default transport surfaces typed faults)
# ---------------------------------------------------------------------------


def test_http_transport_maps_faults_to_typed_errors():
    """HttpTransport must raise typed SDK errors, not leak urllib faults.

    Uses a stub opener so it stays hermetic (no socket, no server).
    """
    import io
    import urllib.error

    from thomas.sdk import HttpTransport

    class _ApiOpener:
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 500, "boom", hdrs=None, fp=io.BytesIO(b"server on fire"))

    class _NetOpener:
        def open(self, req, timeout=None):
            raise urllib.error.URLError("name resolution failed")

    with pytest.raises(ApiError) as api_exc:
        HttpTransport(opener=_ApiOpener()).request("GET", "/api/runs")
    assert api_exc.value.status == 500

    with pytest.raises(TransportError):
        HttpTransport(opener=_NetOpener()).request("GET", "/api/runs")
