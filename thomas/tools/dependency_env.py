"""Dependency & environment management: secret-referenced private indexes and
atomic lockfile updates without secret leakage.

Two hard invariants drive this module:

1. **Secret-reference private index support.** A package index / registry URL
   may reference a secret by *name* using a ``{SECRET:NAME}`` placeholder, e.g.
   ``https://__token__:{SECRET:PYPI_TOKEN}@pypi.internal/simple``. The real
   token is resolved from an injected :class:`SecretProvider` **at use time
   only** (:func:`resolve_index`). The resolved value is never written to disk,
   never placed in a lockfile, and never included in any log or serialized
   form. Config objects store only the *reference* (the placeholder), and the
   resolved-URL wrapper (:class:`ResolvedIndex`) redacts the secret in every
   ``repr``/``str``.

2. **Atomic lockfile updates.** :func:`update_lock` serializes the whole
   lockfile to a sibling temp file (``flush`` + ``fsync``) and swaps it into
   place with ``os.replace``. Because ``os.replace`` is atomic on a single
   filesystem, a concurrent reader always sees either the complete *old* file
   or the complete *new* file -- never a half-written one. The lockfile records
   the index by **reference** (its name and the placeholder template), so the
   secret value is structurally absent from the persisted artifact.

A leak-check helper (:func:`assert_no_secret_leak` / :func:`count_secret_occurrences`)
scans a produced lockfile or log string and asserts zero occurrences of a known
secret value.

This module depends only on the standard library (tools-layer rule: no imports
from agent/server/cli).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ``{SECRET:NAME}`` -- NAME is an env-var-style identifier.
_SECRET_PATTERN = re.compile(r"\{SECRET:([A-Za-z0-9_.\-]+)\}")

# What a redacted secret is replaced with in any human/serialized form.
REDACTION_MASK = "***REDACTED***"

LOCKFILE_VERSION = 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SecretResolutionError(RuntimeError):
    """A ``{SECRET:NAME}`` reference could not be resolved to a real value."""


class SecretLeakError(RuntimeError):
    """A known secret value was found where it must never appear."""


# ---------------------------------------------------------------------------
# Secret providers (injected at use time -- nothing is persisted)
# ---------------------------------------------------------------------------


@runtime_checkable
class SecretProvider(Protocol):
    """Resolves a secret name to its value. Injected by the caller."""

    def get_secret(self, name: str) -> str: ...


class MappingSecretProvider:
    """In-memory provider backed by a name -> value mapping.

    Its ``repr`` never reveals the stored values, so accidentally logging the
    provider cannot leak a secret.
    """

    __slots__ = ("_secrets",)

    def __init__(self, secrets: Mapping[str, str]):
        self._secrets = dict(secrets)

    def get_secret(self, name: str) -> str:
        try:
            return self._secrets[name]
        except KeyError as exc:
            raise SecretResolutionError(f"unknown secret reference: {name!r}") from exc

    def __repr__(self) -> str:
        names = ", ".join(sorted(self._secrets))
        return f"MappingSecretProvider(names=[{names}])"


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------


def redact_text(text: str, secret_values: Iterable[str]) -> str:
    """Return ``text`` with every non-empty secret value masked."""
    out = text
    for value in secret_values:
        if value:
            out = out.replace(value, REDACTION_MASK)
    return out


# ---------------------------------------------------------------------------
# Index configuration -- stores the REFERENCE, never the resolved secret
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexConfig:
    """A package index identified by ``name`` whose URL may reference secrets.

    ``url_template`` holds ``{SECRET:NAME}`` placeholders -- i.e. references,
    not values -- so the config is safe to serialize and ``repr``.
    """

    name: str
    url_template: str

    def secret_names(self) -> tuple[str, ...]:
        """Distinct secret names referenced by the template, in first-seen order."""
        return tuple(dict.fromkeys(_SECRET_PATTERN.findall(self.url_template)))

    def to_reference(self) -> dict[str, str]:
        """Persistable form: name + placeholder template. Contains no secret value."""
        return {"name": self.name, "url_template": self.url_template}


class ResolvedIndex:
    """A resolved index URL. The real URL is reachable only via :meth:`reveal`;
    every ``repr``/``str`` form redacts the embedded secret value(s)."""

    __slots__ = ("name", "_url", "_secrets")

    def __init__(self, name: str, url: str, secret_values: Iterable[str]):
        self.name = name
        self._url = url
        self._secrets = tuple(v for v in secret_values if v)

    def reveal(self) -> str:
        """Return the real resolved URL. Callers must not log or persist this."""
        return self._url

    def redacted(self) -> str:
        """Return the URL with secret value(s) masked -- safe to log."""
        return redact_text(self._url, self._secrets)

    def __repr__(self) -> str:
        return f"ResolvedIndex(name={self.name!r}, url={self.redacted()!r})"

    def __str__(self) -> str:
        return self.redacted()


def resolve_index(config: IndexConfig, provider: SecretProvider) -> ResolvedIndex:
    """Resolve ``config``'s ``{SECRET:NAME}`` references using ``provider``.

    Resolution happens here, at use time, and nowhere else. A missing or empty
    secret raises :class:`SecretResolutionError`.
    """
    used_values: list[str] = []

    def _substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        value = provider.get_secret(name)
        if not value:
            raise SecretResolutionError(f"secret {name!r} resolved to an empty value")
        used_values.append(value)
        return value

    url = _SECRET_PATTERN.sub(_substitute, config.url_template)
    return ResolvedIndex(config.name, url, used_values)


# ---------------------------------------------------------------------------
# Lockfile: atomic writes that record the index by reference
# ---------------------------------------------------------------------------


def _normalize_entry(entry: Mapping[str, object] | object) -> dict[str, object]:
    if isinstance(entry, Mapping):
        return dict(entry)
    as_dict = getattr(entry, "as_dict", None)
    if callable(as_dict):
        result = as_dict()
        if isinstance(result, Mapping):
            return dict(result)
    raise TypeError(f"lock entry must be a mapping or expose as_dict(): {type(entry).__name__}")


def build_lock_document(
    entries: Iterable[Mapping[str, object] | object],
    *,
    index: IndexConfig | None = None,
    version: int = LOCKFILE_VERSION,
) -> dict[str, object]:
    """Build the lockfile document. The index is recorded by reference only."""
    return {
        "version": version,
        "index": index.to_reference() if index is not None else None,
        "packages": [_normalize_entry(e) for e in entries],
    }


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically via temp-file + ``os.replace``.

    A failure at any point leaves the original ``path`` untouched (never a
    truncated file) and removes the temp file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        # Broad catch is deliberate: on ANY failure (write, fsync, replace, or
        # an injected mid-write fault) we must not leave a stray temp file, then
        # we re-raise so the caller learns the update did not land.
        logger.warning("atomic lockfile write failed; cleaning temp %s", tmp)
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def update_lock(
    path: str | os.PathLike[str],
    entries: Iterable[Mapping[str, object] | object],
    *,
    index: IndexConfig | None = None,
    version: int = LOCKFILE_VERSION,
) -> dict[str, object]:
    """Atomically update the lockfile at ``path``.

    The document is written to a sibling temp file and swapped in with
    ``os.replace`` so a concurrent reader never observes a half-written file.
    The index is stored by reference (name + placeholder template), so no secret
    value is ever persisted. Returns the document that was written.
    """
    document = build_lock_document(entries, index=index, version=version)
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_bytes(Path(path), payload)
    return document


def read_lock(path: str | os.PathLike[str]) -> dict[str, object]:
    """Read and parse a lockfile written by :func:`update_lock`."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Leak check
# ---------------------------------------------------------------------------


def _coerce_secret_values(secret_values: str | Iterable[str]) -> list[str]:
    if isinstance(secret_values, str):
        return [secret_values] if secret_values else []
    return [v for v in secret_values if v]


def count_secret_occurrences(blob: str, secret_values: str | Iterable[str]) -> int:
    """Total occurrences of any of ``secret_values`` inside ``blob``."""
    return sum(blob.count(value) for value in _coerce_secret_values(secret_values))


def find_secret_leaks(blob: str, secret_values: str | Iterable[str]) -> dict[str, int]:
    """Map each leaked secret value to its occurrence count (only >0 entries)."""
    counts = {value: blob.count(value) for value in _coerce_secret_values(secret_values)}
    return {value: n for value, n in counts.items() if n > 0}


def assert_no_secret_leak(
    blob: str,
    secret_values: str | Iterable[str],
    *,
    context: str = "output",
) -> None:
    """Raise :class:`SecretLeakError` if any secret value appears in ``blob``."""
    values = _coerce_secret_values(secret_values)
    if not values:
        raise ValueError("assert_no_secret_leak requires at least one non-empty secret value")
    total = sum(blob.count(value) for value in values)
    if total:
        raise SecretLeakError(f"secret value leaked into {context} ({total} occurrence(s))")
