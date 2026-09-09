"""Tests for the preferences passphrase-KDF hardening and legacy migration.

THOMAS_SECRET_KEY (a human passphrase) previously derived the at-rest Fernet
key via a single unsalted SHA-256. It now uses salted PBKDF2-HMAC-SHA256, while
MultiFernet keeps the old key for decrypting pre-upgrade data.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from thomas.preferences._db import PreferencesStore
from thomas.preferences._utils import (
    _derive_fernet_key_from_secret,
    _legacy_derive_fernet_key_from_secret,
)

# --- key-derivation properties ----------------------------------------------


def test_pbkdf2_key_is_valid_and_salted():
    key_a = _derive_fernet_key_from_secret("passphrase", b"0123456789abcdef")
    key_b = _derive_fernet_key_from_secret("passphrase", b"fedcba9876543210")
    # Same passphrase, different salt -> different key (defeats shared rainbow tables).
    assert key_a != key_b
    Fernet(key_a)  # both are valid Fernet keys
    Fernet(key_b)


def test_pbkdf2_differs_from_legacy():
    assert _derive_fernet_key_from_secret("pw", b"0123456789abcdef") != _legacy_derive_fernet_key_from_secret("pw")


def test_multifernet_migration_reads_legacy_and_upgrades():
    secret = "operator-passphrase"
    salt = b"0123456789abcdef"
    legacy_f = Fernet(_legacy_derive_fernet_key_from_secret(secret))
    strong_f = Fernet(_derive_fernet_key_from_secret(secret, salt))
    legacy_token = legacy_f.encrypt(b"sk-secret-api-key")

    multi = MultiFernet([strong_f, legacy_f])
    # Old data still decrypts after the upgrade.
    assert multi.decrypt(legacy_token) == b"sk-secret-api-key"
    # New data is encrypted under the strong key, not the legacy one.
    new_token = multi.encrypt(b"new-value")
    assert strong_f.decrypt(new_token) == b"new-value"
    with pytest.raises(InvalidToken):
        legacy_f.decrypt(new_token)


# --- end-to-end through the store -------------------------------------------


def test_db_roundtrip_with_secret_key_persists_salt(tmp_path, monkeypatch):
    monkeypatch.delenv("THOMAS_PREFERENCES_FERNET_KEY", raising=False)
    monkeypatch.setenv("THOMAS_SECRET_KEY", "operator-passphrase")
    db = str(tmp_path / "prefs.db")

    store = PreferencesStore(db)
    store.set_api_key("u1", "openai", "sk-roundtrip-123")
    assert store.get_api_key_plain("u1", "openai") == "sk-roundtrip-123"

    # A fresh store on the same DB + same secret reads it back: the per-install
    # salt was persisted, so the derived key is stable across processes.
    store2 = PreferencesStore(db)
    assert store2.get_api_key_plain("u1", "openai") == "sk-roundtrip-123"
