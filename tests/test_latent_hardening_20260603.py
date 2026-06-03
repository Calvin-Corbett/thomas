"""Regressions for the 2026-06-03 latent-surface hardening:

* thomas/marketplace/secrets/core.py -- real authenticated encryption (Fernet)
  instead of base64 masquerading as encryption.
* thomas/tools/http_client.py -- SSRF guard before the tool is ever wired into
  the live registry.
* thomas/chat_logger.py -- secret/PII redaction before chat events hit disk.
"""

from __future__ import annotations

import asyncio
import base64

import pytest


def test_secret_encryption_roundtrips_and_is_not_base64() -> None:
    from thomas.marketplace.secrets.core import SecretEncryption

    secret = "hunter2-super-secret-value"
    token = SecretEncryption.encrypt(secret)
    assert token != secret
    assert SecretEncryption.decrypt(token) == secret
    # The old impl was base64(plaintext); prove the plaintext is no longer
    # recoverable by a plain base64 decode.
    try:
        decoded = base64.b64decode(token.encode()).decode("utf-8", "replace")
    except (ValueError, TypeError):
        decoded = ""
    assert secret not in decoded


def test_secret_encryption_rejects_tampered_ciphertext() -> None:
    from thomas.marketplace.secrets.core import SecretEncryption

    token = SecretEncryption.encrypt("x")
    tampered = ("A" if not token.startswith("A") else "B") + token[1:]
    with pytest.raises(Exception):
        SecretEncryption.decrypt(tampered)


def test_secret_vault_stores_ciphertext_not_plaintext() -> None:
    from thomas.marketplace.secrets.core import SecretEncryption, SecretType, SecretVault

    vault = SecretVault()
    vault.store_secret("db", "p@ssw0rd", SecretType.PASSWORD)
    stored = vault.secrets["db"].value
    # The vault stores ciphertext, not the plaintext (nor reversible base64).
    assert stored != "p@ssw0rd"
    assert SecretEncryption.decrypt(stored) == "p@ssw0rd"


def test_http_client_refuses_cloud_metadata_endpoint() -> None:
    from thomas.tools.http_client import HttpClientTool

    tool = HttpClientTool()
    result = asyncio.run(tool.request("GET", "http://169.254.169.254/latest/meta-data/"))
    assert result.ok is False
    assert "SSRF" in (result.error or "")


def test_chat_logger_redacts_secrets_before_disk(tmp_path) -> None:
    from thomas.chat_logger import ChatLogger

    logger = ChatLogger()
    logger.configure(log_dir=str(tmp_path), enabled=True)
    logger.set_session("sess-1")
    logger.log_event("tool_call", {"api_key": "sk-DEADBEEFsecrettoken12345", "note": "keepme"})
    logger.flush()

    files = list(tmp_path.glob("chat_*.jsonl"))
    assert files, "no chat log written"
    text = files[0].read_text(encoding="utf-8")
    assert "sk-DEADBEEFsecrettoken12345" not in text  # secret masked
    assert "keepme" in text  # non-secret field survives
