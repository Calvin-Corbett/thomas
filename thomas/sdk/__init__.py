"""Thomas Embedding SDK -- a full-harness SDK for embedding an Agent View.

This package is the stable, documented public surface a third party uses to
embed a Thomas Agent experience inside their own host application:

* :class:`ThomasClient` -- create/list/get runs, dispatch work, stream the
  event feed, submit approvals, and steer, over an injectable
  :class:`Transport`.
* :class:`HttpTransport` -- the real default transport (stdlib ``urllib`` to a
  local ``thomas.server``).
* :class:`FakeTransport` -- a hermetic in-memory double emulating the same HTTP
  contract for offline embedding and tests.
* :class:`AgentView` -- a headless, embeddable view model exposing run state,
  the event feed, and action handles a host UI binds to.

Quickstart (fully offline against the fake transport)::

    from thomas.sdk import ThomasClient, FakeTransport, AgentView

    client = ThomasClient(FakeTransport())
    run = client.dispatch("summarize the repo")

    view = AgentView(client, run.run_id)
    view.refresh()
    if view.state.pending_approvals:
        view.actions.approve(view.state.pending_approvals[0].approval_id)
    assert view.state.status == "completed"

The same code runs against a live server by swapping the transport::

    client = ThomasClient(HttpTransport("http://127.0.0.1:8899", token=...))
"""

from __future__ import annotations

from thomas.sdk.agent_view import AgentView, ViewActions, ViewState
from thomas.sdk.client import (
    ApiError,
    ApprovalRequest,
    FakeTransport,
    HttpTransport,
    RunDetail,
    RunEvent,
    RunSummary,
    SdkError,
    ThomasClient,
    Transport,
    TransportError,
)

__version__ = "1.0.0"

__all__ = [
    "__version__",
    # client + transports
    "ThomasClient",
    "Transport",
    "HttpTransport",
    "FakeTransport",
    # data model
    "RunSummary",
    "RunDetail",
    "RunEvent",
    "ApprovalRequest",
    # view
    "AgentView",
    "ViewState",
    "ViewActions",
    # errors
    "SdkError",
    "TransportError",
    "ApiError",
    # contract
    "api_surface",
]


def api_surface() -> dict[str, tuple[str, ...]]:
    """Return the frozen public API contract of the embedding SDK.

    The contract test asserts this matches both this literal and the actual
    exported objects, so the third-party-facing surface cannot drift without a
    deliberate, reviewed change.
    """
    return {
        "exports": tuple(name for name in __all__ if name != "api_surface"),
        "client_methods": ThomasClient.API_METHODS,
        "view_methods": ("refresh",),
        "view_action_methods": ("approve", "reject", "steer", "refresh"),
        "view_state_fields": (
            "run_id",
            "status",
            "events",
            "pending_approvals",
            "last_message",
            "error",
            "detail",
        ),
    }
