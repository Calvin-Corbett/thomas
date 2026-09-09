"""Audit chain log with actor attribution, causal chains, and export (CAP-126).

The existing :mod:`thomas.server.audit_log` records *what* happened as a flat
stream of tool-decision rows.  This module answers the harder questions an audit
trail must answer: **who** did it (a human or an agent, unambiguously), **on
whose behalf** delegated agent work was performed, and **what caused it** -- the
ordered causal chain from a root human action through every agent action it set
in motion.

Three guarantees, matching the CAP-126 Level-2 acceptance line:

1. **Complete actor attribution** -- every :class:`AuditEntry` names its actor
   as a :class:`Principal` with an ``id`` and a ``kind`` (``"human"`` or
   ``"agent"``).  For delegated work an agent principal also carries
   ``on_behalf_of`` -- the id of the human who initiated the work -- so an agent
   action is never orphaned from the human ultimately accountable for it.

2. **Human-to-agent causal chains** -- an entry may reference the entry that
   caused it via ``caused_by`` (human -> agent, and agent -> agent).
   :meth:`AuditChainLog.trace_causal_chain` walks those links to the root and
   returns the ordered chain from the root human action through every agent
   action it caused.  A dangling causal reference is rejected at record time and
   guarded against at trace time; cycles are detected rather than looping.

3. **Export** -- :meth:`AuditChainLog.export` emits the log (or a filtered
   slice) as portable, stable JSONL that :meth:`AuditChainLog.import_jsonl`
   re-imports into an identical log.  Every line is canonical JSON (sorted
   keys, compact separators) so the serialised form round-trips byte-for-byte.

Everything is deterministic (the clock is injected, ids are content-derived in
recording order, no randomness at call time) and hermetic (durable JSONL file
whose path is overridable via ``THOMAS_AUDIT_CHAIN_PATH`` or
``THOMAS_RUNTIME_DIR``; no network, no live model).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STORE_ENV = "THOMAS_AUDIT_CHAIN_PATH"
_RUNTIME_DIR_ENV = "THOMAS_RUNTIME_DIR"

_ID_SEED = "thomas-cap126-audit-chain-v1"
_ENTRY_ID_HEX_LEN = 12

#: Valid actor kinds.
HUMAN = "human"
AGENT = "agent"
_ACTOR_KINDS = (HUMAN, AGENT)


class AuditChainError(Exception):
    """Raised for malformed principals, entries, stores, or broken chains."""


# ---------------------------------------------------------------------------
# Principal -- who performed an action
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """The actor behind an audited action.

    ``kind`` is ``"human"`` or ``"agent"``.  ``on_behalf_of`` is the id of the
    human who initiated delegated work; it is meaningful only for agent
    principals and must be empty for humans (a human acts on their own behalf).
    """

    id: str
    kind: str
    on_behalf_of: str = ""

    def __post_init__(self) -> None:
        if not self.id or not str(self.id).strip():
            raise AuditChainError("principal id must be a non-empty string")
        if self.kind not in _ACTOR_KINDS:
            raise AuditChainError(f"principal kind must be one of {_ACTOR_KINDS!r}, got {self.kind!r}")
        if self.kind == HUMAN and self.on_behalf_of:
            raise AuditChainError("a human principal cannot act on_behalf_of another principal")

    @property
    def is_human(self) -> bool:
        return self.kind == HUMAN

    @property
    def is_agent(self) -> bool:
        return self.kind == AGENT

    @property
    def initiating_human(self) -> str:
        """The human ultimately accountable for this actor's action.

        For a human that is the human itself; for a delegated agent it is
        ``on_behalf_of``; for a self-directed agent it is empty.
        """
        if self.is_human:
            return self.id
        return self.on_behalf_of

    @classmethod
    def human(cls, id: str) -> Principal:
        return cls(id=id, kind=HUMAN)

    @classmethod
    def agent(cls, id: str, *, on_behalf_of: str = "") -> Principal:
        return cls(id=id, kind=AGENT, on_behalf_of=on_behalf_of)

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "kind": self.kind, "on_behalf_of": self.on_behalf_of}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Principal:
        try:
            return cls(
                id=str(data["id"]),
                kind=str(data["kind"]),
                on_behalf_of=str(data.get("on_behalf_of", "")),
            )
        except (KeyError, TypeError) as exc:
            raise AuditChainError(f"invalid principal record: {data!r}") from exc


# ---------------------------------------------------------------------------
# AuditEntry -- one auditable action
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditEntry:
    """A single auditable action with complete actor attribution.

    ``caused_by`` links this entry to the entry that caused it (the causal
    parent); an empty string marks a root action (typically a human).
    ``details`` is optional structured context.
    """

    entry_id: str
    actor: Principal
    action: str
    resource: str
    timestamp: str
    caused_by: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "actor": self.actor.to_dict(),
            "action": self.action,
            "resource": self.resource,
            "timestamp": self.timestamp,
            "caused_by": self.caused_by,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AuditEntry:
        try:
            entry_id = str(data["entry_id"])
            actor = Principal.from_dict(data["actor"])
            action = str(data["action"])
            resource = str(data["resource"])
            timestamp = str(data["timestamp"])
        except (KeyError, TypeError) as exc:
            raise AuditChainError(f"invalid audit entry record: {data!r}") from exc
        caused_by = str(data.get("caused_by", ""))
        raw_details = data.get("details", {})
        if raw_details and not isinstance(raw_details, Mapping):
            raise AuditChainError(f"audit entry 'details' must be an object, got {type(raw_details)!r}")
        return cls(
            entry_id=entry_id,
            actor=actor,
            action=action,
            resource=resource,
            timestamp=timestamp,
            caused_by=caused_by,
            details=dict(raw_details),
        )

    def to_jsonl(self) -> str:
        """Canonical one-line JSON (stable key order, compact separators)."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------
# Store path resolution
# ---------------------------------------------------------------------------


def store_path(override: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the audit chain JSONL path (env-overridable for tests)."""
    if override is not None:
        return Path(override)
    env_override = os.environ.get(STORE_ENV, "").strip()
    if env_override:
        return Path(env_override)
    runtime_dir = Path(os.environ.get(_RUNTIME_DIR_ENV, "").strip() or "runtime")
    return runtime_dir / "security" / "audit_chain.jsonl"


def _derive_entry_id(seq: int, actor: Principal, action: str, resource: str, timestamp: str, caused_by: str) -> str:
    """Deterministic, content-derived id, unique by recording order (*seq*)."""
    canonical = json.dumps(
        [_ID_SEED, seq, actor.to_dict(), action, resource, timestamp, caused_by],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"ae-{seq:08d}-{digest[:_ENTRY_ID_HEX_LEN]}"


# ---------------------------------------------------------------------------
# AuditChainLog -- durable, deterministic audit trail
# ---------------------------------------------------------------------------


class AuditChainLog:
    """Durable, append-only audit trail with attribution, chains, and export.

    Entries persist as JSONL (one canonical JSON object per line) to a path that
    is overridable for tests.  An in-memory index mirrors the file for fast
    tracing and filtering; a fresh instance over the same path recovers the full
    log.  The clock is injected, so recording is fully deterministic.
    """

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], str],
    ) -> None:
        self._path = store_path(path)
        self._clock = clock
        self._entries: list[AuditEntry] = []
        self._by_id: dict[str, AuditEntry] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def __len__(self) -> int:
        return len(self._entries)

    # -- load / persist -----------------------------------------------------

    def _load(self) -> None:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("audit chain unreadable at %s: %s", self._path, exc)
            raise
        for lineno, line in enumerate(raw.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise AuditChainError(f"audit chain at {self._path} has invalid JSON on line {lineno}: {exc}") from exc
            self._index(AuditEntry.from_dict(record))

    def _index(self, entry: AuditEntry) -> None:
        if entry.entry_id in self._by_id:
            raise AuditChainError(f"duplicate audit entry id {entry.entry_id!r}")
        self._entries.append(entry)
        self._by_id[entry.entry_id] = entry

    def _append_line(self, entry: AuditEntry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(entry.to_jsonl() + "\n")

    # -- record -------------------------------------------------------------

    def record(
        self,
        *,
        actor: Principal,
        action: str,
        resource: str,
        caused_by: str = "",
        details: Mapping[str, Any] | None = None,
    ) -> AuditEntry:
        """Append an auditable action and return the persisted entry.

        The timestamp comes from the injected clock.  When *caused_by* is set it
        must reference an entry already in the log, so the causal graph never
        dangles.  The entry id is deterministic in recording order.
        """
        if not action or not str(action).strip():
            raise AuditChainError("action must be a non-empty string")
        if caused_by and caused_by not in self._by_id:
            raise AuditChainError(f"caused_by references unknown entry {caused_by!r}")
        timestamp = self._clock()
        seq = len(self._entries)
        entry_id = _derive_entry_id(seq, actor, action, resource, timestamp, caused_by)
        entry = AuditEntry(
            entry_id=entry_id,
            actor=actor,
            action=action,
            resource=resource,
            timestamp=timestamp,
            caused_by=caused_by,
            details=dict(details or {}),
        )
        self._index(entry)
        self._append_line(entry)
        return entry

    # -- lookup / filter ----------------------------------------------------

    def get(self, entry_id: str) -> AuditEntry | None:
        return self._by_id.get(entry_id)

    def all_entries(self) -> list[AuditEntry]:
        """All entries in recording order."""
        return list(self._entries)

    def filter(
        self,
        *,
        actor_id: str | None = None,
        kind: str | None = None,
        on_behalf_of: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[AuditEntry]:
        """Return entries matching every provided criterion, in record order.

        *since*/*until* are inclusive bounds compared against the ISO-8601 UTC
        timestamp string (which orders correctly lexicographically).  Omitted
        criteria are wildcards.
        """
        if kind is not None and kind not in _ACTOR_KINDS:
            raise AuditChainError(f"kind must be one of {_ACTOR_KINDS!r}, got {kind!r}")
        result: list[AuditEntry] = []
        for entry in self._entries:
            if actor_id is not None and entry.actor.id != actor_id:
                continue
            if kind is not None and entry.actor.kind != kind:
                continue
            if on_behalf_of is not None and entry.actor.on_behalf_of != on_behalf_of:
                continue
            if since is not None and entry.timestamp < since:
                continue
            if until is not None and entry.timestamp > until:
                continue
            result.append(entry)
        return result

    # -- causal chains ------------------------------------------------------

    def trace_causal_chain(self, entry_id: str) -> list[AuditEntry]:
        """Return the ordered chain from the root action to *entry_id*.

        Walks ``caused_by`` links up to the root (an entry with no causal
        parent) and returns them ordered root-first: the root human action
        followed by every agent action it caused down to *entry_id*.  Raises
        :class:`AuditChainError` for an unknown id, a dangling parent link, or a
        cycle.
        """
        start = self._by_id.get(entry_id)
        if start is None:
            raise AuditChainError(f"unknown audit entry {entry_id!r}")
        chain: list[AuditEntry] = []
        seen: set[str] = set()
        current: AuditEntry | None = start
        while current is not None:
            if current.entry_id in seen:
                raise AuditChainError(f"cycle detected in causal chain at {current.entry_id!r}")
            seen.add(current.entry_id)
            chain.append(current)
            if not current.caused_by:
                break
            parent = self._by_id.get(current.caused_by)
            if parent is None:
                raise AuditChainError(
                    f"broken causal chain: entry {current.entry_id!r} references missing parent {current.caused_by!r}"
                )
            current = parent
        chain.reverse()
        return chain

    # -- export / import ----------------------------------------------------

    def export(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        actor_id: str | None = None,
        kind: str | None = None,
        on_behalf_of: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> str:
        """Export the log (or a filtered slice) to portable, stable JSONL.

        Returns the JSONL text.  When *path* is given the text is also written
        there atomically.  Any filter argument narrows the exported slice using
        the same rules as :meth:`filter`.
        """
        if any(criterion is not None for criterion in (actor_id, kind, on_behalf_of, since, until)):
            entries = self.filter(
                actor_id=actor_id,
                kind=kind,
                on_behalf_of=on_behalf_of,
                since=since,
                until=until,
            )
        else:
            entries = self._entries
        text = "".join(entry.to_jsonl() + "\n" for entry in entries)
        if path is not None:
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(out.suffix + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, out)
        return text

    def import_jsonl(self, text: str) -> list[AuditEntry]:
        """Import entries from JSONL *text*, appending them to this log.

        Each line must be a JSON object matching :meth:`AuditEntry.to_dict`.
        Imported entries are persisted like recorded ones; ids and timestamps
        are preserved exactly, so a round-trip reproduces the log identically.
        Raises on a duplicate id or a malformed line.
        """
        imported: list[AuditEntry] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise AuditChainError(f"invalid JSONL on line {lineno}: {exc}") from exc
            entry = AuditEntry.from_dict(record)
            self._index(entry)
            self._append_line(entry)
            imported.append(entry)
        return imported

    @classmethod
    def from_jsonl(
        cls,
        text: str,
        path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], str],
    ) -> AuditChainLog:
        """Build a fresh log at *path* from exported JSONL *text*."""
        log = cls(path, clock=clock)
        log.import_jsonl(text)
        return log
