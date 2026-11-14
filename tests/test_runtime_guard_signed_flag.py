"""Regressions for the gate-side signed-flag validator (praxis-unbypassable B9).

The runtime-protection disable flag must only be honored when it is HMAC-signed
with the per-install key. An unsigned flag planted by an agent (the original B9
bypass) must NOT disable the gates.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json

from scripts.forge.gates._runtime_guard import runtime_protection_disabled


def _write_signed_flag(
    root, *, key: bytes, version=1, issued_by="tester", issued_at=None, extra=None
) -> None:
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / ".runtime_protection_key").write_text(key.hex(), encoding="utf-8")
    # Default to NOW: break-glass is a window, and a flag is only honoured while
    # that window is open, so a fixed timestamp would age out of every test.
    if issued_at is None:
        issued_at = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "+00:00")
    repo = str(root.resolve())
    payload = f"{int(version)}|{issued_at}|{issued_by}|{repo}".encode()
    sig = hmac.new(key, payload, hashlib.sha256).hexdigest()
    doc = {"version": version, "issued_at": issued_at, "issued_by": issued_by, "repo": repo, "signature": sig}
    if extra:
        doc.update(extra)
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


def _hours_ago(hours: float) -> str:
    return (dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)).isoformat()


def test_a_stale_breakglass_flag_stops_disabling_protection(tmp_path):
    """Break-glass is a window, not a state.

    Found live on 2026-09-08: the flag on the owner's repo was issued
    2026-09-06T16:30Z and was still disabling FOURTEEN gates two days later --
    protected_files_gate, the deletion guard, merge_resurrection_gate, the
    worktree guards. Every one printed "PASS (runtime protection disabled by
    human)" and exited 0, and nothing at session start said so. That is the
    July disease with a different cause: the gates were not enforcing and the
    instrument that says so was silent.

    A signature proves the human authorised it. It does not prove they meant it
    to still be true days later.
    """
    key = hashlib.sha256(b"real-install-key").digest()
    _write_signed_flag(tmp_path, key=key, issued_at=_hours_ago(48))
    assert runtime_protection_disabled(tmp_path) is False


def test_a_fresh_breakglass_flag_is_still_honoured(tmp_path):
    """The capability itself is untouched: inside the window it still works."""
    key = hashlib.sha256(b"real-install-key").digest()
    _write_signed_flag(tmp_path, key=key, issued_at=_hours_ago(0.5))
    assert runtime_protection_disabled(tmp_path) is True


def test_an_expiry_in_the_flag_can_shorten_the_window(tmp_path):
    key = hashlib.sha256(b"real-install-key").digest()
    _write_signed_flag(
        tmp_path, key=key, issued_at=_hours_ago(0.5),
        extra={"expires_at": _hours_ago(0.1)},
    )
    assert runtime_protection_disabled(tmp_path) is False


def test_an_expiry_in_the_flag_cannot_extend_the_window(tmp_path):
    """expires_at is OUTSIDE the signed payload, so it may only ever restrict.

    Otherwise anyone who could edit the file could grant themselves a decade of
    disabled gates without re-signing.
    """
    key = hashlib.sha256(b"real-install-key").digest()
    far_future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=3650)).isoformat()
    _write_signed_flag(
        tmp_path, key=key, issued_at=_hours_ago(48), extra={"expires_at": far_future},
    )
    assert runtime_protection_disabled(tmp_path) is False


def test_an_unparseable_issue_time_fails_closed(tmp_path):
    key = hashlib.sha256(b"real-install-key").digest()
    _write_signed_flag(tmp_path, key=key, issued_at="not-a-timestamp")
    assert runtime_protection_disabled(tmp_path) is False


def test_the_two_implementations_still_agree(tmp_path):
    """_runtime_guard (stdlib-only, gate side) and filesystem.py MUST stay in sync."""
    from thomas.tools.filesystem import _is_runtime_protection_disabled

    key = hashlib.sha256(b"real-install-key").digest()
    for issued_at in (_hours_ago(0.5), _hours_ago(48), "not-a-timestamp"):
        _write_signed_flag(tmp_path, key=key, issued_at=issued_at)
        assert runtime_protection_disabled(tmp_path) is _is_runtime_protection_disabled(tmp_path), (
            f"the two validators disagree for issued_at={issued_at}"
        )
