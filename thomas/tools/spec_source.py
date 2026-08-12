"""CAP-122: Spec-as-source-of-truth rebuilds.

Promote a loose set of prompts / requirements into a maintained, versioned,
canonical :class:`AppSpec`, then treat that spec -- not the prompts, and not the
generated artifact -- as the single source of truth for the app:

- **promote** -- :func:`promote` folds an unordered collection of prompts or
  structured requirements into a canonical :class:`AppSpec`. The spec is
  versioned, order-independent (a ``set`` of prompts promotes to the same spec
  regardless of iteration order), and every capability is keyed by a stable
  name so it can be tracked across revisions.

- **deterministic regeneration** -- :func:`regenerate` renders a spec into an
  artifact through an *injectable* generator. Regeneration is pure: the same
  spec run through the same generator yields byte-for-byte identical output,
  every time, with no timestamps, hashes-of-now, or dict-ordering leakage. The
  built-in :func:`default_generator` is itself deterministic.

- **behavioral diff** -- :func:`behavioral_diff` compares two specs by
  regenerating both and reporting what *behavior* changed between the artifacts:
  which capabilities were **added**, **removed**, or **changed** (same name,
  different behavioral signature). It is not a line-oriented text diff -- a
  cosmetic edit that leaves every capability's behavior intact produces an empty
  behavioral diff, and an unchanged spec always produces an empty diff.

This module depends only on the standard library (tools-layer rule: no imports
from agent/server/cli).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Union

__all__ = [
    "SpecError",
    "Capability",
    "AppSpec",
    "BehavioralDiff",
    "promote",
    "regenerate",
    "behavioral_diff",
    "default_generator",
]

# A prompt is either a free-form/"name: summary" string or a structured mapping.
PromptSource = Union[str, Mapping[str, Any]]

# A generator turns a spec into an artifact. Returning ``str`` is allowed and is
# encoded as UTF-8; returning ``bytes`` is used verbatim.
Generator = Callable[["AppSpec"], Union[bytes, str]]

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class SpecError(ValueError):
    """Raised when prompts cannot be promoted into a well-formed spec."""


def _slugify(text: str) -> str:
    """Deterministically derive a stable capability name from free text."""
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug


def _normalize_str_seq(value: Any, *, field_name: str) -> tuple[str, ...]:
    """Coerce a scalar/sequence of strings into a cleaned tuple of strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        items: Sequence[Any] = [value]
    elif isinstance(value, Sequence):
        items = value
    else:
        raise SpecError(f"{field_name} must be a string or sequence of strings")
    cleaned: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise SpecError(f"{field_name} entries must be strings, got {type(item)!r}")
        stripped = item.strip()
        if stripped:
            cleaned.append(stripped)
    return tuple(cleaned)


@dataclass(frozen=True)
class Capability:
    """A single behavioral unit of an app.

    The *behavioral signature* -- ``summary`` plus the ordered ``inputs``,
    ``outputs`` and ``effects`` -- is what :func:`behavioral_diff` compares. Two
    capabilities with the same :attr:`name` but different signatures represent a
    behavior change, not merely a reworded description.
    """

    name: str
    summary: str = ""
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise SpecError("capability name must be non-empty")
        # Freeze any incoming lists into tuples so the dataclass stays hashable
        # and comparisons are value-based.
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "effects", tuple(self.effects))

    def behavior_signature(self) -> tuple[Any, ...]:
        """Canonical tuple capturing this capability's behavior (not its name)."""
        return (self.summary, self.inputs, self.outputs, self.effects)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "effects": list(self.effects),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Capability:
        return cls(
            name=str(data["name"]),
            summary=str(data.get("summary", "")),
            inputs=_normalize_str_seq(data.get("inputs"), field_name="inputs"),
            outputs=_normalize_str_seq(data.get("outputs"), field_name="outputs"),
            effects=_normalize_str_seq(data.get("effects"), field_name="effects"),
        )


@dataclass(frozen=True)
class AppSpec:
    """A versioned, canonical description of an app.

    Capabilities are stored sorted by name so the spec is order-independent and
    two specs built from the same requirements compare equal regardless of how
    the requirements were originally ordered.
    """

    name: str
    version: int = 1
    capabilities: tuple[Capability, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise SpecError("spec name must be non-empty")
        if not isinstance(self.version, int) or self.version < 1:
            raise SpecError("spec version must be an integer >= 1")
        seen: set[str] = set()
        for cap in self.capabilities:
            if cap.name in seen:
                raise SpecError(f"duplicate capability name: {cap.name!r}")
            seen.add(cap.name)
        ordered = tuple(sorted(self.capabilities, key=lambda c: c.name))
        object.__setattr__(self, "capabilities", ordered)
        object.__setattr__(self, "metadata", tuple(sorted(dict(self.metadata).items())))

    # -- capability access --------------------------------------------------
    def capability_map(self) -> dict[str, Capability]:
        return {cap.name: cap for cap in self.capabilities}

    def capability_names(self) -> tuple[str, ...]:
        return tuple(cap.name for cap in self.capabilities)

    # -- maintenance --------------------------------------------------------
    def bump(
        self,
        *,
        capabilities: Iterable[Capability] | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> AppSpec:
        """Return a maintained successor spec with an incremented version.

        This is how the spec is kept as the source of truth: edits produce a new
        canonical revision rather than mutating in place.
        """
        return AppSpec(
            name=self.name,
            version=self.version + 1,
            capabilities=(tuple(capabilities) if capabilities is not None else self.capabilities),
            metadata=(tuple(metadata.items()) if metadata is not None else self.metadata),
        )

    # -- serialization / round-trip ----------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "capabilities": [cap.to_dict() for cap in self.capabilities],
            "metadata": {k: v for k, v in self.metadata},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AppSpec:
        caps = tuple(Capability.from_dict(c) for c in data.get("capabilities", []) or [])
        meta = data.get("metadata") or {}
        if not isinstance(meta, Mapping):
            raise SpecError("metadata must be a mapping")
        return cls(
            name=str(data["name"]),
            version=int(data.get("version", 1)),
            capabilities=caps,
            metadata=tuple((str(k), str(v)) for k, v in meta.items()),
        )

    def canonical_bytes(self) -> bytes:
        """Stable canonical JSON encoding of the spec itself."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> AppSpec:
        return cls.from_dict(json.loads(text))

    def fingerprint(self) -> str:
        """Content hash uniquely identifying this canonical spec revision."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Promotion: prompts / requirements -> canonical AppSpec
# ---------------------------------------------------------------------------


def _capability_from_prompt(prompt: PromptSource) -> Capability:
    if isinstance(prompt, Mapping):
        name_raw = prompt.get("name")
        if not name_raw or not str(name_raw).strip():
            raise SpecError("structured prompt requires a non-empty 'name'")
        return Capability(
            name=_slugify(str(name_raw)) or str(name_raw).strip(),
            summary=str(prompt.get("summary", "")).strip(),
            inputs=_normalize_str_seq(prompt.get("inputs"), field_name="inputs"),
            outputs=_normalize_str_seq(prompt.get("outputs"), field_name="outputs"),
            effects=_normalize_str_seq(prompt.get("effects"), field_name="effects"),
        )
    if isinstance(prompt, str):
        text = prompt.strip()
        if not text:
            raise SpecError("prompt string must be non-empty")
        if ":" in text:
            head, _, tail = text.partition(":")
            name = _slugify(head)
            summary = tail.strip()
        else:
            name = _slugify(text)
            summary = text
        if not name:
            raise SpecError(f"could not derive a capability name from prompt: {text!r}")
        return Capability(name=name, summary=summary)
    raise SpecError(f"unsupported prompt type: {type(prompt)!r}")


def promote(
    prompts: Iterable[PromptSource],
    *,
    name: str,
    version: int = 1,
    metadata: Mapping[str, str] | None = None,
) -> AppSpec:
    """Promote a collection of prompts / requirements into a canonical spec.

    ``prompts`` may be any iterable (including a ``set``); the result is
    deterministic and order-independent. Each prompt becomes one capability,
    keyed by a stable name. Duplicate capability names raise :class:`SpecError`.
    """
    capabilities = [_capability_from_prompt(p) for p in prompts]
    if not capabilities:
        raise SpecError("cannot promote an empty set of prompts")
    return AppSpec(
        name=name,
        version=version,
        capabilities=tuple(capabilities),
        metadata=tuple((metadata or {}).items()),
    )


# ---------------------------------------------------------------------------
# Deterministic regeneration
# ---------------------------------------------------------------------------


def default_generator(spec: AppSpec) -> str:
    """Render a spec into a deterministic textual app scaffold.

    The output is a pure function of the spec: capabilities are emitted in
    canonical (name-sorted) order and there are no timestamps or other
    non-deterministic elements, so regenerating the same spec twice is
    byte-identical.
    """
    lines: list[str] = []
    lines.append(f"# App: {spec.name}")
    lines.append(f"# Spec-Version: {spec.version}")
    for key, value in spec.metadata:
        lines.append(f"# {key}: {value}")
    lines.append("")
    for cap in spec.capabilities:
        lines.append(f"capability {cap.name}:")
        lines.append(f"  summary: {cap.summary}")
        lines.append(f"  inputs: {', '.join(cap.inputs)}")
        lines.append(f"  outputs: {', '.join(cap.outputs)}")
        lines.append(f"  effects: {', '.join(cap.effects)}")
        lines.append("")
    return "\n".join(lines)


def regenerate(spec: AppSpec, generator: Generator | None = None) -> bytes:
    """Regenerate the app artifact from ``spec`` using ``generator``.

    Deterministic by contract: for a fixed ``spec`` and ``generator`` the return
    value is byte-for-byte identical on every call. If ``generator`` returns a
    ``str`` it is UTF-8 encoded; ``bytes`` are returned verbatim.
    """
    gen = generator or default_generator
    artifact = gen(spec)
    if isinstance(artifact, str):
        return artifact.encode("utf-8")
    if isinstance(artifact, (bytes, bytearray)):
        return bytes(artifact)
    raise SpecError(f"generator must return str or bytes, got {type(artifact)!r}")


# ---------------------------------------------------------------------------
# Behavioral diff
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityChange:
    """A single changed capability, with old and new behavioral signatures."""

    name: str
    old: Capability
    new: Capability


@dataclass(frozen=True)
class BehavioralDiff:
    """The behavioral delta between two regenerated artifacts.

    ``added`` / ``removed`` name capabilities that appeared or disappeared;
    ``changed`` names capabilities present in both whose behavior changed.
    ``artifact_changed`` reports whether the regenerated bytes differ at all.
    """

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[CapabilityChange, ...] = ()
    artifact_changed: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    @property
    def changed_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.changed)

    def summary(self) -> str:
        if self.is_empty:
            return "no behavioral change"
        parts: list[str] = []
        if self.added:
            parts.append(f"added: {', '.join(self.added)}")
        if self.removed:
            parts.append(f"removed: {', '.join(self.removed)}")
        if self.changed:
            parts.append(f"changed: {', '.join(self.changed_names)}")
        return "; ".join(parts)


def behavioral_diff(
    old_spec: AppSpec,
    new_spec: AppSpec,
    generate: Generator | None = None,
) -> BehavioralDiff:
    """Report what *behavior* changed between two specs' regenerated artifacts.

    Both specs are regenerated through ``generate`` (default: the built-in
    deterministic generator). The diff is capability-oriented -- added, removed,
    and behaviorally-changed capabilities -- rather than a line-level text diff.
    An unchanged spec (equal capabilities) yields an empty diff.
    """
    old_artifact = regenerate(old_spec, generate)
    new_artifact = regenerate(new_spec, generate)

    old_caps = old_spec.capability_map()
    new_caps = new_spec.capability_map()

    added = tuple(sorted(n for n in new_caps if n not in old_caps))
    removed = tuple(sorted(n for n in old_caps if n not in new_caps))

    changed: list[CapabilityChange] = []
    for cap_name in sorted(set(old_caps) & set(new_caps)):
        old_cap = old_caps[cap_name]
        new_cap = new_caps[cap_name]
        if old_cap.behavior_signature() != new_cap.behavior_signature():
            changed.append(CapabilityChange(name=cap_name, old=old_cap, new=new_cap))

    return BehavioralDiff(
        added=added,
        removed=removed,
        changed=tuple(changed),
        artifact_changed=old_artifact != new_artifact,
    )
