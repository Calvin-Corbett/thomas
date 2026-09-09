"""SCIM 2.0 user/group provisioning with directory sync (CAP-124).

Thomas has historically had *no* user model — identity at the edge is just an
``X-User-Id`` header.  This module adds the missing piece an IdP (Okta / Microsoft
Entra ID) needs in order to *provision* users and groups into Thomas: a subset of
the SCIM 2.0 protocol (RFC 7643 schema, RFC 7644 operations).

What it provides
================

1. **A directory store** (:class:`DirectoryStore`) of Users and Groups shaped like
   SCIM resources — ``id``, ``userName``, ``active``, ``emails`` and ``groups`` for
   users; ``displayName`` and ``members`` for groups.  The store persists durably
   as JSON and its path is overridable via ``THOMAS_SCIM_STORE_PATH``.

2. **The core SCIM operations** (:class:`ScimProvider`) — ``create`` / ``get`` /
   ``list`` (with a ``filter`` expression) / ``replace`` (PUT) / ``patch``
   (PATCH ``Operations`` with ``add`` / ``remove`` / ``replace``) / ``delete`` for
   both users and groups.  The PATCH engine speaks the *Okta / Entra dialect*:
   case-insensitive ``op`` names, path-less ``replace`` whose value is an attribute
   map (Entra), value-filter paths such as ``members[value eq "id"]`` and
   ``emails[type eq "work"]`` (Okta), and multi-valued ``add`` that appends.

3. **Directory sync** (:meth:`ScimProvider.sync_directory`) — applying a provider
   push (the IdP's desired membership) reconciles the local directory: new
   principals are *created*, changed ones are *updated*, and principals the IdP no
   longer sends are *de-provisioned*.  De-provisioning a user sets ``active=false``
   (a soft deactivate — never a hard delete), which is exactly how Okta / Entra
   expect SCIM de-provisioning to behave.

Everything is deterministic: IDs come from an injected factory, timestamps from an
injected clock, and iteration order is stable (sorted).  There is no network, no
randomness, and no wall-clock dependence in any result — so the whole protocol is
exercisable offline with a hermetic fake IdP push.

The *live lane* — receiving these operations over HTTP from a real Okta/Entra SCIM
connector at ``/scim/v2/Users`` etc., behind the server's ``_require_api_access``
bearer-token choke point — is a thin transport wrapper over this core and is gated
on a real IdP + provisioning token; it is intentionally out of scope here and not
claimed to have run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "USER_SCHEMA",
    "GROUP_SCHEMA",
    "PATCH_OP_SCHEMA",
    "LIST_RESPONSE_SCHEMA",
    "ERROR_SCHEMA",
    "STORE_ENV",
    "ScimError",
    "DirectoryStore",
    "ScimProvider",
    "SyncResult",
]

#: SCIM 2.0 URNs (RFC 7643 / 7644).
USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
LIST_RESPONSE_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"

#: Environment variable overriding the durable JSON store path.
STORE_ENV = "THOMAS_SCIM_STORE_PATH"
_RUNTIME_DIR_ENV = "THOMAS_RUNTIME_DIR"
_STORE_VERSION = 1

#: Resource types and the attribute that is their "natural key" for sync.
_USER = "User"
_GROUP = "Group"

#: Multi-valued user/group attributes whose PATCH semantics append rather than set.
_MULTI_VALUED = frozenset({"emails", "groups", "members", "phoneNumbers"})


class ScimError(Exception):
    """A SCIM protocol error carrying an HTTP status and optional ``scimType``.

    Serialises to the RFC 7644 error envelope so a transport layer can return it
    verbatim.
    """

    def __init__(self, detail: str, *, status: int = 400, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.scim_type = scim_type

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schemas": [ERROR_SCHEMA],
            "detail": self.detail,
            "status": str(self.status),
        }
        if self.scim_type is not None:
            payload["scimType"] = self.scim_type
        return payload


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _require_mapping(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScimError(f"{what} must be an object, got {type(value).__name__}", scim_type="invalidValue")
    return value


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ScimError(f"{what} must be a non-empty string", scim_type="invalidValue")
    return value


def _canonical(resource: dict[str, Any]) -> str:
    """Stable JSON of a resource *excluding* ``meta`` (used for etag + diffing)."""
    body = {k: v for k, v in resource.items() if k != "meta"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _etag(resource: dict[str, Any]) -> str:
    digest = hashlib.sha1(_canonical(resource).encode("utf-8")).hexdigest()  # noqa: S324 (etag, not security)
    return f'W/"{digest[:16]}"'


# --------------------------------------------------------------------------- #
# Filter parsing (RFC 7644 §3.4.2.2 — supported subset)
# --------------------------------------------------------------------------- #

_FILTER_RE = re.compile(
    r"^\s*(?P<attr>[\w.:]+)\s+(?P<op>eq|ne|co|sw|ew|pr)\b\s*(?P<val>.*?)\s*$",
    re.IGNORECASE,
)


def _parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return None
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1]
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        return raw


def _attr_value(resource: dict[str, Any], attr: str) -> Any:
    """Resolve a (possibly dotted) attribute path against a resource."""
    cur: Any = resource
    for part in attr.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _matches_filter(resource: dict[str, Any], expr: str) -> bool:
    m = _FILTER_RE.match(expr)
    if not m:
        raise ScimError(f"unsupported filter: {expr!r}", scim_type="invalidFilter")
    attr = m.group("attr")
    op = m.group("op").lower()
    actual = _attr_value(resource, attr)
    if op == "pr":
        return actual not in (None, "", [], {})
    expected = _parse_scalar(m.group("val"))
    if op == "eq":
        return _eq(actual, expected)
    if op == "ne":
        return not _eq(actual, expected)
    a = "" if actual is None else str(actual)
    e = "" if expected is None else str(expected)
    if op == "co":
        return e.lower() in a.lower()
    if op == "sw":
        return a.lower().startswith(e.lower())
    if op == "ew":
        return a.lower().endswith(e.lower())
    raise ScimError(f"unsupported filter operator: {op!r}", scim_type="invalidFilter")


def _eq(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual == expected
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.casefold() == expected.casefold()
    return actual == expected


# --------------------------------------------------------------------------- #
# PATCH path parsing (Okta / Entra dialect)
# --------------------------------------------------------------------------- #

_PATH_RE = re.compile(
    r"^(?P<attr>[\w]+)"
    r"(?:\[(?P<filter>[^\]]+)\])?"
    r"(?:\.(?P<sub>[\w]+))?$"
)


@dataclass(frozen=True)
class _PatchPath:
    attr: str
    filter: str | None
    sub: str | None


def _parse_patch_path(path: str) -> _PatchPath:
    m = _PATH_RE.match(path.strip())
    if not m:
        # dotted top-level path such as "name.givenName"
        if "." in path and "[" not in path:
            head, _, tail = path.partition(".")
            return _PatchPath(attr=head, filter=None, sub=tail)
        raise ScimError(f"unsupported patch path: {path!r}", scim_type="invalidPath")
    return _PatchPath(attr=m.group("attr"), filter=m.group("filter"), sub=m.group("sub"))


# --------------------------------------------------------------------------- #
# Directory store
# --------------------------------------------------------------------------- #


class DirectoryStore:
    """Durable JSON store of SCIM Users and Groups, keyed by ``id``."""

    def __init__(self, store_path: str | os.PathLike[str] | None = None) -> None:
        self._users: dict[str, dict[str, Any]] = {}
        self._groups: dict[str, dict[str, Any]] = {}
        self._store_path = Path(store_path) if store_path is not None else _default_store_path()

    @property
    def store_path(self) -> Path:
        return self._store_path

    def _bucket(self, resource_type: str) -> dict[str, dict[str, Any]]:
        if resource_type == _USER:
            return self._users
        if resource_type == _GROUP:
            return self._groups
        raise ScimError(f"unknown resource type {resource_type!r}", scim_type="invalidValue")

    def put(self, resource_type: str, resource: dict[str, Any]) -> None:
        self._bucket(resource_type)[resource["id"]] = resource

    def get(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        return self._bucket(resource_type).get(resource_id)

    def delete(self, resource_type: str, resource_id: str) -> bool:
        return self._bucket(resource_type).pop(resource_id, None) is not None

    def all(self, resource_type: str) -> list[dict[str, Any]]:
        return [self._bucket(resource_type)[k] for k in sorted(self._bucket(resource_type))]

    # -- persistence ------------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": _STORE_VERSION,
            "users": [self._users[k] for k in sorted(self._users)],
            "groups": [self._groups[k] for k in sorted(self._groups)],
        }

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        target = Path(path) if path is not None else self._store_path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)
        return target

    def load(self, path: str | os.PathLike[str] | None = None) -> None:
        source = Path(path) if path is not None else self._store_path
        self.load_dict(json.loads(source.read_text(encoding="utf-8")))

    def load_dict(self, data: dict[str, Any]) -> None:
        data = _require_mapping(data, "store payload")
        users = data.get("users", [])
        groups = data.get("groups", [])
        if not isinstance(users, list) or not isinstance(groups, list):
            raise ScimError("store 'users'/'groups' must be lists", scim_type="invalidValue")
        self._users = {_require_str(u.get("id"), "user id"): u for u in users}
        self._groups = {_require_str(g.get("id"), "group id"): g for g in groups}

    @classmethod
    def from_store(cls, path: str | os.PathLike[str] | None = None) -> DirectoryStore:
        store = cls(store_path=path)
        if store._store_path.exists():
            store.load()
        return store


# --------------------------------------------------------------------------- #
# Sync result
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SyncResult:
    """Deterministic summary of a :meth:`ScimProvider.sync_directory` reconcile."""

    created_users: tuple[str, ...] = ()
    updated_users: tuple[str, ...] = ()
    deactivated_users: tuple[str, ...] = ()
    created_groups: tuple[str, ...] = ()
    updated_groups: tuple[str, ...] = ()
    removed_groups: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "created_users": list(self.created_users),
            "updated_users": list(self.updated_users),
            "deactivated_users": list(self.deactivated_users),
            "created_groups": list(self.created_groups),
            "updated_groups": list(self.updated_groups),
            "removed_groups": list(self.removed_groups),
        }


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #


@dataclass
class ScimProvider:
    """SCIM 2.0 subset provider over a :class:`DirectoryStore`.

    ``id_factory`` and ``clock`` are injected so IDs and ``meta`` timestamps are
    deterministic under test; the production defaults are :func:`uuid.uuid4` and a
    monotonic-ish wall clock.
    """

    store: DirectoryStore = field(default_factory=DirectoryStore)
    id_factory: Callable[[], str] = field(default=lambda: uuid.uuid4().hex)
    clock: Callable[[], float] = field(default=lambda: 0.0)

    # -- create ------------------------------------------------------------ #

    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._create(_USER, payload)

    def create_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._create(_GROUP, payload)

    def _create(self, rtype: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = _require_mapping(payload, f"{rtype} payload")
        key = self._natural_key(rtype)
        _require_str(payload.get(key), f"{rtype}.{key}")
        # Uniqueness on the natural key (userName / displayName).
        if self._find_by_key(rtype, payload[key]) is not None:
            raise ScimError(
                f"{rtype} with {key}={payload[key]!r} already exists",
                status=409,
                scim_type="uniqueness",
            )
        resource = self._normalize(rtype, payload, resource_id=self.id_factory())
        self._stamp(resource, rtype, created=True)
        self.store.put(rtype, resource)
        return resource

    # -- get / list -------------------------------------------------------- #

    def get_user(self, user_id: str) -> dict[str, Any]:
        return self._get(_USER, user_id)

    def get_group(self, group_id: str) -> dict[str, Any]:
        return self._get(_GROUP, group_id)

    def _get(self, rtype: str, resource_id: str) -> dict[str, Any]:
        resource = self.store.get(rtype, resource_id)
        if resource is None:
            raise ScimError(f"{rtype} {resource_id!r} not found", status=404)
        return resource

    def list_users(self, *, filter: str | None = None) -> dict[str, Any]:
        return self._list(_USER, filter=filter)

    def list_groups(self, *, filter: str | None = None) -> dict[str, Any]:
        return self._list(_GROUP, filter=filter)

    def _list(self, rtype: str, *, filter: str | None) -> dict[str, Any]:
        resources = self.store.all(rtype)
        if filter is not None:
            resources = [r for r in resources if _matches_filter(r, filter)]
        return {
            "schemas": [LIST_RESPONSE_SCHEMA],
            "totalResults": len(resources),
            "startIndex": 1,
            "itemsPerPage": len(resources),
            "Resources": resources,
        }

    # -- replace (PUT) ----------------------------------------------------- #

    def replace_user(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._replace(_USER, user_id, payload)

    def replace_group(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._replace(_GROUP, group_id, payload)

    def _replace(self, rtype: str, resource_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self._get(rtype, resource_id)
        payload = _require_mapping(payload, f"{rtype} payload")
        key = self._natural_key(rtype)
        _require_str(payload.get(key), f"{rtype}.{key}")
        resource = self._normalize(rtype, payload, resource_id=resource_id)
        # Preserve creation metadata across a full PUT replace.
        resource["meta"] = dict(existing.get("meta", {}))
        self._stamp(resource, rtype, created=False)
        self.store.put(rtype, resource)
        return resource

    # -- patch (PATCH) ----------------------------------------------------- #

    def patch_user(self, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        return self._patch(_USER, user_id, patch)

    def patch_group(self, group_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        return self._patch(_GROUP, group_id, patch)

    def _patch(self, rtype: str, resource_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = self._get(rtype, resource_id)
        patch = _require_mapping(patch, "PatchOp")
        ops = patch.get("Operations")
        if not isinstance(ops, list) or not ops:
            raise ScimError("PatchOp requires a non-empty 'Operations' array", scim_type="invalidValue")
        resource = json.loads(json.dumps(existing))  # working copy
        for raw_op in ops:
            self._apply_op(resource, _require_mapping(raw_op, "operation"))
        # Natural key must survive a patch.
        _require_str(resource.get(self._natural_key(rtype)), f"{rtype}.{self._natural_key(rtype)}")
        self._stamp(resource, rtype, created=False)
        self.store.put(rtype, resource)
        return resource

    def _apply_op(self, resource: dict[str, Any], operation: dict[str, Any]) -> None:
        raw_op = operation.get("op")
        if not isinstance(raw_op, str) or raw_op.lower() not in ("add", "remove", "replace"):
            raise ScimError(f"invalid patch op {raw_op!r}", scim_type="invalidSyntax")
        op = raw_op.lower()
        path = operation.get("path")
        has_value = "value" in operation
        value = operation.get("value")

        if op == "remove" and path is None:
            raise ScimError("'remove' requires a 'path'", scim_type="noTarget")
        if op in ("add", "replace") and not has_value:
            raise ScimError(f"'{op}' requires a 'value'", scim_type="invalidValue")

        # Entra path-less replace/add: value is an attribute map.
        if path is None:
            attr_map = _require_mapping(value, "value")
            for k, v in attr_map.items():
                self._set_attr(resource, _parse_patch_path(k), v, op)
            return

        if not isinstance(path, str) or not path:
            raise ScimError("patch 'path' must be a non-empty string", scim_type="invalidPath")
        parsed = _parse_patch_path(path)
        if op == "remove":
            self._remove_attr(resource, parsed)
        else:
            self._set_attr(resource, parsed, value, op)

    def _set_attr(self, resource: dict[str, Any], p: _PatchPath, value: Any, op: str) -> None:
        if p.filter is not None:
            # Targeted change on a multi-valued attribute element.
            items = resource.get(p.attr)
            if not isinstance(items, list):
                items = []
            for item in items:
                if isinstance(item, dict) and _matches_filter(item, p.filter):
                    if p.sub is not None:
                        item[p.sub] = value
                    elif isinstance(value, dict):
                        item.update(value)
            resource[p.attr] = items
            return

        if p.sub is not None:
            container = resource.get(p.attr)
            if not isinstance(container, dict):
                container = {}
            container[p.sub] = value
            resource[p.attr] = container
            return

        if p.attr in _MULTI_VALUED and op == "add":
            existing = resource.get(p.attr)
            existing = list(existing) if isinstance(existing, list) else []
            for entry in value if isinstance(value, list) else [value]:
                if entry not in existing:
                    existing.append(entry)
            resource[p.attr] = existing
            return

        resource[p.attr] = value

    def _remove_attr(self, resource: dict[str, Any], p: _PatchPath) -> None:
        if p.filter is not None:
            items = resource.get(p.attr)
            if isinstance(items, list):
                kept = [item for item in items if not (isinstance(item, dict) and _matches_filter(item, p.filter))]
                resource[p.attr] = kept
            return
        if p.sub is not None:
            container = resource.get(p.attr)
            if isinstance(container, dict):
                container.pop(p.sub, None)
            return
        resource.pop(p.attr, None)

    # -- delete ------------------------------------------------------------ #

    def delete_user(self, user_id: str) -> None:
        if not self.store.delete(_USER, user_id):
            raise ScimError(f"User {user_id!r} not found", status=404)

    def delete_group(self, group_id: str) -> None:
        if not self.store.delete(_GROUP, group_id):
            raise ScimError(f"Group {group_id!r} not found", status=404)

    def deactivate_user(self, user_id: str) -> dict[str, Any]:
        """De-provision a user by setting ``active=false`` (soft, never a delete)."""
        return self.patch_user(
            user_id,
            {"schemas": [PATCH_OP_SCHEMA], "Operations": [{"op": "replace", "path": "active", "value": False}]},
        )

    # -- directory sync ---------------------------------------------------- #

    def sync_directory(
        self,
        *,
        users: Iterable[dict[str, Any]] = (),
        groups: Iterable[dict[str, Any]] = (),
    ) -> SyncResult:
        """Reconcile the local directory against an IdP's desired push.

        The ``users`` / ``groups`` iterables are the *complete* desired membership
        the IdP is pushing.  For each resource type:

        - a desired resource with no local match is **created**;
        - a desired resource that differs from its local match is **updated**;
        - a local user the push omits is **de-provisioned** (``active=false``) —
          never hard-deleted;
        - a local group the push omits is **removed**.

        The result is deterministic (all id lists are sorted).
        """
        created_u, updated_u, deactivated_u = self._sync_users(list(users))
        created_g, updated_g, removed_g = self._sync_groups(list(groups))
        return SyncResult(
            created_users=tuple(sorted(created_u)),
            updated_users=tuple(sorted(updated_u)),
            deactivated_users=tuple(sorted(deactivated_u)),
            created_groups=tuple(sorted(created_g)),
            updated_groups=tuple(sorted(updated_g)),
            removed_groups=tuple(sorted(removed_g)),
        )

    def _sync_users(self, desired: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
        created: list[str] = []
        updated: list[str] = []
        deactivated: list[str] = []
        seen_keys: set[str] = set()
        for payload in desired:
            payload = _require_mapping(payload, "sync user")
            key = _require_str(payload.get("userName"), "User.userName").casefold()
            seen_keys.add(key)
            existing = self._find_by_key(_USER, payload["userName"])
            if existing is None:
                created.append(self.create_user(payload)["id"])
            else:
                merged = self._normalize(_USER, payload, resource_id=existing["id"])
                # A returning user is re-activated unless the push says otherwise.
                if "active" not in payload:
                    merged["active"] = True
                if _canonical(merged) != _canonical(existing):
                    merged["meta"] = dict(existing.get("meta", {}))
                    self._stamp(merged, _USER, created=False)
                    self.store.put(_USER, merged)
                    updated.append(existing["id"])
        # De-provision users the push omitted (soft: active=false).
        for user in self.store.all(_USER):
            if user["userName"].casefold() not in seen_keys and user.get("active", True):
                self.deactivate_user(user["id"])
                deactivated.append(user["id"])
        return created, updated, deactivated

    def _sync_groups(self, desired: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
        created: list[str] = []
        updated: list[str] = []
        removed: list[str] = []
        seen_keys: set[str] = set()
        for payload in desired:
            payload = _require_mapping(payload, "sync group")
            key = _require_str(payload.get("displayName"), "Group.displayName").casefold()
            seen_keys.add(key)
            existing = self._find_by_key(_GROUP, payload["displayName"])
            if existing is None:
                created.append(self.create_group(payload)["id"])
            else:
                merged = self._normalize(_GROUP, payload, resource_id=existing["id"])
                if _canonical(merged) != _canonical(existing):
                    merged["meta"] = dict(existing.get("meta", {}))
                    self._stamp(merged, _GROUP, created=False)
                    self.store.put(_GROUP, merged)
                    updated.append(existing["id"])
        for group in self.store.all(_GROUP):
            if group["displayName"].casefold() not in seen_keys:
                self.store.delete(_GROUP, group["id"])
                removed.append(group["id"])
        return created, updated, removed

    # -- internals --------------------------------------------------------- #

    @staticmethod
    def _natural_key(rtype: str) -> str:
        return "userName" if rtype == _USER else "displayName"

    def _find_by_key(self, rtype: str, key_value: str) -> dict[str, Any] | None:
        key = self._natural_key(rtype)
        target = key_value.casefold()
        for resource in self.store.all(rtype):
            if str(resource.get(key, "")).casefold() == target:
                return resource
        return None

    def _normalize(self, rtype: str, payload: dict[str, Any], *, resource_id: str) -> dict[str, Any]:
        """Project an input payload onto the supported SCIM resource shape."""
        schema = USER_SCHEMA if rtype == _USER else GROUP_SCHEMA
        resource: dict[str, Any] = {"schemas": [schema], "id": resource_id}
        if rtype == _USER:
            resource["userName"] = payload["userName"]
            resource["active"] = bool(payload.get("active", True))
            if "name" in payload:
                resource["name"] = payload["name"]
            if "displayName" in payload:
                resource["displayName"] = payload["displayName"]
            resource["emails"] = list(payload.get("emails", []))
            resource["groups"] = list(payload.get("groups", []))
        else:
            resource["displayName"] = payload["displayName"]
            resource["members"] = list(payload.get("members", []))
        return resource

    def _stamp(self, resource: dict[str, Any], rtype: str, *, created: bool) -> None:
        now = self.clock()
        meta = dict(resource.get("meta", {}))
        meta["resourceType"] = rtype
        if created or "created" not in meta:
            meta["created"] = now
        meta["lastModified"] = now
        resource["meta"] = meta
        resource["meta"]["version"] = _etag(resource)


def _default_store_path() -> Path:
    env = os.environ.get(STORE_ENV)
    if env:
        return Path(env)
    runtime = os.environ.get(_RUNTIME_DIR_ENV)
    base = Path(runtime) if runtime else Path.home() / ".thomas"
    return base / "security" / "scim_directory.json"
