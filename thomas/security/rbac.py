"""Custom scoped RBAC enforced identically for humans and agents (CAP-125).

This module provides a small, deterministic role-based access-control engine
built around three ideas the acceptance line demands:

1. **Custom scoped roles.** A role is a named set of *permissions*.  Each
   permission is scoped: it names a ``resource`` and an ``action`` and may
   carry an optional ``scope`` constraint (a path / glob such as
   ``"repo/thomas/**"``).  Roles are defined at runtime — nothing is
   hard-coded — so callers compose whatever custom roles they need.

2. **Principals that may be human OR agent.** A :class:`Principal` carries a
   ``kind`` (:data:`HUMAN` or :data:`AGENT`) and an ``id``.  Roles are assigned
   to principals of either kind.

3. **Identical enforcement.** :meth:`RBACEngine.check_access` evaluates purely
   from the *roles a principal holds* — ``principal.kind`` is deliberately
   never read during evaluation.  A human and an agent that hold the same role
   therefore receive byte-for-byte identical :class:`AccessDecision` results;
   holding different roles yields different decisions.

Semantics:

- **Role composition** — a principal may hold multiple roles; the effective
  permission set is their union.
- **Explicit deny overrides allow** — a matching ``deny`` permission always
  wins over any matching ``allow``, regardless of role order.
- **Default-deny** — if no held permission matches, access is denied with a
  reason naming the miss.
- **Scope constraints** — a permission with a ``scope`` only matches requests
  whose scope is covered by it (glob / prefix); out-of-scope requests fall
  through to default-deny.

Everything is deterministic: roles are evaluated in a stable (sorted) order and
there is no randomness or wall-clock dependence in a decision.  Role and
assignment definitions persist durably as JSON; the store path is overridable
via the ``THOMAS_RBAC_STORE_PATH`` environment variable.
"""

from __future__ import annotations

import fnmatch
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "HUMAN",
    "AGENT",
    "ALLOW",
    "DENY",
    "STORE_ENV",
    "Principal",
    "Permission",
    "Role",
    "AccessDecision",
    "RBACEngine",
    "RBACError",
]

#: Principal kinds.  Present for readability only — evaluation never branches
#: on them (that is the whole point of "identical enforcement").
HUMAN = "human"
AGENT = "agent"

#: Permission effects.
ALLOW = "allow"
DENY = "deny"

#: Environment variable overriding the durable JSON store path.
STORE_ENV = "THOMAS_RBAC_STORE_PATH"
_RUNTIME_DIR_ENV = "THOMAS_RUNTIME_DIR"
_STORE_VERSION = 1


class RBACError(ValueError):
    """Raised for malformed roles, principals, or store payloads."""


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise RBACError(f"{what} must be a non-empty string, got {value!r}")
    return value


@dataclass(frozen=True, order=True)
class Principal:
    """An actor that can hold roles — either a human or an agent.

    ``kind`` distinguishes the two for assignment and audit, but is never
    consulted when a decision is made.
    """

    kind: str
    id: str

    def __post_init__(self) -> None:
        _require_str(self.kind, "Principal.kind")
        _require_str(self.id, "Principal.id")

    @property
    def key(self) -> str:
        """Stable string key used for assignment storage."""
        return f"{self.kind}:{self.id}"

    @classmethod
    def human(cls, id: str) -> Principal:
        return cls(HUMAN, id)

    @classmethod
    def agent(cls, id: str) -> Principal:
        return cls(AGENT, id)


@dataclass(frozen=True)
class Permission:
    """A single scoped grant or denial within a role.

    - ``resource`` / ``action`` support an exact match or the ``"*"`` wildcard.
    - ``scope`` is an optional path/glob constraint (e.g. ``"repo/**"``).
      ``None`` means the permission is not scope-restricted and applies to any
      request scope.
    - ``effect`` is :data:`ALLOW` or :data:`DENY`.
    """

    resource: str
    action: str
    scope: str | None = None
    effect: str = ALLOW

    def __post_init__(self) -> None:
        _require_str(self.resource, "Permission.resource")
        _require_str(self.action, "Permission.action")
        if self.scope is not None:
            _require_str(self.scope, "Permission.scope")
        if self.effect not in (ALLOW, DENY):
            raise RBACError(f"Permission.effect must be {ALLOW!r} or {DENY!r}, got {self.effect!r}")

    def matches(self, resource: str, action: str, scope: str | None) -> bool:
        """Return True if this permission applies to the given request."""
        if not _token_matches(self.resource, resource):
            return False
        if not _token_matches(self.action, action):
            return False
        return _scope_matches(self.scope, scope)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "action": self.action,
            "scope": self.scope,
            "effect": self.effect,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Permission:
        if not isinstance(data, dict):
            raise RBACError(f"permission entry must be a mapping, got {data!r}")
        return cls(
            resource=data.get("resource", ""),
            action=data.get("action", ""),
            scope=data.get("scope"),
            effect=data.get("effect", ALLOW),
        )


@dataclass(frozen=True)
class Role:
    """A named, custom set of scoped permissions."""

    name: str
    permissions: tuple[Permission, ...] = ()

    def __post_init__(self) -> None:
        _require_str(self.name, "Role.name")
        if not all(isinstance(p, Permission) for p in self.permissions):
            raise RBACError("Role.permissions must all be Permission instances")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "permissions": [p.to_dict() for p in self.permissions]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Role:
        if not isinstance(data, dict):
            raise RBACError(f"role entry must be a mapping, got {data!r}")
        perms = data.get("permissions", [])
        if not isinstance(perms, list):
            raise RBACError("role permissions must be a list")
        return cls(
            name=_require_str(data.get("name"), "Role.name"),
            permissions=tuple(Permission.from_dict(p) for p in perms),
        )


@dataclass(frozen=True)
class AccessDecision:
    """Result of an access check.

    ``matched_role`` names the role whose permission decided the outcome
    (``None`` on default-deny).  Two principals whose held roles are identical
    always produce equal :class:`AccessDecision` values.
    """

    allowed: bool
    matched_role: str | None
    reason: str
    effect: str | None = None


def _token_matches(pattern: str, value: str) -> bool:
    """Exact match, or ``"*"`` wildcard, for resource/action tokens."""
    if pattern == "*":
        return True
    return pattern == value


def _scope_matches(constraint: str | None, requested: str | None) -> bool:
    """Return True if ``requested`` scope is covered by ``constraint``.

    - A permission with no constraint (``None``) applies to any request.
    - A constrained permission requires a request scope and matches it as a
      glob (``fnmatch``), so ``"repo/**"`` covers ``"repo/a/b"`` and ``"*"``
      covers everything.
    """
    if constraint is None:
        return True
    if requested is None:
        return False
    if constraint == requested:
        return True
    # Support both shell-glob "**" (recursive) and single "*" semantics.
    normalized = constraint.replace("**", "*")
    return fnmatch.fnmatchcase(requested, normalized)


class RBACEngine:
    """In-memory engine for custom scoped roles with durable JSON persistence.

    The engine holds a registry of roles and a map of principal -> role names.
    :meth:`check_access` is the single enforcement path used for every
    principal, human or agent alike.
    """

    def __init__(
        self,
        store_path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._roles: dict[str, Role] = {}
        # principal key -> ordered-unique tuple of role names
        self._assignments: dict[str, tuple[str, ...]] = {}
        self._store_path = Path(store_path) if store_path is not None else _default_store_path()
        # Injected clock keeps persistence metadata deterministic in tests.
        self._clock = clock if clock is not None else (lambda: 0.0)

    # -- role & assignment management -------------------------------------

    def define_role(self, name: str, permissions: Iterable[Permission]) -> Role:
        """Create or replace a custom role and return it."""
        role = Role(name=_require_str(name, "role name"), permissions=tuple(permissions))
        self._roles[role.name] = role
        return role

    def get_role(self, name: str) -> Role | None:
        return self._roles.get(name)

    def roles(self) -> tuple[Role, ...]:
        return tuple(self._roles[n] for n in sorted(self._roles))

    def assign_role(self, principal: Principal, role_name: str) -> None:
        """Grant ``role_name`` to ``principal`` (idempotent, order-preserving)."""
        if not isinstance(principal, Principal):
            raise RBACError(f"principal must be a Principal, got {principal!r}")
        if role_name not in self._roles:
            raise RBACError(f"unknown role {role_name!r}; define it first")
        current = self._assignments.get(principal.key, ())
        if role_name not in current:
            self._assignments[principal.key] = current + (role_name,)

    def revoke_role(self, principal: Principal, role_name: str) -> None:
        current = self._assignments.get(principal.key, ())
        remaining = tuple(r for r in current if r != role_name)
        if remaining:
            self._assignments[principal.key] = remaining
        else:
            self._assignments.pop(principal.key, None)

    def roles_for(self, principal: Principal) -> tuple[str, ...]:
        """Return the role names held by ``principal`` (evaluation order)."""
        return self._assignments.get(principal.key, ())

    # -- enforcement -------------------------------------------------------

    def check_access(
        self,
        principal: Principal,
        resource: str,
        action: str,
        scope: str | None = None,
    ) -> AccessDecision:
        """Decide whether ``principal`` may perform ``action`` on ``resource``.

        The evaluation reads only the roles the principal holds and their
        permissions — never ``principal.kind`` — so it is identical for humans
        and agents.  Explicit deny overrides allow; absent any match the
        default is deny.
        """
        held = self.roles_for(principal)
        if not held:
            return AccessDecision(
                allowed=False,
                matched_role=None,
                reason=f"default-deny: principal {principal.key!r} holds no roles",
            )

        # Deny wins over allow regardless of role order, so scan for a matching
        # deny across ALL held roles first, in a stable (sorted) order.
        first_allow: tuple[str, Permission] | None = None
        for role_name in sorted(held):
            role = self._roles.get(role_name)
            if role is None:
                continue
            for perm in role.permissions:
                if not perm.matches(resource, action, scope):
                    continue
                if perm.effect == DENY:
                    return AccessDecision(
                        allowed=False,
                        matched_role=role_name,
                        reason=(
                            f"explicit deny on {resource!r}/{action!r}{_scope_suffix(scope)} via role {role_name!r}"
                        ),
                        effect=DENY,
                    )
                if first_allow is None:
                    first_allow = (role_name, perm)

        if first_allow is not None:
            role_name, _perm = first_allow
            return AccessDecision(
                allowed=True,
                matched_role=role_name,
                reason=(f"allow on {resource!r}/{action!r}{_scope_suffix(scope)} via role {role_name!r}"),
                effect=ALLOW,
            )

        return AccessDecision(
            allowed=False,
            matched_role=None,
            reason=(f"default-deny: no held role grants {resource!r}/{action!r}{_scope_suffix(scope)}"),
        )

    # -- persistence -------------------------------------------------------

    @property
    def store_path(self) -> Path:
        return self._store_path

    def to_dict(self) -> dict[str, Any]:
        """Serialise roles + assignments to a JSON-ready mapping."""
        return {
            "version": _STORE_VERSION,
            "generated_at": self._clock(),
            "roles": [self._roles[n].to_dict() for n in sorted(self._roles)],
            "assignments": {key: list(self._assignments[key]) for key in sorted(self._assignments)},
        }

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        """Persist definitions durably as JSON; returns the written path."""
        target = Path(path) if path is not None else self._store_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)
        return target

    def load(self, path: str | os.PathLike[str] | None = None) -> None:
        """Replace in-memory state from a JSON store (round-trips ``save``)."""
        source = Path(path) if path is not None else self._store_path
        raw = source.read_text(encoding="utf-8")
        self.load_dict(json.loads(raw))

    def load_dict(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise RBACError(f"store payload must be a mapping, got {data!r}")
        roles_data = data.get("roles", [])
        if not isinstance(roles_data, list):
            raise RBACError("store 'roles' must be a list")
        assignments_data = data.get("assignments", {})
        if not isinstance(assignments_data, dict):
            raise RBACError("store 'assignments' must be a mapping")

        roles: dict[str, Role] = {}
        for entry in roles_data:
            role = Role.from_dict(entry)
            roles[role.name] = role

        assignments: dict[str, tuple[str, ...]] = {}
        for key, names in assignments_data.items():
            if not isinstance(names, list):
                raise RBACError(f"assignment for {key!r} must be a list")
            deduped: list[str] = []
            for name in names:
                name = _require_str(name, "assignment role name")
                if name not in roles:
                    raise RBACError(f"assignment references unknown role {name!r}")
                if name not in deduped:
                    deduped.append(name)
            assignments[_require_str(key, "assignment principal key")] = tuple(deduped)

        self._roles = roles
        self._assignments = assignments

    @classmethod
    def from_store(
        cls,
        path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> RBACEngine:
        """Construct an engine and load its store if the file exists."""
        engine = cls(store_path=path, clock=clock)
        if engine._store_path.exists():
            engine.load()
        return engine

    def copy(self) -> RBACEngine:
        """Return an independent deep-ish copy (roles/permissions are frozen)."""
        clone = RBACEngine(store_path=self._store_path, clock=self._clock)
        clone._roles = dict(self._roles)
        clone._assignments = dict(self._assignments)
        return clone


def _scope_suffix(scope: str | None) -> str:
    return f" scope={scope!r}" if scope is not None else ""


def _default_store_path() -> Path:
    env = os.environ.get(STORE_ENV)
    if env:
        return Path(env)
    runtime = os.environ.get(_RUNTIME_DIR_ENV)
    base = Path(runtime) if runtime else Path.home() / ".thomas"
    return base / "security" / "rbac_store.json"
