"""Agent identity, scoped policy, and signed action attestation (CAP-127).

This module gives each agent three things that, together, let the rest of the
system reason about *who* did *what* and prove it was not tampered with:

1. **Managed identity** -- :func:`mint_identity` mints a durable
   :class:`ManagedIdentity` (``agent_id``, ``display_name``, ``created_at`` and
   an HMAC signing secret).  The secret is stored server-side and is *never*
   emitted in an attestation, a public dict, a log line, or ``repr()`` -- the
   dataclass carries a redacting ``__repr__`` and a separate
   :meth:`ManagedIdentity.public_dict` that omits the secret entirely.
   Identities persist to a JSON store whose path is overridable via
   ``THOMAS_AGENT_IDENTITY_STORE_PATH`` (or ``THOMAS_RUNTIME_DIR``).

2. **Scoped policy** -- :class:`ScopedPolicy` binds an ``agent_id`` to a set of
   ``action -> {resources}`` grants.  :func:`check_policy` is *default-deny*:
   an action/resource pair is permitted only when an explicit grant (or a
   ``"*"`` wildcard) covers it.

3. **Signed action attestation** -- :func:`attest` produces an
   :class:`Attestation` that binds the agent identity to a specific action
   payload with an HMAC signature over the canonical
   ``(agent_id, action_digest, issued_at, nonce)`` tuple.
   :func:`verify_attestation` recomputes the digest and signature and returns
   ``True`` only when the attestation was signed by *that* identity's secret
   over *that exact* action payload -- any change to the action, or a different
   identity, or a forged signature made with the wrong secret, fails.

Everything is deterministic: the clock and nonce are injected, there is no
randomness at call time, and nothing touches the network.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STORE_ENV = "THOMAS_AGENT_IDENTITY_STORE_PATH"
_RUNTIME_DIR_ENV = "THOMAS_RUNTIME_DIR"
_STORE_VERSION = 1

_ID_SEED = "thomas-cap127-agent-identity-v1"
_SECRET_SEED = "thomas-cap127-agent-secret-v1"
_SIG_SEED = "thomas-cap127-attestation-v1"
_AGENT_ID_HEX_LEN = 16
_SECRET_HEX_LEN = 64

#: Sentinel string used everywhere the secret would otherwise appear.
REDACTED = "***REDACTED***"

#: Wildcard token matching any action or any resource in a scoped policy.
WILDCARD = "*"


class AgentIdentityError(Exception):
    """Raised for malformed identities, stores, or attestations."""


# ---------------------------------------------------------------------------
# Managed identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, repr=False)
class ManagedIdentity:
    """A durable, signable identity for a single agent.

    ``secret`` is the HMAC signing key.  It is redacted from ``repr()`` and
    excluded from :meth:`public_dict`; only :meth:`storage_dict` (used by the
    server-side store) carries it.
    """

    agent_id: str
    display_name: str
    created_at: str
    secret: str = field(repr=False)

    def __repr__(self) -> str:  # pragma: no cover - exercised via tests
        return (
            "ManagedIdentity("
            f"agent_id={self.agent_id!r}, "
            f"display_name={self.display_name!r}, "
            f"created_at={self.created_at!r}, "
            f"secret={REDACTED!r})"
        )

    __str__ = __repr__

    def public_dict(self) -> dict[str, str]:
        """Serialisable view WITHOUT the secret -- safe to log or attach."""
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "created_at": self.created_at,
        }

    def storage_dict(self) -> dict[str, str]:
        """Full view INCLUDING the secret -- for the server-side store only."""
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "secret": self.secret,
        }

    @classmethod
    def from_storage_dict(cls, data: Mapping[str, Any]) -> ManagedIdentity:
        try:
            agent_id = str(data["agent_id"])
            display_name = str(data["display_name"])
            created_at = str(data["created_at"])
            secret = str(data["secret"])
        except (KeyError, TypeError) as exc:
            raise AgentIdentityError(f"invalid identity record: {data!r}") from exc
        if not agent_id or not secret:
            raise AgentIdentityError("identity record missing agent_id or secret")
        return cls(
            agent_id=agent_id,
            display_name=display_name,
            created_at=created_at,
            secret=secret,
        )


def _derive_agent_id(nonce: str, display_name: str) -> str:
    digest = hashlib.sha256(f"{_ID_SEED}:{nonce}:{display_name}".encode()).hexdigest()
    return f"agent-{digest[:_AGENT_ID_HEX_LEN]}"


def _derive_secret(nonce: str, agent_id: str) -> str:
    digest = hashlib.sha256(f"{_SECRET_SEED}:{nonce}:{agent_id}".encode()).hexdigest()
    return digest[:_SECRET_HEX_LEN]


def mint_identity(
    display_name: str,
    *,
    nonce: str,
    clock: Callable[[], str],
    agent_id: str | None = None,
) -> ManagedIdentity:
    """Mint a fresh managed identity (deterministic in *nonce* and *clock*).

    *nonce* seeds both the ``agent_id`` (unless one is supplied) and the signing
    secret.  *clock* is an injected callable returning the ``created_at``
    timestamp string.  No randomness, no network.
    """
    if not display_name or not display_name.strip():
        raise AgentIdentityError("display_name must be a non-empty string")
    if not nonce:
        raise AgentIdentityError("nonce must be a non-empty string")
    resolved_id = agent_id if agent_id else _derive_agent_id(nonce, display_name)
    secret = _derive_secret(nonce, resolved_id)
    return ManagedIdentity(
        agent_id=resolved_id,
        display_name=display_name,
        created_at=clock(),
        secret=secret,
    )


# ---------------------------------------------------------------------------
# Persistent identity store
# ---------------------------------------------------------------------------


def store_path(override: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the identity store path (env-overridable for tests)."""
    if override is not None:
        return Path(override)
    env_override = os.environ.get(STORE_ENV, "").strip()
    if env_override:
        return Path(env_override)
    runtime_dir = Path(os.environ.get(_RUNTIME_DIR_ENV, "").strip() or "runtime")
    return runtime_dir / "security" / "agent_identities.json"


class IdentityStore:
    """JSON-backed, server-side store of managed identities and their policies.

    The secret lives here and nowhere public.  The store also holds the scoped
    policy attached to each identity.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._path = store_path(path)

    @property
    def path(self) -> Path:
        return self._path

    # -- load / save --------------------------------------------------------

    def _read_raw(self) -> dict[str, Any]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"version": _STORE_VERSION, "identities": {}, "policies": {}}
        except OSError as exc:
            logger.warning("identity store unreadable at %s: %s", self._path, exc)
            raise
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AgentIdentityError(f"identity store at {self._path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise AgentIdentityError(f"identity store at {self._path} is malformed")
        data.setdefault("identities", {})
        data.setdefault("policies", {})
        return data

    def _write_raw(self, data: Mapping[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, self._path)

    # -- identities ---------------------------------------------------------

    def save(self, identity: ManagedIdentity) -> ManagedIdentity:
        """Persist *identity* (idempotent by ``agent_id``)."""
        data = self._read_raw()
        identities = data["identities"]
        if not isinstance(identities, dict):
            raise AgentIdentityError("identity store 'identities' is malformed")
        identities[identity.agent_id] = identity.storage_dict()
        self._write_raw(data)
        return identity

    def get(self, agent_id: str) -> ManagedIdentity | None:
        """Load a single identity by id, or ``None`` if absent."""
        data = self._read_raw()
        record = data["identities"].get(agent_id)
        if record is None:
            return None
        return ManagedIdentity.from_storage_dict(record)

    def list_ids(self) -> list[str]:
        """Return all known agent ids, sorted."""
        data = self._read_raw()
        return sorted(data["identities"].keys())

    def mint(
        self,
        display_name: str,
        *,
        nonce: str,
        clock: Callable[[], str],
        agent_id: str | None = None,
    ) -> ManagedIdentity:
        """Mint an identity and persist it in one step."""
        identity = mint_identity(display_name, nonce=nonce, clock=clock, agent_id=agent_id)
        return self.save(identity)

    # -- policies -----------------------------------------------------------

    def attach_policy(self, policy: ScopedPolicy) -> ScopedPolicy:
        """Persist *policy*, replacing any prior policy for its agent."""
        data = self._read_raw()
        policies = data["policies"]
        if not isinstance(policies, dict):
            raise AgentIdentityError("identity store 'policies' is malformed")
        policies[policy.agent_id] = policy.to_dict()
        self._write_raw(data)
        return policy

    def get_policy(self, agent_id: str) -> ScopedPolicy | None:
        """Load the scoped policy for *agent_id*, or ``None`` if none set."""
        data = self._read_raw()
        record = data["policies"].get(agent_id)
        if record is None:
            return None
        return ScopedPolicy.from_dict(record)


# ---------------------------------------------------------------------------
# Scoped policy (default-deny)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyDecision:
    """The outcome of a :func:`check_policy` evaluation."""

    allowed: bool
    agent_id: str
    action: str
    resource: str
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


@dataclass(frozen=True)
class ScopedPolicy:
    """Binds an ``agent_id`` to ``action -> {allowed resources}`` grants.

    A resource set containing :data:`WILDCARD` grants any resource for that
    action; an action key of :data:`WILDCARD` grants (its resources) for any
    action.  Absence of a matching grant means *deny*.
    """

    agent_id: str
    grants: Mapping[str, frozenset[str]]

    @classmethod
    def create(cls, agent_id: str, grants: Mapping[str, set[str] | frozenset[str] | list[str]]) -> ScopedPolicy:
        """Build a policy, normalising each resource collection to a frozenset."""
        if not agent_id:
            raise AgentIdentityError("policy requires a non-empty agent_id")
        normalised = {str(action): frozenset(str(r) for r in resources) for action, resources in grants.items()}
        return cls(agent_id=agent_id, grants=normalised)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "grants": {action: sorted(res) for action, res in self.grants.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScopedPolicy:
        try:
            agent_id = str(data["agent_id"])
            raw_grants = data["grants"]
        except (KeyError, TypeError) as exc:
            raise AgentIdentityError(f"invalid policy record: {data!r}") from exc
        if not isinstance(raw_grants, dict):
            raise AgentIdentityError("policy 'grants' must be an object")
        return cls.create(agent_id, raw_grants)


def _resource_allowed(resources: frozenset[str], resource: str) -> bool:
    return WILDCARD in resources or resource in resources


def check_policy(
    policy: ScopedPolicy,
    identity: ManagedIdentity,
    action: str,
    resource: str,
) -> PolicyDecision:
    """Default-deny check of *action*/*resource* for *identity* under *policy*.

    Denies (never raises) when the policy belongs to a different agent, when no
    grant covers the action, or when the action's grant does not cover the
    resource.  Only an explicit (or wildcard) grant yields ``allowed=True``.
    """

    def deny(reason: str) -> PolicyDecision:
        return PolicyDecision(
            allowed=False,
            agent_id=identity.agent_id,
            action=action,
            resource=resource,
            reason=reason,
        )

    if policy.agent_id != identity.agent_id:
        return deny(f"policy for {policy.agent_id!r} does not apply to {identity.agent_id!r}")

    matched: frozenset[str] | None = policy.grants.get(action)
    if matched is not None and _resource_allowed(matched, resource):
        return PolicyDecision(
            allowed=True,
            agent_id=identity.agent_id,
            action=action,
            resource=resource,
            reason="explicit grant",
        )

    wildcard_action = policy.grants.get(WILDCARD)
    if wildcard_action is not None and _resource_allowed(wildcard_action, resource):
        return PolicyDecision(
            allowed=True,
            agent_id=identity.agent_id,
            action=action,
            resource=resource,
            reason="wildcard-action grant",
        )

    return deny("default-deny: no grant covers this action/resource")


# ---------------------------------------------------------------------------
# Signed action attestation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Attestation:
    """A signed, tamper-evident record that *agent_id* performed an action.

    Carries only the digest of the action payload plus a signature -- never the
    identity's secret and never the raw payload.
    """

    agent_id: str
    action_digest: str
    issued_at: str
    nonce: str
    signature: str

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_id": self.agent_id,
            "action_digest": self.action_digest,
            "issued_at": self.issued_at,
            "nonce": self.nonce,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Attestation:
        try:
            return cls(
                agent_id=str(data["agent_id"]),
                action_digest=str(data["action_digest"]),
                issued_at=str(data["issued_at"]),
                nonce=str(data["nonce"]),
                signature=str(data["signature"]),
            )
        except (KeyError, TypeError) as exc:
            raise AgentIdentityError(f"invalid attestation record: {data!r}") from exc


def canonical_action_payload(action_record: Mapping[str, Any]) -> str:
    """Deterministic, canonical JSON for an action record (stable key order)."""
    return json.dumps(action_record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _action_digest(action_record: Mapping[str, Any]) -> str:
    canonical = canonical_action_payload(action_record)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _signing_message(agent_id: str, action_digest: str, issued_at: str, nonce: str) -> bytes:
    # Canonical, unambiguous concatenation; length-prefixing via JSON list keeps
    # the fields from bleeding into one another.
    parts = [_SIG_SEED, agent_id, action_digest, issued_at, nonce]
    return json.dumps(parts, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sign(secret: str, agent_id: str, action_digest: str, issued_at: str, nonce: str) -> str:
    message = _signing_message(agent_id, action_digest, issued_at, nonce)
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def attest(
    identity: ManagedIdentity,
    action_record: Mapping[str, Any],
    *,
    clock: Callable[[], str],
    nonce: str,
) -> Attestation:
    """Produce a signed attestation binding *identity* to *action_record*.

    The signature is an HMAC-SHA256 over the canonical
    ``(agent_id, action_digest, issued_at, nonce)`` tuple keyed by the
    identity's secret.  The returned attestation contains no secret and no raw
    payload -- only the digest.  Deterministic in *clock* and *nonce*.
    """
    if not nonce:
        raise AgentIdentityError("attestation nonce must be a non-empty string")
    digest = _action_digest(action_record)
    issued_at = clock()
    signature = _sign(identity.secret, identity.agent_id, digest, issued_at, nonce)
    return Attestation(
        agent_id=identity.agent_id,
        action_digest=digest,
        issued_at=issued_at,
        nonce=nonce,
        signature=signature,
    )


def verify_attestation(
    attestation: Attestation,
    action_record: Mapping[str, Any],
    identity: ManagedIdentity,
) -> bool:
    """Return ``True`` iff *attestation* was signed by *identity* over exactly
    *action_record*.

    Fails (returns ``False``, never raises for a mismatch) when:

    * the attestation names a different agent than *identity*;
    * *action_record* was altered (its recomputed digest no longer matches);
    * the signature was forged with the wrong secret or any signed field was
      tampered with.

    The signature comparison is constant-time (:func:`hmac.compare_digest`).
    """
    if attestation.agent_id != identity.agent_id:
        return False

    expected_digest = _action_digest(action_record)
    if not hmac.compare_digest(attestation.action_digest, expected_digest):
        return False

    expected_signature = _sign(
        identity.secret,
        identity.agent_id,
        attestation.action_digest,
        attestation.issued_at,
        attestation.nonce,
    )
    return hmac.compare_digest(attestation.signature, expected_signature)
