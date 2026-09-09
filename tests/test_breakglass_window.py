"""Tests for the breakglass approval-window validator (scripts/breakglass_window_core).

These pin the security-relevant behavior: a window is honored ONLY when the
signature verifies, the actor matches, the repo matches, and it has not expired.
Everything is stdlib-only and platform-independent (no Windows calls), so the
core can be trusted on CI as well as on the owner's machine.
"""

from __future__ import annotations

import json

import scripts.breakglass_window_core as bwc

ACTOR = "ACME\\owner"


def test_roundtrip_window_is_active(tmp_path):
    bwc.mint_window(tmp_path, ACTOR, 3)
    doc = bwc.active_window(tmp_path, ACTOR)
    assert doc is not None
    assert doc["actor"] == ACTOR
    assert doc["hours"] == 3


def test_actor_match_is_case_insensitive_but_distinct_users_rejected(tmp_path):
    bwc.mint_window(tmp_path, ACTOR, 3)
    # Same user, different case / spacing -> still valid.
    assert bwc.active_window(tmp_path, "acme\\owner") is not None
    # A different account cannot reuse the window.
    assert bwc.active_window(tmp_path, "ACME\\intruder") is None


def test_expired_window_is_rejected(tmp_path, monkeypatch):
    bwc.mint_window(tmp_path, ACTOR, 3)  # expires ~3h from now
    real_time = bwc.time.time()
    monkeypatch.setattr(bwc.time, "time", lambda: real_time + 4 * 3600)
    assert bwc.active_window(tmp_path, ACTOR) is None


def test_tampered_signature_is_rejected(tmp_path):
    bwc.mint_window(tmp_path, ACTOR, 3)
    token = tmp_path / bwc.TOKEN_REL
    doc = json.loads(token.read_text(encoding="utf-8"))
    # Flip the last hex char of the signature.
    sig = doc["signature"]
    doc["signature"] = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    token.write_text(json.dumps(doc), encoding="utf-8")
    assert bwc.active_window(tmp_path, ACTOR) is None


def test_extended_expiry_without_resign_is_rejected(tmp_path):
    """Hand-editing expires_at_epoch without the key must not extend the window."""
    bwc.mint_window(tmp_path, ACTOR, 1)
    token = tmp_path / bwc.TOKEN_REL
    doc = json.loads(token.read_text(encoding="utf-8"))
    doc["expires_at_epoch"] = int(doc["expires_at_epoch"]) + 10 * 3600
    token.write_text(json.dumps(doc), encoding="utf-8")
    assert bwc.active_window(tmp_path, ACTOR) is None


def test_repo_mismatch_is_rejected(tmp_path):
    bwc.mint_window(tmp_path, ACTOR, 3)
    token = tmp_path / bwc.TOKEN_REL
    doc = json.loads(token.read_text(encoding="utf-8"))
    doc["repo"] = doc["repo"] + "_elsewhere"
    token.write_text(json.dumps(doc), encoding="utf-8")
    assert bwc.active_window(tmp_path, ACTOR) is None


def test_missing_key_fails_closed(tmp_path):
    bwc.mint_window(tmp_path, ACTOR, 3)
    (tmp_path / bwc.KEY_REL).unlink()
    assert bwc.active_window(tmp_path, ACTOR) is None


def test_clear_window_removes_token_and_key(tmp_path):
    bwc.mint_window(tmp_path, ACTOR, 3)
    assert bwc.active_window(tmp_path, ACTOR) is not None
    assert bwc.clear_window(tmp_path) is True
    assert bwc.active_window(tmp_path, ACTOR) is None
    assert not (tmp_path / bwc.TOKEN_REL).exists()
    assert not (tmp_path / bwc.KEY_REL).exists()


def test_no_token_is_inactive(tmp_path):
    assert bwc.active_window(tmp_path, ACTOR) is None
    status = bwc.window_status(tmp_path, ACTOR)
    assert status["active"] is False
    assert status["token_present"] is False


def test_clamp_hours_bounds():
    assert bwc.clamp_hours(0) == bwc.DEFAULT_WINDOW_HOURS
    assert bwc.clamp_hours(-5) == bwc.DEFAULT_WINDOW_HOURS
    assert bwc.clamp_hours("nonsense") == bwc.DEFAULT_WINDOW_HOURS
    assert bwc.clamp_hours(1000) == bwc.MAX_WINDOW_HOURS
    assert bwc.clamp_hours(2) == 2.0


def test_window_files_are_protected_from_agent_writes():
    """Token + key must be in the hardcoded protected-file list so agent file
    tools refuse to write (forge) them -- same bar as runtime_protection. With
    shell.exec off by default + rules_of_road shell-write detection, this leaves
    an agent no path to forge a window."""
    from thomas.tools.filesystem import _HARDCODED_PROTECTED_FILES

    assert bwc.TOKEN_REL in _HARDCODED_PROTECTED_FILES
    assert bwc.KEY_REL in _HARDCODED_PROTECTED_FILES
