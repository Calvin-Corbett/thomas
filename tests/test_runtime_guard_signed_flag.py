"""Regressions for the gate-side signed-flag validator (praxis-unbypassable B9).

The runtime-protection disable flag must only be honored when it is HMAC-signed
with the per-install key. An unsigned flag planted by an agent (the original B9
bypass) must NOT disable the gates.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from scripts.forge.gates._runtime_guard import runtime_protection_disabled


def _write_signed_flag(root, *, key: bytes, version=1, issued_by="tester") -> None:
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / ".runtime_protection_key").write_text(key.hex(), encoding="utf-8")
    issued_at = "2026-05-29T00:00:00+00:00"
    repo = str(root.resolve())
    payload = f"{int(version)}|{issued_at}|{issued_by}|{repo}".encode()
    sig = hmac.new(key, payload, hashlib.sha256).hexdigest()
    doc = {"version": version, "issued_at": issued_at, "issued_by": issued_by, "repo": repo, "signature": sig}
    (root / "runtime" / ".runtime_protection_disabled").write_text(json.dumps(doc), encoding="utf-8")


def test_no_flag_is_not_disabled(tmp_path):
    assert runtime_protection_disabled(tmp_path) is False


def test_unsigned_plaintext_flag_is_rejected_B9(tmp_path):
    # The exact B9 repro: a plain unsigned file.
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runtime" / ".runtime_protection_disabled").write_text(
        "not json, not signed, planted by red", encoding="utf-8"
    )
    assert runtime_protection_disabled(tmp_path) is False


def test_unsigned_json_flag_is_rejected_B9(tmp_path):
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runtime" / ".runtime_protection_disabled").write_text(
        json.dumps({"version": 1, "issued_at": "x", "issued_by": "red", "repo": str(tmp_path.resolve())}),
        encoding="utf-8",
    )
    assert runtime_protection_disabled(tmp_path) is False


def test_flag_signed_with_wrong_key_is_rejected(tmp_path):
    _write_signed_flag(tmp_path, key=hashlib.sha256(b"real").digest())
    # Overwrite the key with a different one so the stored signature no longer verifies.
    (tmp_path / "runtime" / ".runtime_protection_key").write_text(
        hashlib.sha256(b"attacker").digest().hex(), encoding="utf-8"
    )
    assert runtime_protection_disabled(tmp_path) is False


def test_properly_signed_flag_is_honored(tmp_path):
    _write_signed_flag(tmp_path, key=hashlib.sha256(b"real-install-key").digest())
    assert runtime_protection_disabled(tmp_path) is True
