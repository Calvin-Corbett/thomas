"""Portable capability packs for skills (CAP-023).

This module lives in the ``thomas.skills`` tier and depends only on the
standard library, so it never violates the ``thomas/_architecture.py``
dependency hierarchy.

It provides three capabilities that make skills portable across installs:

1. Versioned export (:func:`export_pack`) - serialize a skill into a
   self-describing pack carrying an explicit ``schema_version``, the skill's
   own ``skill_version``, and a deterministic ``content_hash``.
2. Versioned import (:func:`import_pack`) - validate the schema version
   (rejecting unknown/newer majors), verify the content hash, and rebuild a
   :class:`PortableSkill`. ``export_pack`` -> ``import_pack`` is lossless.
Skill selection is intentionally absent. Thomas discovers skills through
structured tools and chooses one with the frontier model.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PACK_SCHEMA_VERSION",
    "PortableSkill",
    "SkillPackError",
    "export_pack",
    "import_pack",
]

# Explicit pack schema version (independent of any individual skill's version).
# Bumping the MAJOR component signals an incompatible pack layout; readers of an
# older major must refuse to import it rather than silently mis-parse.
PACK_SCHEMA_VERSION = "1.0"

_HASH_ALGO = "sha256"


class SkillPackError(ValueError):
    """Raised when a pack cannot be exported or safely imported."""


@dataclass(slots=True)
class PortableSkill:
    """A minimal, transport-friendly representation of a skill.

    This intentionally mirrors the load-bearing fields of a skill bundle
    (name, description, body, version, keywords, metadata) without depending on
    the runtime bundle type, so packs stay portable across environments.
    """

    name: str
    description: str = ""
    body: str = ""
    version: str = "0.0.0"
    keywords: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


def _as_keywords(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,\n]", value)
    elif isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        return []
    return [token for token in (part.strip() for part in parts) if token]


def _getattr_or_key(skill: Any, key: str) -> Any:
    if isinstance(skill, dict):
        return skill.get(key)
    return getattr(skill, key, None)


def _coerce_portable(skill: Any) -> PortableSkill:
    """Accept a :class:`PortableSkill`, a mapping, or any skill-bundle-like
    object exposing ``name``/``description``/``body``/``metadata`` and return a
    normalized :class:`PortableSkill`."""

    if isinstance(skill, PortableSkill):
        # Copy so callers cannot mutate the pack source through the result.
        return PortableSkill(
            name=_as_str(skill.name),
            description=_as_str(skill.description),
            body=_as_str(skill.body),
            version=_as_str(skill.version) or "0.0.0",
            keywords=list(skill.keywords),
            metadata=dict(skill.metadata),
        )

    name = _as_str(_getattr_or_key(skill, "name")).strip()
    if not name:
        raise SkillPackError("Skill must expose a non-empty name to export.")

    metadata_raw = _getattr_or_key(skill, "metadata")
    metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}

    version = _as_str(_getattr_or_key(skill, "version")).strip()
    if not version:
        version = _as_str(metadata.get("version")).strip() or "0.0.0"

    keywords = _as_keywords(_getattr_or_key(skill, "keywords"))
    if not keywords:
        keywords = _as_keywords(metadata.get("keywords"))

    return PortableSkill(
        name=name,
        description=_as_str(_getattr_or_key(skill, "description")),
        body=_as_str(_getattr_or_key(skill, "body")),
        version=version,
        keywords=keywords,
        metadata=metadata,
    )


def _skill_payload(portable: PortableSkill) -> dict[str, Any]:
    return {
        "name": portable.name,
        "description": portable.description,
        "body": portable.body,
        "version": portable.version,
        "keywords": list(portable.keywords),
        "metadata": dict(portable.metadata),
    }


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    # Sorted keys + no whitespace jitter => deterministic across runs/machines.
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _compute_hash(schema_version: str, skill_version: str, skill_payload: dict[str, Any]) -> str:
    envelope = {
        "schema_version": schema_version,
        "skill_version": skill_version,
        "skill": skill_payload,
    }
    digest = hashlib.new(_HASH_ALGO)
    digest.update(_canonical_bytes(envelope))
    return f"{_HASH_ALGO}:{digest.hexdigest()}"


def _parse_major(version: str) -> int:
    text = _as_str(version).strip()
    head = text.split(".", 1)[0]
    if not head.isdigit():
        raise SkillPackError(f"Malformed schema version {version!r}: expected 'MAJOR.MINOR'.")
    return int(head)


def export_pack(skill: Any) -> dict[str, Any]:
    """Serialize ``skill`` into a versioned, hash-stamped portable pack.

    The returned mapping carries an explicit ``schema_version``, the skill's own
    ``skill_version``, a deterministic ``content_hash`` and the skill payload.
    Two exports of equal skills produce identical packs.
    """

    portable = _coerce_portable(skill)
    skill_payload = _skill_payload(portable)
    content_hash = _compute_hash(PACK_SCHEMA_VERSION, portable.version, skill_payload)
    return {
        "schema_version": PACK_SCHEMA_VERSION,
        "skill_version": portable.version,
        "content_hash": content_hash,
        "skill": skill_payload,
    }


def import_pack(pack: Any) -> PortableSkill:
    """Validate ``pack`` and reconstruct a :class:`PortableSkill`.

    Raises :class:`SkillPackError` when the schema major is unknown/newer than
    this reader supports, when the content hash does not match (tamper), or when
    required fields are missing/malformed. ``import_pack(export_pack(s))`` is a
    lossless round-trip.
    """

    if not isinstance(pack, dict):
        raise SkillPackError("Pack must be a mapping.")

    raw_schema = pack.get("schema_version")
    if raw_schema is None:
        raise SkillPackError("Pack is missing required 'schema_version'.")
    pack_major = _parse_major(raw_schema)
    reader_major = _parse_major(PACK_SCHEMA_VERSION)
    if pack_major > reader_major:
        raise SkillPackError(
            f"Unsupported pack schema major {pack_major} "
            f"(reader supports up to {reader_major}); refusing to import newer pack {raw_schema!r}."
        )
    if pack_major < reader_major:
        raise SkillPackError(
            f"Unsupported pack schema major {pack_major} "
            f"(reader requires major {reader_major}); refusing to import legacy pack {raw_schema!r}."
        )

    skill_payload = pack.get("skill")
    if not isinstance(skill_payload, dict):
        raise SkillPackError("Pack is missing a valid 'skill' payload.")

    name = _as_str(skill_payload.get("name")).strip()
    if not name:
        raise SkillPackError("Pack skill payload must include a non-empty name.")

    skill_version = _as_str(pack.get("skill_version")).strip() or "0.0.0"

    stated_hash = _as_str(pack.get("content_hash")).strip()
    if not stated_hash:
        raise SkillPackError("Pack is missing required 'content_hash'.")

    # Recompute the hash over the canonical payload and compare. Any tampering
    # with the payload, skill_version, or schema_version changes the digest.
    canonical_payload = {
        "name": name,
        "description": _as_str(skill_payload.get("description")),
        "body": _as_str(skill_payload.get("body")),
        "version": _as_str(skill_payload.get("version")).strip() or "0.0.0",
        "keywords": _as_keywords(skill_payload.get("keywords")),
        "metadata": dict(skill_payload["metadata"]) if isinstance(skill_payload.get("metadata"), dict) else {},
    }
    expected_hash = _compute_hash(_as_str(raw_schema), skill_version, canonical_payload)
    if not _constant_time_eq(stated_hash, expected_hash):
        raise SkillPackError("Pack content hash mismatch: the pack may be corrupt or tampered with.")

    return PortableSkill(
        name=canonical_payload["name"],
        description=canonical_payload["description"],
        body=canonical_payload["body"],
        version=canonical_payload["version"],
        keywords=list(canonical_payload["keywords"]),
        metadata=dict(canonical_payload["metadata"]),
    )


def _constant_time_eq(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    result = 0
    for a, b in zip(left, right):
        result |= ord(a) ^ ord(b)
    return result == 0
