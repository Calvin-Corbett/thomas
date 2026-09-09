"""Named repository groups with pinned revisions and access boundaries.

A *repo group* bundles several repositories under one name so a caller can
reason about them as a unit -- e.g. a service and the libraries it vendors, or
a fleet of microservices deployed together.  Three properties make a group
safe to hand to an autonomous agent:

1. **Pinned revisions.** Every member records a specific revision (a 40-hex
   commit sha or a non-empty tag) rather than a floating branch.  A group with
   a member that has no pin is *unpinned* (floating) -- reproducibility is
   broken and the group cannot be trusted to resolve to the same code twice.
   ``verify_pins`` performs a purely local format check (no network) and
   flags every member whose pin is missing or malformed.

2. **Read/write boundaries.** Each member is declared ``read`` (read-only) or
   ``write`` (read-write).  ``check_access(group, repo, mode)`` denies a write
   to a read-only member -- and denies *any* access to a repository that is
   not a member of the group -- with a clear, human-readable reason.  The
   boundary is a policy decision object, not an OS permission: it is meant to
   gate an agent's own actions before it touches a repo.

3. **Durable definitions.** Group definitions persist as JSON.  The store path
   comes from ``THOMAS_REPO_GROUPS_PATH`` when set, else a caller-supplied
   path.  State round-trips: what you save is what you load.

This module is deliberately self-contained (only stdlib) so it sits cleanly in
``thomas.tools`` without new cross-package edges.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STORE_PATH_ENV = "THOMAS_REPO_GROUPS_PATH"

# Access modes a caller can request.
MODE_READ = "read"
MODE_WRITE = "write"
_ACCESS_MODES = frozenset({MODE_READ, MODE_WRITE})

# Boundary a member is declared with.
ACCESS_READ_ONLY = "read"
ACCESS_READ_WRITE = "write"
_MEMBER_ACCESS = frozenset({ACCESS_READ_ONLY, ACCESS_READ_WRITE})

# Pin format: either a full 40-char lowercase-hex commit sha, or a non-empty
# tag.  We treat anything that is not a full sha as a tag and validate the tag
# shape conservatively (no whitespace, no ref-hostile characters).
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TAG_RE = re.compile(r"^[^\s~^:?*\[\\]+$")

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class RepoGroupError(ValueError):
    """Raised for invalid group/member definitions or unknown lookups."""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _norm_repo(repo: str) -> str:
    """Normalize a repo identifier for equality comparison.

    Local paths and URLs are compared case-insensitively with a trailing
    slash and a trailing ``.git`` stripped so ``.../foo`` and ``.../foo.git``
    match.  Backslashes fold to forward slashes so Windows paths compare
    stably against the stored POSIX form.
    """
    text = str(repo or "").strip().replace("\\", "/").rstrip("/")
    lowered = text.lower()
    if lowered.endswith(".git"):
        text = text[: -len(".git")]
    return text.lower()


def classify_pin(revision: str) -> str:
    """Classify *revision* as ``"sha"``, ``"tag"``, or ``"unpinned"``.

    Pure format inspection -- no repository or network access.
    """
    text = str(revision or "").strip()
    if not text:
        return "unpinned"
    if _FULL_SHA_RE.match(text):
        return "sha"
    if _TAG_RE.match(text):
        return "tag"
    return "unpinned"


@dataclass(frozen=True)
class RepoMember:
    """One repository inside a group, with its pin and access boundary."""

    repo: str
    revision: str = ""
    access: str = ACCESS_READ_ONLY
    name: str = ""

    def __post_init__(self) -> None:
        repo = str(self.repo or "").strip()
        if not repo:
            raise RepoGroupError("repo member requires a non-empty repo path/url")
        object.__setattr__(self, "repo", repo)
        access = str(self.access or "").strip().lower()
        if access not in _MEMBER_ACCESS:
            raise RepoGroupError(f"member {repo!r} has invalid access {self.access!r} (expected 'read' or 'write')")
        object.__setattr__(self, "access", access)
        object.__setattr__(self, "revision", str(self.revision or "").strip())
        object.__setattr__(self, "name", str(self.name or "").strip())

    @property
    def read_only(self) -> bool:
        return self.access == ACCESS_READ_ONLY

    @property
    def pin_kind(self) -> str:
        return classify_pin(self.revision)

    @property
    def is_pinned(self) -> bool:
        return self.pin_kind != "unpinned"

    def matches(self, repo: str) -> bool:
        """True when *repo* names this member (by repo id or explicit name)."""
        target = _norm_repo(repo)
        if _norm_repo(self.repo) == target:
            return True
        return bool(self.name) and self.name.strip().lower() == str(repo or "").strip().lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "revision": self.revision,
            "access": self.access,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RepoMember:
        data = dict(data or {})
        return cls(
            repo=str(data.get("repo") or ""),
            revision=str(data.get("revision") or ""),
            access=str(data.get("access") or ACCESS_READ_ONLY),
            name=str(data.get("name") or ""),
        )


@dataclass(frozen=True)
class RepoGroup:
    """A named collection of pinned repository members."""

    name: str
    members: tuple[RepoMember, ...] = ()
    description: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not _NAME_RE.match(name):
            raise RepoGroupError(f"invalid group name {self.name!r} (use letters, digits, '.', '_', '-', '/')")
        object.__setattr__(self, "name", name)
        seen: set[str] = set()
        for member in self.members:
            key = _norm_repo(member.repo)
            if key in seen:
                raise RepoGroupError(f"duplicate member {member.repo!r} in group {name!r}")
            seen.add(key)
        object.__setattr__(self, "description", str(self.description or "").strip())

    def member_for(self, repo: str) -> RepoMember | None:
        for member in self.members:
            if member.matches(repo):
                return member
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "updated_at": self.updated_at,
            "members": [member.to_dict() for member in self.members],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RepoGroup:
        data = dict(data or {})
        members = data.get("members")
        rows = members if isinstance(members, list) else []
        return cls(
            name=str(data.get("name") or ""),
            members=tuple(RepoMember.from_dict(row) for row in rows if isinstance(row, Mapping)),
            description=str(data.get("description") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class ResolvedGroup:
    """A group resolved to its members and their pinned revisions."""

    name: str
    members: tuple[RepoMember, ...]

    @property
    def pins(self) -> dict[str, str]:
        """Map of ``repo -> revision`` for every member."""
        return {member.repo: member.revision for member in self.members}


@dataclass(frozen=True)
class AccessDecision:
    """The outcome of an access check against a group boundary."""

    allowed: bool
    group: str
    repo: str
    mode: str
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


@dataclass(frozen=True)
class PinIssue:
    """One member whose pin failed the local integrity check."""

    repo: str
    revision: str
    kind: str
    reason: str


@dataclass(frozen=True)
class PinReport:
    """Result of verifying every member's pin in a group."""

    group: str
    issues: tuple[PinIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def unpinned(self) -> tuple[PinIssue, ...]:
        return tuple(issue for issue in self.issues if issue.kind == "unpinned")


def _access_denied(group: str, repo: str, mode: str, reason: str) -> AccessDecision:
    return AccessDecision(allowed=False, group=group, repo=repo, mode=mode, reason=reason)


@dataclass
class RepoGroupRegistry:
    """In-memory registry of repo groups with an optional durable JSON store.

    Construct with a ``store_path`` (or set ``THOMAS_REPO_GROUPS_PATH``) to
    persist; ``load`` / ``save`` round-trip the definitions.  All mutation is
    explicit -- nothing writes to disk unless ``save`` is called.
    """

    store_path: Path | None = None
    _groups: dict[str, RepoGroup] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.store_path is not None:
            self.store_path = Path(self.store_path)

    # -- construction --------------------------------------------------------
    @classmethod
    def from_env(cls, default_path: str | os.PathLike[str] | None = None) -> RepoGroupRegistry:
        """Build a registry whose store path comes from the environment.

        ``THOMAS_REPO_GROUPS_PATH`` wins when set and non-empty; otherwise
        *default_path* is used (may be ``None`` for a memory-only registry).
        """
        override = os.environ.get(STORE_PATH_ENV, "").strip()
        if override:
            return cls(store_path=Path(override))
        if default_path is not None:
            return cls(store_path=Path(default_path))
        return cls()

    # -- definition ----------------------------------------------------------
    def define_group(
        self,
        name: str,
        members: Iterable[RepoMember | Mapping[str, Any]],
        *,
        description: str = "",
    ) -> RepoGroup:
        """Define (or replace) a named group and return it.

        Members may be ``RepoMember`` instances or plain mappings.  A group
        with zero members is rejected -- an empty boundary is meaningless.
        """
        parsed: list[RepoMember] = []
        for member in members:
            if isinstance(member, RepoMember):
                parsed.append(member)
            elif isinstance(member, Mapping):
                parsed.append(RepoMember.from_dict(member))
            else:
                raise RepoGroupError(f"member must be RepoMember or mapping, got {type(member).__name__}")
        if not parsed:
            raise RepoGroupError(f"group {name!r} must have at least one member")
        group = RepoGroup(
            name=name,
            members=tuple(parsed),
            description=description,
            updated_at=_utc_iso(),
        )
        self._groups[group.name] = group
        return group

    def remove_group(self, name: str) -> bool:
        return self._groups.pop(str(name or "").strip(), None) is not None

    def group_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._groups))

    def get_group(self, name: str) -> RepoGroup:
        key = str(name or "").strip()
        group = self._groups.get(key)
        if group is None:
            raise RepoGroupError(f"unknown repo group {name!r}")
        return group

    # -- resolution ----------------------------------------------------------
    def resolve(self, name: str) -> ResolvedGroup:
        """Resolve a group to its members and their pinned revisions."""
        group = self.get_group(name)
        return ResolvedGroup(name=group.name, members=group.members)

    # -- access enforcement --------------------------------------------------
    def check_access(self, group: str, repo: str, mode: str) -> AccessDecision:
        """Decide whether *mode* access to *repo* is allowed within *group*.

        Denies a write to a read-only member, denies any access to a
        non-member repo, and denies an unrecognised mode -- each with a clear
        reason.  A read to any member, and a write to a read-write member, is
        allowed.
        """
        requested = str(mode or "").strip().lower()
        if requested not in _ACCESS_MODES:
            return _access_denied(
                str(group),
                str(repo),
                requested,
                f"unrecognised access mode {mode!r} (expected 'read' or 'write')",
            )
        try:
            resolved_group = self.get_group(group)
        except RepoGroupError as exc:
            return _access_denied(str(group), str(repo), requested, str(exc))
        member = resolved_group.member_for(repo)
        if member is None:
            return _access_denied(
                resolved_group.name,
                str(repo),
                requested,
                f"repo {repo!r} is not a member of group {resolved_group.name!r}; access denied",
            )
        if requested == MODE_WRITE and member.read_only:
            return _access_denied(
                resolved_group.name,
                member.repo,
                requested,
                f"repo {member.repo!r} is read-only in group {resolved_group.name!r}; write denied",
            )
        return AccessDecision(
            allowed=True,
            group=resolved_group.name,
            repo=member.repo,
            mode=requested,
            reason=f"{requested} access to {member.repo!r} permitted ({member.access})",
        )

    # -- pin integrity -------------------------------------------------------
    def verify_pins(self, group: str) -> PinReport:
        """Verify each member's pin is a valid sha/tag (local format only).

        Flags every member whose revision is missing (an accidental floating
        member) or malformed.  No repository or network access is performed.
        """
        resolved_group = self.get_group(group)
        issues: list[PinIssue] = []
        for member in resolved_group.members:
            kind = member.pin_kind
            if kind == "unpinned":
                reason = (
                    f"member {member.repo!r} is unpinned (floating): revision is empty"
                    if not member.revision
                    else f"member {member.repo!r} has malformed revision {member.revision!r} "
                    "(not a 40-hex sha or a valid tag)"
                )
                issues.append(PinIssue(repo=member.repo, revision=member.revision, kind="unpinned", reason=reason))
        return PinReport(group=resolved_group.name, issues=tuple(issues))

    # -- persistence ---------------------------------------------------------
    def _resolve_store_path(self, path: str | os.PathLike[str] | None) -> Path:
        target = path if path is not None else self.store_path
        if target is None:
            raise RepoGroupError(
                f"no store path configured (set {STORE_PATH_ENV}, pass store_path, or a path argument)"
            )
        return Path(target)

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        """Persist all group definitions to JSON atomically; return the path."""
        target = self._resolve_store_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _utc_iso(),
            "groups": [group.to_dict() for group in sorted(self._groups.values(), key=lambda g: g.name)],
        }
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        return target

    def load(self, path: str | os.PathLike[str] | None = None) -> RepoGroupRegistry:
        """Load group definitions from JSON, replacing the in-memory set.

        A missing file yields an empty registry (not an error).  Malformed
        rows are skipped; an entirely unparseable file raises.
        """
        target = self._resolve_store_path(path)
        if not target.exists():
            self._groups = {}
            return self
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RepoGroupError(f"cannot read repo groups store {target}: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise RepoGroupError(f"repo groups store {target} is not a JSON object")
        rows = payload.get("groups")
        loaded: dict[str, RepoGroup] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            try:
                group = RepoGroup.from_dict(row)
            except RepoGroupError:
                continue
            loaded[group.name] = group
        self._groups = loaded
        return self


def build_member(
    repo: str,
    revision: str = "",
    *,
    access: str = ACCESS_READ_ONLY,
    name: str = "",
) -> RepoMember:
    """Convenience constructor for a :class:`RepoMember`."""
    return RepoMember(repo=repo, revision=revision, access=access, name=name)


def with_revision(member: RepoMember, revision: str) -> RepoMember:
    """Return a copy of *member* pinned to *revision*."""
    return replace(member, revision=str(revision or "").strip())
