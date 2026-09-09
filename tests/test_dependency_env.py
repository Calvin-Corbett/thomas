"""Tests for thomas.tools.dependency_env.

Proves the CAP-008 Level-2 acceptance line:
"Add secret-reference private-index support and atomic lockfile updates
without secret leakage."

All hermetic: temp dirs, an injected fake secret provider, no network, no real
package registry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.tools.dependency_env import (
    IndexConfig,
    MappingSecretProvider,
    ResolvedIndex,
    SecretLeakError,
    SecretResolutionError,
    assert_no_secret_leak,
    build_lock_document,
    count_secret_occurrences,
    find_secret_leaks,
    read_lock,
    resolve_index,
    update_lock,
)

SECRET_VALUE = "tok_live_ZYX987_do_not_leak"
TEMPLATE = "https://__token__:{SECRET:PYPI_TOKEN}@pypi.internal/simple"


@pytest.fixture
def provider() -> MappingSecretProvider:
    return MappingSecretProvider({"PYPI_TOKEN": SECRET_VALUE})


@pytest.fixture
def index() -> IndexConfig:
    return IndexConfig(name="internal", url_template=TEMPLATE)


# ---------------------------------------------------------------------------
# (1) Secret-reference private index: resolves at use time, never leaks
# ---------------------------------------------------------------------------


def test_index_config_records_reference_not_secret(index):
    # The secret name is referenced; the value never appears in the config.
    assert index.secret_names() == ("PYPI_TOKEN",)
    assert SECRET_VALUE not in repr(index)
    assert SECRET_VALUE not in json.dumps(index.to_reference())
    assert "{SECRET:PYPI_TOKEN}" in index.to_reference()["url_template"]


def test_resolve_index_yields_real_url_only_via_reveal(index, provider):
    resolved = resolve_index(index, provider)
    assert isinstance(resolved, ResolvedIndex)
    # reveal() returns the usable URL with the real token substituted in.
    assert resolved.reveal() == TEMPLATE.replace("{SECRET:PYPI_TOKEN}", SECRET_VALUE)
    assert SECRET_VALUE in resolved.reveal()


def test_resolved_index_repr_and_str_redact_secret(index, provider):
    resolved = resolve_index(index, provider)
    # Zero occurrences of the secret in any serialized/repr form.
    assert count_secret_occurrences(repr(resolved), SECRET_VALUE) == 0
    assert count_secret_occurrences(str(resolved), SECRET_VALUE) == 0
    assert count_secret_occurrences(resolved.redacted(), SECRET_VALUE) == 0
    assert "***REDACTED***" in resolved.redacted()


def test_provider_repr_does_not_leak(provider):
    assert count_secret_occurrences(repr(provider), SECRET_VALUE) == 0
    assert "PYPI_TOKEN" in repr(provider)


def test_missing_secret_raises(index):
    empty = MappingSecretProvider({})
    with pytest.raises(SecretResolutionError):
        resolve_index(index, empty)


def test_empty_secret_value_raises(index):
    blank = MappingSecretProvider({"PYPI_TOKEN": ""})
    with pytest.raises(SecretResolutionError):
        resolve_index(index, blank)


# ---------------------------------------------------------------------------
# (2) Lockfile records the index by reference (name), not the secret
# ---------------------------------------------------------------------------


def test_lockfile_stores_reference_not_secret(tmp_path, index, provider):
    # Resolve the secret at use time (as a real install would) BEFORE writing.
    resolved = resolve_index(index, provider)
    assert SECRET_VALUE in resolved.reveal()

    lock = tmp_path / "requirements.lock"
    entries = [{"name": "acme-sdk", "version": "1.2.3", "hash": "sha256:abcd"}]
    update_lock(lock, entries, index=index)

    raw = lock.read_text(encoding="utf-8")
    # The secret value is structurally absent from the persisted lockfile...
    assert count_secret_occurrences(raw, SECRET_VALUE) == 0
    doc = read_lock(lock)
    # ...but the index is recorded by reference (name + placeholder template).
    assert doc["index"]["name"] == "internal"
    assert doc["index"]["url_template"] == TEMPLATE
    assert doc["packages"] == entries


def test_build_lock_document_accepts_as_dict_entries(index):
    class Pin:
        def as_dict(self):
            return {"name": "x", "version": "9"}

    doc = build_lock_document([Pin()], index=index)
    assert doc["packages"] == [{"name": "x", "version": "9"}]


# ---------------------------------------------------------------------------
# (2b) Atomic update: reader sees old-or-new-complete, never truncated
# ---------------------------------------------------------------------------


def test_update_lock_is_atomic_and_leaves_new_complete(tmp_path, index):
    lock = tmp_path / "deps.lock"
    update_lock(lock, [{"name": "a", "version": "1"}], index=index)
    first = read_lock(lock)
    assert first["packages"] == [{"name": "a", "version": "1"}]

    update_lock(lock, [{"name": "a", "version": "2"}], index=index)
    second = read_lock(lock)
    assert second["packages"] == [{"name": "a", "version": "2"}]


def test_mid_write_failure_leaves_old_complete_lock(tmp_path, index, monkeypatch):
    lock = tmp_path / "deps.lock"
    update_lock(lock, [{"name": "a", "version": "1"}], index=index)
    original = lock.read_text(encoding="utf-8")

    # Simulate a crash at the atomic-swap boundary.
    import thomas.tools.dependency_env as dep_env

    def boom(src, dst):
        raise RuntimeError("simulated mid-write failure")

    monkeypatch.setattr(dep_env.os, "replace", boom)

    with pytest.raises(RuntimeError, match="simulated mid-write failure"):
        update_lock(lock, [{"name": "a", "version": "2"}], index=index)

    # Reader sees the OLD, complete file -- never a truncated one.
    after = lock.read_text(encoding="utf-8")
    assert after == original
    assert read_lock(lock)["packages"] == [{"name": "a", "version": "1"}]
    # No stray temp file left behind.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "deps.lock"]
    assert leftovers == []


def test_failure_before_any_prior_lock_creates_no_partial_file(tmp_path, index, monkeypatch):
    lock = tmp_path / "fresh.lock"
    import thomas.tools.dependency_env as dep_env

    def boom(src, dst):
        raise RuntimeError("swap failed")

    monkeypatch.setattr(dep_env.os, "replace", boom)
    with pytest.raises(RuntimeError):
        update_lock(lock, [{"name": "a", "version": "1"}], index=index)

    # The target was never created, and no temp file lingers.
    assert not lock.exists()
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# (3) Leak-check helper
# ---------------------------------------------------------------------------


def test_leak_check_detects_deliberate_leak():
    leaked = f"installing from https://user:{SECRET_VALUE}@pypi.internal/simple"
    assert count_secret_occurrences(leaked, SECRET_VALUE) == 1
    assert find_secret_leaks(leaked, SECRET_VALUE) == {SECRET_VALUE: 1}
    with pytest.raises(SecretLeakError):
        assert_no_secret_leak(leaked, SECRET_VALUE, context="pip log")


def test_leak_check_passes_on_clean_output(tmp_path, index, provider):
    resolved = resolve_index(index, provider)
    clean_log = f"resolved index {resolved} for install"  # uses redacting str
    lock = tmp_path / "clean.lock"
    update_lock(lock, [{"name": "a", "version": "1"}], index=index)
    clean_lock = lock.read_text(encoding="utf-8")

    # Both the log line and the lockfile are clean of the secret.
    assert count_secret_occurrences(clean_log, SECRET_VALUE) == 0
    assert count_secret_occurrences(clean_lock, SECRET_VALUE) == 0
    assert find_secret_leaks(clean_lock, SECRET_VALUE) == {}
    assert_no_secret_leak(clean_log, SECRET_VALUE)
    assert_no_secret_leak(clean_lock, [SECRET_VALUE])  # no raise


def test_assert_requires_a_secret_value():
    with pytest.raises(ValueError):
        assert_no_secret_leak("anything", "")
