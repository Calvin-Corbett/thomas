"""Tests for the native-auth override extension to _is_protected_runtime_path.

Part of gate-architecture-2026-05-26 (PROBLEM.md "Proposed implementation"
step 6 — extend request_native_authorization callers to cover protected-file
delete/edit operations).

Verifies:
- Default behavior unchanged when the kwarg isn't passed (regression guard).
- With allow_native_auth_override=True AND auth approved: write allowed.
- With allow_native_auth_override=True AND auth denied: write refused.
- Auth module unavailable: refusal honored (fail-closed).
- Auth function raises: refusal honored (fail-closed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools.filesystem import _is_protected_runtime_path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A fake sandbox root mimicking Thomas's protected layout."""
    (tmp_path / "thomas" / "tools").mkdir(parents=True)
    (tmp_path / "thomas" / "agent").mkdir(parents=True)
    (tmp_path / "agent_safety.toml").write_text("# stub\n")
    (tmp_path / "src").mkdir()  # unprotected sibling for control tests
    return tmp_path


def _protected_dir_target(sandbox: Path) -> Path:
    return sandbox / "thomas" / "tools" / "evil.py"


def _protected_file_target(sandbox: Path) -> Path:
    return sandbox / "agent_safety.toml"


def _unprotected_target(sandbox: Path) -> Path:
    return sandbox / "src" / "ok.py"


# ---------------------------------------------------------------------------
# Default behavior (regression guard — must stay refuse-only)
# ---------------------------------------------------------------------------


def test_unprotected_path_returns_none(sandbox: Path) -> None:
    assert _is_protected_runtime_path(sandbox, _unprotected_target(sandbox)) is None


def test_protected_dir_refused_by_default(sandbox: Path) -> None:
    reason = _is_protected_runtime_path(sandbox, _protected_dir_target(sandbox))
    assert reason is not None
    assert "protected runtime" in reason
    assert "thomas/tools" in reason


def test_protected_file_refused_by_default(sandbox: Path) -> None:
    reason = _is_protected_runtime_path(sandbox, _protected_file_target(sandbox))
    assert reason is not None
    assert "protected policy file" in reason
    assert "agent_safety.toml" in reason


# ---------------------------------------------------------------------------
# Native-auth override (architecture extension)
# ---------------------------------------------------------------------------


def test_native_auth_override_approved_allows_write(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When override kwarg is True AND native auth approves, write is allowed."""
    calls: list[tuple[str, str]] = []

    def _fake_auth(action_description: str, reason: str) -> bool:
        calls.append((action_description, reason))
        return True

    monkeypatch.setattr("thomas.tools.native_auth.request_native_authorization", _fake_auth)

    result = _is_protected_runtime_path(
        sandbox,
        _protected_dir_target(sandbox),
        allow_native_auth_override=True,
        action_description="Test write to protected path",
    )
    assert result is None  # write allowed
    assert len(calls) == 1
    assert calls[0][0] == "Test write to protected path"
    assert "protected runtime" in calls[0][1]


def test_native_auth_override_denied_refuses_write(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When override kwarg is True but native auth denies, write is refused."""
    monkeypatch.setattr(
        "thomas.tools.native_auth.request_native_authorization",
        lambda action, reason: False,
    )

    result = _is_protected_runtime_path(
        sandbox,
        _protected_dir_target(sandbox),
        allow_native_auth_override=True,
    )
    assert result is not None
    assert "protected runtime" in result


def test_native_auth_override_default_action_description(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If no action_description is passed, a sensible default is used."""
    captured: dict[str, str] = {}

    def _fake_auth(action_description: str, reason: str) -> bool:
        captured["action"] = action_description
        return True

    monkeypatch.setattr("thomas.tools.native_auth.request_native_authorization", _fake_auth)

    _is_protected_runtime_path(
        sandbox,
        _protected_dir_target(sandbox),
        allow_native_auth_override=True,
    )
    assert "thomas/tools/evil.py" in captured["action"]


# ---------------------------------------------------------------------------
# Fail-closed behaviors (defense in depth)
# ---------------------------------------------------------------------------


def test_native_auth_module_unavailable_honors_refusal(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the native_auth module can't be imported, refusal is honored."""
    import builtins

    real_import = builtins.__import__

    def _failing_import(name: str, *args, **kwargs):
        if name == "thomas.tools.native_auth":
            raise ImportError("simulated missing native_auth")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _failing_import)

    result = _is_protected_runtime_path(
        sandbox,
        _protected_dir_target(sandbox),
        allow_native_auth_override=True,
    )
    assert result is not None  # refused (fail-closed)


def test_native_auth_raises_honors_refusal(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If native_auth raises unexpectedly, refusal is honored."""

    def _raising(action: str, reason: str) -> bool:
        raise RuntimeError("simulated auth failure")

    monkeypatch.setattr("thomas.tools.native_auth.request_native_authorization", _raising)

    result = _is_protected_runtime_path(
        sandbox,
        _protected_file_target(sandbox),
        allow_native_auth_override=True,
    )
    assert result is not None  # refused (fail-closed)


def test_runtime_protection_disabled_flag_still_works(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag-file bypass still wins over per-call check — but only if the
    flag is properly signed (post-2026-05-27 fix).  An unsigned/empty flag
    is treated as absent (see test_filesystem_protection_adversarial.py)."""
    import hmac as _hmac
    import json as _json
    from hashlib import sha256 as _sha256

    from thomas.tools.filesystem import _runtime_signing_payload

    # Plant a valid signing key and a flag signed against it.
    key = bytes(range(32))
    (sandbox / "runtime").mkdir(parents=True, exist_ok=True)
    (sandbox / "runtime" / ".runtime_protection_key").write_text(key.hex() + "\n")

    issued_at = "2026-05-27T12:00:00Z"
    issued_by = "calvin"
    repo = str(sandbox.resolve())
    sig = _hmac.new(
        key,
        _runtime_signing_payload(1, issued_at, issued_by, repo),
        _sha256,
    ).hexdigest()
    (sandbox / "runtime" / ".runtime_protection_disabled").write_text(
        _json.dumps(
            {
                "version": 1,
                "issued_at": issued_at,
                "issued_by": issued_by,
                "repo": repo,
                "signature": sig,
            }
        )
    )

    # Even WITHOUT the kwarg, the signed-flag bypass returns None.
    assert _is_protected_runtime_path(sandbox, _protected_dir_target(sandbox)) is None
    # And WITH the kwarg (no auth needed since flag wins first).
    assert (
        _is_protected_runtime_path(
            sandbox,
            _protected_dir_target(sandbox),
            allow_native_auth_override=True,
        )
        is None
    )
