"""Thomas Embedding SDK -- AgentView embeddable component abstraction.

:class:`AgentView` is a *headless view model*: given a run id and a
:class:`~thomas.sdk.client.ThomasClient`, it exposes everything a host UI needs
to render and drive a Thomas Agent surface -- the run's live state, its event
feed, the pending approvals, and callable action handles the host binds to
buttons. It renders nothing itself, so any framework (web, TUI, native) can
embed it.

Typical host loop::

    view = AgentView(client, run_id)
    view.refresh()                       # pull state + events
    render(view.state)                   # host draws from the view model
    if view.state.pending_approvals:
        view.actions.approve(view.state.pending_approvals[0].approval_id)
    render(view.state)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from thomas.sdk.client import ApprovalRequest, RunDetail, RunEvent, ThomasClient

__all__ = ["ViewState", "ViewActions", "AgentView"]

#: Run statuses in which the agent is blocked waiting on the host/user.
WAITING_STATUSES = frozenset({"waiting_approval", "waiting", "paused", "blocked"})

#: Terminal run statuses.
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "error"})


@dataclass(frozen=True)
class ViewState:
    """Immutable snapshot a host UI binds to.

    Rebuilt on every :meth:`AgentView.refresh`; the host re-renders from it.
    """

    run_id: str
    status: str
    events: tuple[RunEvent, ...] = ()
    pending_approvals: tuple[ApprovalRequest, ...] = ()
    last_message: str | None = None
    error: str | None = None
    detail: RunDetail | None = None

    @property
    def is_waiting_approval(self) -> bool:
        return bool(self.pending_approvals) or self.status in WAITING_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def event_count(self) -> int:
        return len(self.events)


@dataclass
class ViewActions:
    """Callable action handles a host binds to UI controls.

    Each action performs the side effect through the client and then refreshes
    the owning view so ``view.state`` reflects the result immediately.
    """

    _view: AgentView = field(repr=False)

    def approve(self, approval_id: str, *, note: str | None = None) -> ViewState:
        """Approve a pending approval and refresh the view."""
        self._view.client.submit_approval(self._view.run_id, approval_id, approve=True, note=note)
        return self._view.refresh()

    def reject(self, approval_id: str, *, note: str | None = None) -> ViewState:
        """Reject a pending approval and refresh the view."""
        self._view.client.submit_approval(self._view.run_id, approval_id, approve=False, note=note)
        return self._view.refresh()

    def steer(self, text: str) -> ViewState:
        """Send a steering message and refresh the view."""
        self._view.client.submit_steer(self._view.run_id, text)
        return self._view.refresh()

    def refresh(self) -> ViewState:
        """Re-pull state and events without a side effect."""
        return self._view.refresh()


class AgentView:
    """Headless, embeddable view model for a single run.

    Attributes:
        client: the :class:`ThomasClient` backing this view.
        run_id: the run being observed.
        state: the current :class:`ViewState` (``None`` until first refresh).
        actions: the :class:`ViewActions` handles a host binds to controls.
    """

    def __init__(self, client: ThomasClient, run_id: str) -> None:
        self.client = client
        self.run_id = str(run_id)
        self._events: list[RunEvent] = []
        self._state: ViewState | None = None
        self.actions = ViewActions(self)

    @property
    def state(self) -> ViewState:
        """Current snapshot; refreshes lazily on first access."""
        if self._state is None:
            return self.refresh()
        return self._state

    def refresh(self) -> ViewState:
        """Pull the latest run detail and any new events, rebuild the state."""
        detail = self.client.get_run(self.run_id)
        # Incrementally drain only events past what we've already seen so a host
        # can poll cheaply as the run progresses.
        for event in self.client.stream_events(self.run_id, start=len(self._events)):
            self._events.append(event)
        self._state = self._build_state(detail)
        return self._state

    def _build_state(self, detail: RunDetail) -> ViewState:
        resolved = _resolved_approval_ids(self._events)
        pending: list[ApprovalRequest] = []
        for event in self._events:
            if event.event_type != "approval.requested":
                continue
            approval_id = str(event.payload.get("approval_id") or "")
            if not approval_id or approval_id in resolved:
                continue
            pending.append(
                ApprovalRequest(
                    approval_id=approval_id,
                    prompt=str(event.payload.get("prompt") or ""),
                    run_id=self.run_id,
                    event_index=event.index,
                    payload=dict(event.payload),
                )
            )
        return ViewState(
            run_id=self.run_id,
            status=detail.status,
            events=tuple(self._events),
            pending_approvals=tuple(pending),
            last_message=_last_message(self._events),
            error=detail.error,
            detail=detail,
        )


def _resolved_approval_ids(events: list[RunEvent]) -> set[str]:
    resolved: set[str] = set()
    for event in events:
        if event.event_type == "approval.resolved":
            approval_id = str(event.payload.get("approval_id") or "")
            if approval_id:
                resolved.add(approval_id)
    return resolved


def _last_message(events: list[RunEvent]) -> str | None:
    for event in reversed(events):
        if event.event_type == "agent.message":
            text = event.payload.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return None
