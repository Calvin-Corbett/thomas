"""Honest Work connector catalog backed by installed Thomas integrations."""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from typing import Any

from .validation import WorkValidationError


@dataclass(frozen=True)
class WorkConnector:
    id: str
    name: str
    integration_module: str
    identity_hint: str
    scopes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["scopes"] = list(self.scopes)
        payload["installed"] = importlib.util.find_spec(self.integration_module) is not None
        return payload


CONNECTORS: tuple[WorkConnector, ...] = (
    WorkConnector("gmail", "Gmail", "thomas.integrations.google_workspace", "name@example.com", ("read", "send")),
    WorkConnector(
        "google_drive", "Google Drive", "thomas.integrations.google_workspace", "name@example.com", ("read", "write")
    ),
    WorkConnector(
        "google_calendar",
        "Google Calendar",
        "thomas.integrations.google_workspace",
        "name@example.com",
        ("read", "write"),
    ),
)

_SCOPE_ALIASES: dict[str, dict[str, frozenset[str]]] = {
    "gmail": {
        "read": frozenset({"read", "readonly", "read_only", "mail.read", "gmail.read"}),
        "send": frozenset({"send", "mail.send", "gmail.send", "mail.write"}),
    },
    "google_drive": {
        "read": frozenset({"read", "readonly", "read_only", "drive.read", "drive.readonly"}),
        "write": frozenset({"write", "drive.write"}),
    },
    "google_calendar": {
        "read": frozenset({"read", "readonly", "read_only", "calendar.read"}),
        "write": frozenset({"write", "calendar.write", "calendar.events.write"}),
    },
}


def canonical_connector_scopes(provider: Any, requested: Any) -> list[str]:
    """Return provider-owned canonical scopes; reject cross-provider assertions."""

    provider_id = str(provider or "").strip().lower()
    aliases = _SCOPE_ALIASES.get(provider_id)
    if aliases is None:
        raise WorkValidationError("connector provider is not installed")
    values = requested if isinstance(requested, list) else []
    values = values or ["read"]
    canonical: list[str] = []
    for raw in values:
        normalized = str(raw or "").strip().lower().replace("-", "_")
        match = next((scope for scope, accepted in aliases.items() if normalized in accepted), None)
        if match is None:
            raise WorkValidationError(f"scope is not valid for the {provider_id} connector")
        if match not in canonical:
            canonical.append(match)
    return canonical


def list_work_connectors() -> list[dict[str, object]]:
    return [connector.to_dict() for connector in CONNECTORS if importlib.util.find_spec(connector.integration_module)]


def installed_connector_ids() -> frozenset[str]:
    """Return provider ids whose Thomas integration is available locally."""

    return frozenset(str(row["id"]) for row in list_work_connectors())


__all__ = [
    "CONNECTORS",
    "WorkConnector",
    "canonical_connector_scopes",
    "installed_connector_ids",
    "list_work_connectors",
]
