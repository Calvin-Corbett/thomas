from __future__ import annotations

from pathlib import Path

import scripts.breakglass_auth as mod


def test_authorize_breakglass_reports_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(mod.os, "name", "posix")

    result = mod.authorize_breakglass(
        purpose="test",
        agent="Codex",
        ticket="OPS-1",
        reason="test reason long enough",
        skip_hooks=["hook-a"],
    )

    assert result.ok is False
    assert result.method == "unsupported-platform"


def test_authorize_breakglass_requires_opt_in(monkeypatch) -> None:
    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod, "_human_breakglass_enabled", lambda: False)

    result = mod.authorize_breakglass(
        purpose="test",
        agent="Codex",
        ticket="OPS-1A",
        reason="test reason long enough",
        skip_hooks=["hook-a"],
    )

    assert result.ok is False
    assert result.method == "disabled-by-preference"
    assert "Protected Override Approval" in result.message


def test_authorize_breakglass_uses_windows_prompt(monkeypatch) -> None:
    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod, "_human_breakglass_enabled", lambda: True)
    monkeypatch.setattr(mod, "_current_windows_sam_name", lambda: "WORKSTATION\\operator")
    monkeypatch.setattr(mod, "_show_breakglass_confirmation_dialog", lambda **_: True)
    monkeypatch.setattr(
        mod,
        "_run_windows_credential_prompt",
        lambda **_: mod.BreakglassAuthorization(
            ok=True,
            message="approved",
            actor="WORKSTATION\\operator",
            method=mod.WINDOWS_CREDENTIAL_METHOD,
            cancelled=False,
        ),
    )

    result = mod.authorize_breakglass(
        purpose="test",
        agent="Codex",
        ticket="OPS-2",
        reason="test reason long enough",
        skip_hooks=["hook-a", "hook-b"],
    )

    assert result.ok is True
    assert result.actor == "WORKSTATION\\operator"
    assert result.method == mod.WINDOWS_CREDENTIAL_METHOD


def test_build_windows_prompt_copy_explains_current_user_sign_in() -> None:
    title, instruction, content = mod._build_windows_confirmation_copy(
        purpose="commit protected governance changes",
        agent="Codex",
        ticket="OPS-42",
        reason="Need a human-authenticated protected-file override for the governance patch.",
        skip_hooks=["thomas-protected-files-gate", "thomas-active-folder-guard"],
        current_user="WORKSTATION\\operator",
    )
    caption, message = mod._build_windows_prompt_copy(current_user="WORKSTATION\\operator")

    assert title == mod.WINDOWS_CONFIRMATION_CAPTION
    assert instruction == "Approve protected Thomas change?"
    assert "Account: WORKSTATION\\operator" in content
    assert "Requested by: Codex" in content
    assert "Continue to open the Windows sign-in prompt." in content
    assert caption == mod.WINDOWS_CREDENTIAL_CAPTION
    assert "Account: WORKSTATION\\operator" in message
    assert "PIN, password, or Windows Hello" in message
    assert "thomas-protected-files-gate" in content


def test_authorize_breakglass_toggle_mints_single_use_receipt(monkeypatch) -> None:
    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod, "_current_windows_sam_name", lambda: "WORKSTATION\\operator")
    monkeypatch.setattr(mod, "_show_breakglass_confirmation_dialog", lambda **_: True)
    monkeypatch.setattr(
        mod,
        "_run_windows_credential_prompt",
        lambda **_: mod.BreakglassAuthorization(
            ok=True,
            message="approved",
            actor="WORKSTATION\\operator",
            method=mod.WINDOWS_CREDENTIAL_METHOD,
            cancelled=False,
        ),
    )

    result = mod.authorize_breakglass_toggle(enabled=True)

    assert result.ok is True
    assert result.receipt
    receipt = mod.consume_breakglass_toggle_receipt(result.receipt)
    assert receipt is not None
    assert receipt.actor == "WORKSTATION\\operator"
    assert receipt.method == mod.WINDOWS_CREDENTIAL_METHOD
    assert mod.consume_breakglass_toggle_receipt(result.receipt) is None


def test_authorize_breakglass_toggle_reports_cancelled_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod, "_current_windows_sam_name", lambda: "WORKSTATION\\operator")
    monkeypatch.setattr(mod, "_show_breakglass_confirmation_dialog", lambda **_: False)

    result = mod.authorize_breakglass_toggle(enabled=False)

    assert result.ok is False
    assert result.cancelled is True
    assert result.receipt is None


def test_authorize_scope_fallback_mints_single_use_receipt(tmp_path: Path, monkeypatch) -> None:
    receipts_dir = tmp_path / "receipts"
    monkeypatch.setattr(mod, "_scope_fallback_receipts_dir", lambda: receipts_dir)
    monkeypatch.setattr(
        mod,
        "authorize_breakglass",
        lambda **_: mod.BreakglassAuthorization(
            ok=True,
            message="approved",
            actor="WORKSTATION\\operator",
            method=mod.WINDOWS_CREDENTIAL_METHOD,
        ),
    )

    result = mod.authorize_scope_fallback(
        agent="codex",
        scopes=["src/app.py"],
        reason="user approved scoped fallback",
    )

    assert result.ok is True
    assert result.receipt
    receipt = mod.consume_scope_fallback_receipt(
        result.receipt,
        agent="codex",
        scopes=("src/app.py",),
        reason="user approved scoped fallback",
    )
    assert receipt is not None
    assert receipt.actor == "WORKSTATION\\operator"
    assert receipt.method == mod.WINDOWS_CREDENTIAL_METHOD
    assert mod.consume_scope_fallback_receipt(
        result.receipt,
        agent="codex",
        scopes=("src/app.py",),
        reason="user approved scoped fallback",
    ) is None


def test_consume_scope_fallback_receipt_rejects_mismatched_scope_or_reason(tmp_path: Path, monkeypatch) -> None:
    receipts_dir = tmp_path / "receipts"
    monkeypatch.setattr(mod, "_scope_fallback_receipts_dir", lambda: receipts_dir)
    receipt = mod._issue_scope_fallback_receipt(
        actor="WORKSTATION\\operator",
        method=mod.WINDOWS_CREDENTIAL_METHOD,
        agent="codex",
        scopes=("src/app.py",),
        reason="user approved scoped fallback",
    )

    assert (
        mod.consume_scope_fallback_receipt(
            receipt,
            agent="codex",
            scopes=("src/other.py",),
            reason="user approved scoped fallback",
        )
        is None
    )

    receipt = mod._issue_scope_fallback_receipt(
        actor="WORKSTATION\\operator",
        method=mod.WINDOWS_CREDENTIAL_METHOD,
        agent="codex",
        scopes=("src/app.py",),
        reason="user approved scoped fallback",
    )
    assert (
        mod.consume_scope_fallback_receipt(
            receipt,
            agent="codex",
            scopes=("src/app.py",),
            reason="different reason",
        )
        is None
    )
