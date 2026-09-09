"""Ticket-system providers for Thomas (Jira/Linear-style status sync).

This module defines a small :class:`TicketProvider` protocol plus two
implementations:

* :class:`LinearProvider` -- a REAL adapter that talks to Linear's GraphQL API
  over stdlib ``urllib.request`` (no new pip dependencies). The API token is
  read from an injected provider callable or the ``LINEAR_API_KEY`` environment
  variable *at call time* and is never logged (``repr`` redacts it).
* :class:`FakeProvider` -- a hermetic, in-memory implementation used by tests so
  the full sync behavior can be proven offline with no network access.

Live use of :class:`LinearProvider` is credential-gated: it only performs real
network calls when a Linear API key is available. Unit tests exercise the
:class:`FakeProvider`; the real adapter is only exercised when credentials are
present in the environment.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable

LINEAR_GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"
_ENV_TOKEN_KEY = "LINEAR_API_KEY"


class TicketProviderError(RuntimeError):
    """Raised when a ticket provider call fails."""


@runtime_checkable
class TicketProvider(Protocol):
    """Minimal contract the sync engine depends on.

    Implementations must never leak credentials through ``repr`` or logs.
    """

    def get_ticket(self, ticket_id: str) -> Mapping[str, Any]:
        """Return the raw ticket payload for ``ticket_id``."""
        ...

    def set_ticket_state(self, ticket_id: str, state_name: str) -> Mapping[str, Any]:
        """Move ``ticket_id`` to the workflow state named ``state_name``.

        Returns the updated raw ticket payload.
        """
        ...


def _safe_string(value: Any) -> str:
    return str(value or "").strip()


class LinearProvider:
    """Real Linear GraphQL adapter.

    The token is resolved lazily on every call from, in order of precedence, an
    injected ``token_provider`` callable, an explicit ``api_key`` argument, or
    the ``LINEAR_API_KEY`` environment variable. It is held only transiently and
    is redacted from ``repr`` so it can never end up in logs or tracebacks.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        token_provider: Callable[[], str] | None = None,
        endpoint: str = LINEAR_GRAPHQL_ENDPOINT,
        timeout_s: float = 20.0,
        opener: Callable[[urllib.request.Request, float], bytes] | None = None,
    ) -> None:
        self._api_key = api_key
        self._token_provider = token_provider
        self._endpoint = _safe_string(endpoint) or LINEAR_GRAPHQL_ENDPOINT
        self._timeout_s = max(1.0, float(timeout_s))
        # ``opener`` exists purely for hermetic testing of the transport; the
        # default performs a real network call.
        self._opener = opener or self._default_opener

    def __repr__(self) -> str:  # pragma: no cover - trivial, but security-relevant
        # Never render the token. Only reveal *whether* one is configured.
        has_token = bool(self._api_key or self._token_provider or os.environ.get(_ENV_TOKEN_KEY))
        return f"LinearProvider(endpoint={self._endpoint!r}, token={'set' if has_token else 'unset'})"

    __str__ = __repr__

    def _resolve_token(self) -> str:
        if self._token_provider is not None:
            token = _safe_string(self._token_provider())
            if token:
                return token
        if self._api_key:
            token = _safe_string(self._api_key)
            if token:
                return token
        token = _safe_string(os.environ.get(_ENV_TOKEN_KEY))
        if token:
            return token
        raise TicketProviderError("No Linear API key available. Set LINEAR_API_KEY or inject a token_provider.")

    @staticmethod
    def _default_opener(req: urllib.request.Request, timeout_s: float) -> bytes:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.read()

    def _graphql(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        token = self._resolve_token()
        body = json.dumps({"query": query, "variables": dict(variables)}).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            method="POST",
            headers={
                # Linear personal API keys are sent as the raw Authorization
                # header value; OAuth access tokens use the "Bearer " prefix.
                "Authorization": token,
                "Content-Type": "application/json",
                "User-Agent": "thomas-ticket-sync",
            },
        )
        try:
            raw = self._opener(req, self._timeout_s)
        except urllib.error.HTTPError as exc:
            # Do not include the token; HTTPError repr never carries it.
            raise TicketProviderError(f"Linear API HTTP error: {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise TicketProviderError(f"Linear API transport error: {exc.reason}") from exc
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise TicketProviderError("Linear API returned invalid JSON.") from exc
        if not isinstance(payload, Mapping):
            raise TicketProviderError("Linear API returned a non-object response.")
        errors = payload.get("errors")
        if errors:
            # ``errors`` is provider-authored data, safe to surface (no token).
            raise TicketProviderError(f"Linear GraphQL errors: {errors}")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise TicketProviderError("Linear API response missing 'data'.")
        return dict(data)

    def get_ticket(self, ticket_id: str) -> Mapping[str, Any]:
        query = (
            "query Issue($id: String!) {"
            " issue(id: $id) {"
            " id identifier title description url"
            " assignee { name email }"
            " state { id name type }"
            " team { id }"
            " updatedAt"
            " } }"
        )
        data = self._graphql(query, {"id": _safe_string(ticket_id)})
        issue = data.get("issue")
        if not isinstance(issue, Mapping):
            raise TicketProviderError(f"Linear issue not found: {ticket_id!r}")
        return dict(issue)

    def _resolve_state_id(self, team_id: str, state_name: str) -> str:
        query = "query TeamStates($id: String!) { team(id: $id) { states { nodes { id name } } } }"
        data = self._graphql(query, {"id": _safe_string(team_id)})
        team = data.get("team")
        nodes: list[Any] = []
        if isinstance(team, Mapping):
            states = team.get("states")
            if isinstance(states, Mapping) and isinstance(states.get("nodes"), list):
                nodes = states["nodes"]
        target = _safe_string(state_name).lower()
        for node in nodes:
            if isinstance(node, Mapping) and _safe_string(node.get("name")).lower() == target:
                state_id = _safe_string(node.get("id"))
                if state_id:
                    return state_id
        raise TicketProviderError(f"No Linear workflow state named {state_name!r} on team {team_id!r}.")

    def set_ticket_state(self, ticket_id: str, state_name: str) -> Mapping[str, Any]:
        ticket = self.get_ticket(ticket_id)
        team = ticket.get("team")
        team_id = _safe_string(team.get("id")) if isinstance(team, Mapping) else ""
        if not team_id:
            raise TicketProviderError(f"Ticket {ticket_id!r} has no team; cannot resolve state.")
        state_id = self._resolve_state_id(team_id, state_name)
        mutation = (
            "mutation Move($id: String!, $stateId: String!) {"
            " issueUpdate(id: $id, input: { stateId: $stateId }) {"
            " success issue { id identifier state { id name type } }"
            " } }"
        )
        data = self._graphql(
            mutation,
            {"id": _safe_string(ticket_id), "stateId": state_id},
        )
        result = data.get("issueUpdate")
        if not isinstance(result, Mapping) or not result.get("success"):
            raise TicketProviderError(f"Linear failed to update ticket {ticket_id!r}.")
        issue = result.get("issue")
        return dict(issue) if isinstance(issue, Mapping) else self.get_ticket(ticket_id)


class FakeProvider:
    """Hermetic in-memory ticket provider for tests.

    Tickets are stored as plain dicts keyed by ``id`` (and ``identifier`` if
    present). Every state write is recorded in :attr:`state_writes` so tests can
    assert bidirectional propagation without a network.
    """

    def __init__(self, tickets: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._tickets: dict[str, dict[str, Any]] = {}
        self.state_writes: list[tuple[str, str]] = []
        for key, ticket in (tickets or {}).items():
            self.add_ticket({"id": key, **dict(ticket)})

    def add_ticket(self, ticket: Mapping[str, Any]) -> None:
        record = dict(ticket)
        ticket_id = _safe_string(record.get("id"))
        if not ticket_id:
            raise ValueError("Fake ticket requires an 'id'.")
        self._tickets[ticket_id] = record
        identifier = _safe_string(record.get("identifier"))
        if identifier:
            self._tickets[identifier] = record

    def get_ticket(self, ticket_id: str) -> Mapping[str, Any]:
        key = _safe_string(ticket_id)
        if key not in self._tickets:
            raise TicketProviderError(f"Fake ticket not found: {ticket_id!r}")
        return dict(self._tickets[key])

    def set_ticket_state(self, ticket_id: str, state_name: str) -> Mapping[str, Any]:
        key = _safe_string(ticket_id)
        if key not in self._tickets:
            raise TicketProviderError(f"Fake ticket not found: {ticket_id!r}")
        record = self._tickets[key]
        state = record.get("state")
        if isinstance(state, Mapping):
            new_state = dict(state)
            new_state["name"] = _safe_string(state_name)
            record["state"] = new_state
        else:
            record["state"] = {"name": _safe_string(state_name)}
        self.state_writes.append((key, _safe_string(state_name)))
        return dict(record)


__all__ = [
    "LINEAR_GRAPHQL_ENDPOINT",
    "FakeProvider",
    "LinearProvider",
    "TicketProvider",
    "TicketProviderError",
]
