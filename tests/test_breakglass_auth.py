from __future__ import annotations

import scripts.breakglass_auth as mod
from scripts.breakglass_context import build_commit_blocker_context


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
    monkeypatch.setattr(mod, "_current_windows_sam_name", lambda: "WORKSTATION\\corbe")
    monkeypatch.setattr(mod, "_show_breakglass_confirmation_dialog", lambda **_: "approve")
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


def test_breakglass_decision_copy_uses_commit_blocker_context() -> None:
    context = build_commit_blocker_context(
        "Thomas Merge Readiness............................Failed\n"
        "- uncommitted change budget exceeded: 1548 changed lines exceeds max_uncommitted_changed_lines=800\n",
        ai_recommendation="This is a large commit, but the changed files are related. I think it is okay to continue after reviewing the file list.",
    )

    title, instruction, content, approve_label, cancel_label, resolution_label, resolution_prompt = (
        mod._build_breakglass_decision_copy(
            purpose="commit without a successful local pre-commit run",
            agent="Codex",
            ticket="OPS-100",
            reason="User requested checkpoint.",
            skip_hooks=["all local pre-commit hooks"],
            current_user="WORKSTATION\\corbe",
            context=context,
        )
    )

    assert title == "Thomas commit blocker"
    assert instruction == "Thomas needs your decision before breakglass."
    assert "1548 changed lines exceeds max_uncommitted_changed_lines=800" in content
    assert "okay to continue after reviewing" in content
    assert "What happened:" in content
    assert "Commit issues:" in content
    assert "Choose" not in content
    assert approve_label == "Authorize recommended commit"
    assert cancel_label == "Back out and talk to Thomas"
    assert resolution_label == ""
    assert resolution_prompt == ""


def test_authorize_breakglass_can_request_recommended_action(monkeypatch) -> None:
    monkeypatch.setattr(mod.os, "name", "nt")
    monkeypatch.setattr(mod, "_human_breakglass_enabled", lambda: True)
    monkeypatch.setattr(mod, "_current_windows_sam_name", lambda: "WORKSTATION\\corbe")
    monkeypatch.setattr(mod, "_show_breakglass_confirmation_dialog", lambda **_: "action")

    context = build_commit_blocker_context(
        "Thomas Merge Readiness............................Failed\n"
        "- uncommitted change budget exceeded: 1548 changed lines exceeds max_uncommitted_changed_lines=800\n",
        ai_guidance_json=(
            '{"recommendation":"Split this into smaller commits first.",'
            '"resolution_label":"Split commit",'
            '"resolution_prompt":"Split this blocked commit into smaller commits, then retry."}'
        ),
    )

    result = mod.authorize_breakglass(
        purpose="commit without a successful local pre-commit run",
        agent="Codex",
        ticket="OPS-100",
        reason="User requested checkpoint.",
        skip_hooks=["all local pre-commit hooks"],
        context=context,
    )

    assert result.ok is False
    assert result.cancelled is True
    assert result.action_requested is True
    assert "Split this blocked commit" in str(result.action_prompt)


def test_breakglass_dialog_geometry_scales_with_monitor_size() -> None:
    width, height, left, top = mod._dialog_geometry(2194, 1234)

    assert 980 <= width <= 1040
    assert 640 <= height <= 700
    assert left > 0
    assert top > 0


def test_breakglass_button_width_handles_long_action_labels() -> None:
    assert 14 <= mod._button_width_chars("Authorize and open Windows sign-in") <= 24
    assert 14 <= mod._button_width_chars("Back out and talk to Thomas") <= 24


def test_build_windows_prompt_copy_explains_current_user_sign_in() -> None:
    title, instruction, content = mod._build_windows_confirmation_copy(
        purpose="commit protected governance changes",
        agent="Codex",
        ticket="OPS-42",
        reason="Need a human-authenticated protected-file override for the governance patch.",
        skip_hooks=["thomas-protected-files-gate", "thomas-active-folder-guard"],
        current_user="WORKSTATION\\corbe",
    )
    caption, message = mod._build_windows_prompt_copy(current_user="WORKSTATION\\corbe")

    assert title == mod.WINDOWS_CONFIRMATION_CAPTION
    assert instruction == "Approve protected Thomas change?"
    assert "Account: WORKSTATION\\corbe" in content
    assert "Requested by: Codex" in content
    assert "Continue to open the Windows sign-in prompt." in content
    assert caption == mod.WINDOWS_CREDENTIAL_CAPTION
    assert "Account: WORKSTATION\\corbe" in message
    assert "PIN, password, or Windows Hello" in message
    assert "thomas-protected-files-gate" in content
