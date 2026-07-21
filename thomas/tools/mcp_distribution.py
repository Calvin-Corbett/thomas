"""Team MCP distribution: central admin sets, group policy, refresh, audit.

CAP-069 builds a distribution / policy layer *over* the CAP-068 MCP registry
(:mod:`thomas.tools.mcp_registry`) and the compat server-metadata store it
installs into. Where CAP-068 lets one operator search a catalog and install a
server locally, CAP-069 lets a team **admin** curate an approved set once and
have every **member** receive exactly the servers their group is permitted.

Four capabilities:

1. **Central admin distribution** -- :meth:`DistributionAdmin.distribute`
   publishes an approved set of catalog servers (a *distribution manifest*)
   for the team. Every server named must be a known catalog entry so members
   can actually install it.
2. **Group policy** -- :meth:`DistributionAdmin.set_group_policy` records a
   per-group allow/deny list. A member in a group receives only the servers
   its policy permits; a denied (or not-allow-listed) server is *withheld with
   a reason* rather than silently dropped (see :class:`WithheldServer`).
3. **Cross-surface refresh** -- :meth:`DistributionMember.refresh` propagates
   the current manifest to a member's *local* registry. It reuses
   :func:`thomas.tools.mcp_registry.install` so a distributed server lands as a
   real, launchable compat row, and it **prunes** servers this member had
   previously received that are no longer distributed or no longer permitted.
4. **Audit history** -- every distribute, policy change, and member refresh is
   appended (never rewritten) to an ordered audit log inside the manifest, so
   the full history round-trips from disk.

Persistence: the manifest is durable JSON. Its path comes from
``THOMAS_MCP_DISTRIBUTION_PATH`` when set, otherwise from the app config
(``memory.root_path`` / ``.thomas`` / ``cli`` / ``mcp_distribution.json``).
Per-member sync state (which servers this member currently manages, for
pruning) is a sibling file, overridable via
``THOMAS_MCP_DISTRIBUTION_MEMBER_PATH``.

Layering: tools tier. Imports only stdlib and the sibling
:mod:`thomas.tools.mcp_registry` (same tier). The manifest is a distribution
concern, so its tiny read/write logic mirrors the compat schema locally rather
than reaching up into the cli tier -- exactly as ``mcp_registry`` does.

Secrets: this module distributes *server references* (catalog names), never
credentials. Any per-server ``env`` secrets are resolved by the launcher at
call time from the environment; nothing here reads or logs secret values.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig
from thomas.tools.mcp_registry import (
    McpRegistryError,
    get_entry,
    install,
    registry_store_path,
)

DISTRIBUTION_PATH_ENV = "THOMAS_MCP_DISTRIBUTION_PATH"
MEMBER_STATE_PATH_ENV = "THOMAS_MCP_DISTRIBUTION_MEMBER_PATH"

# Audit action names (stable identifiers for the append-only log).
ACTION_DISTRIBUTE = "distribute"
ACTION_SET_POLICY = "set_group_policy"
ACTION_REFRESH = "refresh"


class DistributionError(Exception):
    """Raised for an unresolvable path, unknown group, or un-distributable server."""


# --- policy / result value objects -------------------------------------------
@dataclass(frozen=True)
class GroupPolicy:
    """Per-group allow/deny of distributed servers.

    ``allow`` empty means "every distributed server is allowed" (still subject
    to ``deny``). A non-empty ``allow`` restricts the group to just those
    servers. ``deny`` always wins over ``allow``.
    """

    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()

    def decide(self, server: str) -> tuple[bool, str]:
        """Return ``(permitted, reason)`` for ``server`` under this policy.

        ``reason`` is empty when permitted, otherwise a human-readable cause.
        """
        name = str(server or "").strip().lower()
        deny = {s.strip().lower() for s in self.deny}
        allow = {s.strip().lower() for s in self.allow}
        if name in deny:
            return False, "denied by group policy"
        if allow and name not in allow:
            return False, "not in group allow-list"
        return True, ""


@dataclass(frozen=True)
class WithheldServer:
    """A distributed server a group did not receive, with the reason why."""

    name: str
    reason: str


@dataclass(frozen=True)
class RefreshResult:
    """Outcome of a member :meth:`DistributionMember.refresh`."""

    group: str
    version: int
    permitted: tuple[str, ...]
    installed: tuple[str, ...]
    updated: tuple[str, ...]
    pruned: tuple[str, ...]
    withheld: tuple[WithheldServer, ...]


@dataclass(frozen=True)
class AuditEntry:
    """One append-only audit record."""

    seq: int
    at: str
    actor: str
    action: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "at": self.at,
            "actor": self.actor,
            "action": self.action,
            "detail": dict(self.detail),
        }


@dataclass
class DistributionManifest:
    """The central, durable distribution state (servers + group policy + audit)."""

    version: int = 0
    servers: list[str] = field(default_factory=list)
    groups: dict[str, GroupPolicy] = field(default_factory=dict)
    audit: list[AuditEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "servers": list(self.servers),
            "groups": {name: {"allow": list(pol.allow), "deny": list(pol.deny)} for name, pol in self.groups.items()},
            "audit": [entry.to_dict() for entry in self.audit],
            "updated_at": _utc_iso(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DistributionManifest:
        servers_raw = payload.get("servers")
        servers = [str(s) for s in servers_raw] if isinstance(servers_raw, list) else []
        groups: dict[str, GroupPolicy] = {}
        groups_raw = payload.get("groups")
        if isinstance(groups_raw, dict):
            for name, pol in groups_raw.items():
                pol = pol if isinstance(pol, dict) else {}
                allow = pol.get("allow")
                deny = pol.get("deny")
                groups[str(name)] = GroupPolicy(
                    allow=tuple(str(s) for s in allow) if isinstance(allow, list) else (),
                    deny=tuple(str(s) for s in deny) if isinstance(deny, list) else (),
                )
        audit: list[AuditEntry] = []
        audit_raw = payload.get("audit")
        if isinstance(audit_raw, list):
            for row in audit_raw:
                if not isinstance(row, dict):
                    continue
                detail = row.get("detail")
                audit.append(
                    AuditEntry(
                        seq=int(row.get("seq") or 0),
                        at=str(row.get("at") or ""),
                        actor=str(row.get("actor") or ""),
                        action=str(row.get("action") or ""),
                        detail=dict(detail) if isinstance(detail, dict) else {},
                    )
                )
        version = payload.get("version")
        return cls(
            version=int(version) if isinstance(version, int) else 0,
            servers=servers,
            groups=groups,
            audit=audit,
        )


# --- path / io helpers (mirror the compat schema locally) --------------------
def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def manifest_path(config: AppConfig | None = None) -> Path:
    """Resolve the distribution manifest path (env override wins, else config)."""
    override = os.environ.get(DISTRIBUTION_PATH_ENV)
    if override and override.strip():
        return Path(override.strip())
    if config is not None:
        return config.memory.root_path / ".thomas" / "cli" / "mcp_distribution.json"
    raise DistributionError(f"no manifest path: set {DISTRIBUTION_PATH_ENV} or pass a config")


def member_state_path(config: AppConfig | None = None) -> Path:
    """Resolve the per-member sync-state path (env override wins, else config)."""
    override = os.environ.get(MEMBER_STATE_PATH_ENV)
    if override and override.strip():
        return Path(override.strip())
    if config is not None:
        return config.memory.root_path / ".thomas" / "cli" / "mcp_distribution_member.json"
    raise DistributionError(f"no member-state path: set {MEMBER_STATE_PATH_ENV} or pass a config")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_manifest(path: Path) -> DistributionManifest:
    """Load the manifest from ``path`` (a fresh empty one if it does not exist)."""
    if not path.exists():
        return DistributionManifest()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DistributionManifest()
    if not isinstance(payload, dict):
        return DistributionManifest()
    return DistributionManifest.from_dict(payload)


def _load_registry_rows(path: Path) -> list[dict[str, Any]]:
    """Load compat server rows (same ``{"servers": [...]}`` schema as the store)."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("servers")
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _save_registry_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_json(path, {"servers": rows, "updated_at": _utc_iso()})


def _load_member_managed(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    managed = payload.get("managed")
    return [str(s) for s in managed] if isinstance(managed, list) else []


def _save_member_managed(path: Path, *, managed: list[str], version: int, group: str) -> None:
    _write_json(
        path,
        {"managed": list(managed), "version": version, "group": group, "updated_at": _utc_iso()},
    )


# --- admin side --------------------------------------------------------------
class DistributionAdmin:
    """Central admin surface: curate the distributed set and group policies.

    All mutations bump the manifest ``version`` and append an audit entry, then
    persist atomically. ``actor`` labels who made the change in the audit log.
    """

    def __init__(self, *, path: Path | None = None, config: AppConfig | None = None, actor: str = "admin") -> None:
        self._path = path if path is not None else manifest_path(config)
        self._actor = str(actor or "admin")

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> DistributionManifest:
        """Return the current manifest from disk."""
        return load_manifest(self._path)

    def _next_seq(self, manifest: DistributionManifest) -> int:
        return (max((e.seq for e in manifest.audit), default=0)) + 1

    def _commit(self, manifest: DistributionManifest, *, actor: str, action: str, detail: dict[str, Any]) -> None:
        manifest.version += 1
        manifest.audit.append(
            AuditEntry(
                seq=self._next_seq(manifest),
                at=_utc_iso(),
                actor=str(actor or self._actor),
                action=action,
                detail={**detail, "version": manifest.version},
            )
        )
        _write_json(self._path, manifest.to_dict())

    def distribute(self, servers: list[str] | tuple[str, ...], *, actor: str | None = None) -> DistributionManifest:
        """Publish the approved server set for the team.

        Every name must resolve to a known catalog entry (so members can
        actually install it); an unknown name raises :class:`DistributionError`.
        Duplicate names are collapsed; order is normalized for determinism.
        """
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in servers:
            name = str(raw or "").strip().lower()
            if not name or name in seen:
                continue
            if get_entry(name) is None:
                raise DistributionError(f"cannot distribute unknown catalog server {name!r}")
            seen.add(name)
            normalized.append(name)
        normalized.sort()
        manifest = self.load()
        manifest.servers = normalized
        self._commit(
            manifest,
            actor=actor or self._actor,
            action=ACTION_DISTRIBUTE,
            detail={"servers": list(normalized)},
        )
        return manifest

    def set_group_policy(
        self,
        group: str,
        *,
        allow: list[str] | tuple[str, ...] = (),
        deny: list[str] | tuple[str, ...] = (),
        actor: str | None = None,
    ) -> DistributionManifest:
        """Record a group's allow/deny policy (creating or replacing it)."""
        group_key = str(group or "").strip()
        if not group_key:
            raise DistributionError("group name is required")
        policy = GroupPolicy(
            allow=tuple(str(s).strip().lower() for s in allow if str(s).strip()),
            deny=tuple(str(s).strip().lower() for s in deny if str(s).strip()),
        )
        manifest = self.load()
        manifest.groups[group_key] = policy
        self._commit(
            manifest,
            actor=actor or self._actor,
            action=ACTION_SET_POLICY,
            detail={"group": group_key, "allow": list(policy.allow), "deny": list(policy.deny)},
        )
        return manifest

    def audit_history(self) -> list[AuditEntry]:
        """Return the ordered audit log (oldest first)."""
        return list(self.load().audit)


# --- policy application ------------------------------------------------------
def resolve_for_group(manifest: DistributionManifest, group: str) -> tuple[list[str], list[WithheldServer]]:
    """Split the distributed set into ``(permitted, withheld)`` for ``group``.

    Raises :class:`DistributionError` if the group has no policy -- a member
    cannot receive servers under a policy that was never defined.
    """
    group_key = str(group or "").strip()
    policy = manifest.groups.get(group_key)
    if policy is None:
        raise DistributionError(f"no policy defined for group {group_key!r}")
    permitted: list[str] = []
    withheld: list[WithheldServer] = []
    for server in sorted(manifest.servers):
        ok, reason = policy.decide(server)
        if ok:
            permitted.append(server)
        else:
            withheld.append(WithheldServer(name=server, reason=reason))
    return permitted, withheld


# --- member side -------------------------------------------------------------
class DistributionMember:
    """A team member's surface: pull the distribution into a local registry.

    ``config`` locates the member's *local* compat registry store (the same
    one CAP-068 installs into) and the member's sync-state file. ``manifest_path``
    points at the shared central manifest (defaults to the member config's own
    manifest path, which is what a single-host test uses).
    """

    def __init__(
        self,
        *,
        config: AppConfig | None = None,
        manifest_path_override: Path | None = None,
        member_state_path_override: Path | None = None,
        member_id: str = "member",
    ) -> None:
        self._config = config
        self._manifest_path = manifest_path_override if manifest_path_override is not None else manifest_path(config)
        self._member_state_path = (
            member_state_path_override if member_state_path_override is not None else member_state_path(config)
        )
        self._member_id = str(member_id or "member")

    def refresh(self, group: str, *, actor: str | None = None) -> RefreshResult:
        """Propagate the current distribution into this member's local registry.

        Installs every permitted server via the CAP-068 registry (so each lands
        as a launchable compat row), prunes any previously-received server that
        is no longer permitted or no longer distributed, records a ``refresh``
        entry in the central audit log, and persists this member's new managed
        set. Returns a :class:`RefreshResult` describing exactly what changed.
        """
        manifest = load_manifest(self._manifest_path)
        permitted, withheld = resolve_for_group(manifest, group)

        previously_managed = set(_load_member_managed(self._member_state_path))

        installed: list[str] = []
        updated: list[str] = []
        for name in permitted:
            install(name, config=self._config)
            if name in previously_managed:
                updated.append(name)
            else:
                installed.append(name)

        pruned = self._prune(sorted(previously_managed - set(permitted)))

        _save_member_managed(
            self._member_state_path,
            managed=list(permitted),
            version=manifest.version,
            group=str(group),
        )
        self._record_refresh(
            manifest,
            group=str(group),
            actor=actor or self._member_id,
            installed=installed,
            updated=updated,
            pruned=pruned,
        )
        return RefreshResult(
            group=str(group),
            version=manifest.version,
            permitted=tuple(permitted),
            installed=tuple(sorted(installed)),
            updated=tuple(sorted(updated)),
            pruned=tuple(pruned),
            withheld=tuple(withheld),
        )

    def managed_servers(self) -> list[str]:
        """Return the servers this member currently manages via distribution."""
        return _load_member_managed(self._member_state_path)

    def _prune(self, names: list[str]) -> list[str]:
        """Remove ``names`` from the member's local compat registry store.

        Returns the names that were actually removed (a name already absent
        from the store -- e.g. pruned manually -- is skipped, keeping refresh
        idempotent).
        """
        if not names:
            return []
        store = registry_store_path(self._config)
        rows = _load_registry_rows(store)
        drop = {n.strip().lower() for n in names}
        present = {str(row.get("name") or "").strip().lower() for row in rows}
        kept = [row for row in rows if str(row.get("name") or "").strip().lower() not in drop]
        if len(kept) != len(rows):
            _save_registry_rows(store, kept)
        return sorted(n for n in names if n.strip().lower() in present)

    def _record_refresh(
        self,
        manifest: DistributionManifest,
        *,
        group: str,
        actor: str,
        installed: list[str],
        updated: list[str],
        pruned: list[str],
    ) -> None:
        """Append a refresh entry to the shared audit log (append-only)."""
        current = load_manifest(self._manifest_path)
        seq = (max((e.seq for e in current.audit), default=0)) + 1
        current.audit.append(
            AuditEntry(
                seq=seq,
                at=_utc_iso(),
                actor=str(actor or self._member_id),
                action=ACTION_REFRESH,
                detail={
                    "group": group,
                    "member": self._member_id,
                    "version": manifest.version,
                    "installed": sorted(installed),
                    "updated": sorted(updated),
                    "pruned": sorted(pruned),
                },
            )
        )
        _write_json(self._manifest_path, current.to_dict())


__all__ = [
    "ACTION_DISTRIBUTE",
    "ACTION_REFRESH",
    "ACTION_SET_POLICY",
    "AuditEntry",
    "DistributionAdmin",
    "DistributionError",
    "DistributionManifest",
    "DistributionMember",
    "GroupPolicy",
    "McpRegistryError",
    "RefreshResult",
    "WithheldServer",
    "load_manifest",
    "manifest_path",
    "member_state_path",
    "resolve_for_group",
]
