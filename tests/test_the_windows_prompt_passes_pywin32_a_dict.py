"""The Windows authorization prompt checks the password (2026-09-22).

History: on 2026-09-07 ``WindowsAuthGate._show_windows_dialog`` died with
``TypeError: CREDUI_INFO must be a dict`` before any prompt appeared (this file's
name is from that fix). Once it did appear, it was ``CredUIPromptForCredentials``
with GENERIC credentials, and the gate treated OK as approval without checking
what was typed. Any password, or none, approved a protected write. You were shown
that box on 2026-09-22 for a self-fix Thomas was attempting.

The gate now uses ``verified_sign_in``: Windows' own sign-in (PIN or password),
whose answer Windows checks. The verifier is stood in for here so the test runs
on every platform, and so a wrong password can be simulated.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from scripts import breakglass_auth

from thomas.tools import windows_auth


def _install_verifier(monkeypatch, *, ok: bool, calls: list, raises: Exception | None = None) -> None:
    def prompt(*, prompt_caption: str, prompt_message: str):
        calls.append({"caption": prompt_caption, "message": prompt_message})
        if raises is not None:
            raise raises
        return SimpleNamespace(ok=ok, message="validated" if ok else "LogonUserW failed: wrong password")

    monkeypatch.setattr(breakglass_auth, "_run_windows_credential_prompt", prompt)
    monkeypatch.setattr(windows_auth.platform, "system", lambda: "Windows")


def test_a_verified_sign_in_authorizes_and_says_what_it_is_for(monkeypatch) -> None:
    calls: list = []
    _install_verifier(monkeypatch, ok=True, calls=calls)
    gate = windows_auth.WindowsAuthGate()

    assert gate.request_authorization("write thomas/server/web/js/browser_shell.js", "self-edit") is True
    assert len(calls) == 1
    assert "browser_shell.js" in calls[0]["message"] and "self-edit" in calls[0]["message"]
    assert calls[0]["caption"] == "Thomas", "every Thomas approval is the one prompt, captioned Thomas"
    assert gate.session_summary()["active"] is True


def test_a_wrong_password_is_a_denial(monkeypatch) -> None:
    """The box on 2026-09-22 would have said yes here. Windows now says no."""
    calls: list = []
    _install_verifier(monkeypatch, ok=False, calls=calls)
    gate = windows_auth.WindowsAuthGate()

    assert gate.request_authorization("write thomas/core/capture_context.py", "self-fix") is False
    assert gate.session_summary() == {"active": False, "actions_approved": []}


def test_a_dialog_failure_is_a_denial_not_a_crash(monkeypatch) -> None:
    """Whatever the prompt raises, the gate answers False; a crash in the prompt
    must not escape into the tool that asked."""
    _install_verifier(monkeypatch, ok=True, calls=[], raises=OSError("CredUI unavailable"))
    assert windows_auth.WindowsAuthGate().request_authorization("write a file", "why") is False


def test_the_unchecked_box_is_gone() -> None:
    src = inspect.getsource(windows_auth)
    assert "CredUIPromptForCredentials(" not in src, "the box that trusted OK is back"
    # verified_sign_in asks through sign_in_answer (2026-10-09), which tells Cancel from a sign-in not accepted.
    assert "sign_in_answer(" in inspect.getsource(windows_auth.verified_sign_in)
    assert "_run_windows_credential_prompt" in inspect.getsource(windows_auth.sign_in_answer)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
