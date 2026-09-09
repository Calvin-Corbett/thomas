"""Regressions for success-marker authentication (praxis-unbypassable B1).

The local commit choke point (prepare-commit-msg → commit_breakglass_guard)
must not accept a forged success marker.  A forged marker is one written by an
agent that ran no gates: it can match the staged tree/HEAD/age but cannot carry
a valid HMAC signature because the signing key lives outside the repo worktree.

These tests inject the key + marker paths via monkeypatch — deliberately NOT
via environment, since an env override would itself be a hook-time bypass
(found by codex's re-attack 2026-05-29).
"""

from __future__ import annotations

import argparse
import json
import secrets
from datetime import datetime, timezone

from scripts import commit_breakglass_guard as cbg

_TREE = "1111111111111111111111111111111111111111"
_HEAD = "2222222222222222222222222222222222222222"


def _wire(monkeypatch, tmp_path):
    keyf = tmp_path / "marker.key"
    markerf = tmp_path / "marker.json"
    monkeypatch.setattr(cbg, "_marker_key_path", lambda: keyf)
    monkeypatch.setattr(cbg, "_success_marker_path", lambda: markerf)
    monkeypatch.setattr(cbg, "_current_index_tree", lambda: _TREE)
    monkeypatch.setattr(cbg, "_current_head", lambda: _HEAD)
    monkeypatch.setattr(cbg, "_current_branch", lambda: "feature")
    monkeypatch.setattr(cbg, "_resolve_agent", lambda: "tester")
    monkeypatch.setattr(cbg, "_staged_files", lambda: [])
    return keyf, markerf


def _fresh_payload(**overrides):
    payload = {
        "version": cbg.MARKER_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "agent": "attacker",
        "branch": "feature",
        "head": _HEAD,
        "index_tree": _TREE,
        "staged_files": [],
    }
    payload.update(overrides)
    return payload


def test_unsigned_forged_marker_is_rejected(monkeypatch, tmp_path):
    """The original B1 repro: write a plain JSON marker, no key, no signature."""
    _keyf, markerf = _wire(monkeypatch, tmp_path)
    markerf.write_text(json.dumps(_fresh_payload()), encoding="utf-8")
    ok, detail = cbg.validate_success_marker()
    assert ok is False
    assert "signature" in detail or "key" in detail


def test_marker_signed_with_wrong_key_is_rejected(monkeypatch, tmp_path):
    """Attacker forges a signature with a key they control — must be rejected."""
    keyf, markerf = _wire(monkeypatch, tmp_path)
    keyf.write_text(secrets.token_bytes(32).hex(), encoding="utf-8")  # the real key
    attacker_key = secrets.token_bytes(32)
    payload = _fresh_payload()
    payload["signature"] = cbg._marker_signature(payload, attacker_key)
    markerf.write_text(json.dumps(payload), encoding="utf-8")
    ok, detail = cbg.validate_success_marker()
    assert ok is False
    assert "signature" in detail


def test_legitimate_signed_marker_is_accepted(monkeypatch, tmp_path):
    """The real flow: pre-commit-success mints the key + signs; verify passes."""
    _keyf, _markerf = _wire(monkeypatch, tmp_path)
    cbg.cmd_pre_commit_success(argparse.Namespace())
    ok, detail = cbg.validate_success_marker()
    assert ok is True, detail


def test_no_environment_override_for_key_path(monkeypatch, tmp_path):
    """The key path must ignore the (removed) THOMAS_PRAXIS_MARKER_KEY_FILE env."""
    attacker = tmp_path / "attacker.key"
    monkeypatch.setenv("THOMAS_PRAXIS_MARKER_KEY_FILE", str(attacker))
    resolved = cbg._marker_key_path()
    assert resolved != attacker
    assert str(tmp_path) not in str(resolved)
