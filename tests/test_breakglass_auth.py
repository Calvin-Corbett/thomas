from __future__ import annotations

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


def test_authorize_breakglass_uses_windows_prompt(monkeypatch) -> None:
    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod, "_current_windows_sam_name", lambda: "WORKSTATION\\corbe")
    monkeypatch.setattr(
        mod,
        "_run_windows_credential_prompt",
        lambda **_: mod.BreakglassAuthorization(
            ok=True,
            message="approved",
            actor="WORKSTATION\\corbe",
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
    assert result.actor == "WORKSTATION\\corbe"
    assert result.method == mod.WINDOWS_CREDENTIAL_METHOD


def test_build_windows_prompt_copy_explains_current_user_sign_in() -> None:
    caption, message = mod._build_windows_prompt_copy(
        purpose="commit protected governance changes",
        agent="Codex",
        ticket="OPS-42",
        reason="Need a human-authenticated protected-file override for the governance patch.",
        skip_hooks=["thomas-protected-files-gate", "thomas-active-folder-guard"],
        current_user="WORKSTATION\\corbe",
    )

    assert caption == mod.WINDOWS_CREDENTIAL_CAPTION
    assert "Windows account: WORKSTATION\\corbe" in message
    assert "PIN, password, or Windows Hello" in message
    assert "thomas-protected-files-gate" in message
