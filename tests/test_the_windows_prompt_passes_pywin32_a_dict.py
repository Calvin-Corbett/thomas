"""The Windows authorization prompt hands pywin32 what it asks for (2026-09-07).

An isolated self-edit run on 2026-09-07 (fc_20260907T053138_2b7f40) had every
write inside its candidate copy refused by runtime protection, reached for the
guarded write path, and that path died before any prompt appeared::

    TypeError: CREDUI_INFO must be a dict

``WindowsAuthGate._show_windows_dialog`` passed the message text as the seventh
argument of ``win32cred.CredUIPromptForCredentials``; pywin32 wants the
``CREDUI_INFO`` structure there, as a dict with ``MessageText`` and
``CaptionText``. The gate caught only ``OSError`` and ``pywintypes.error``, so
the ``TypeError`` escaped the gate and every native authorization the runtime
ever asked for on Windows failed before the user saw a dialog.

pywin32 itself is stood in for here, with the exact refusal the real module
gives a string, so the test runs on every platform and fails for the same
reason the run did.
"""

from __future__ import annotations

import sys
import types

import pytest

from thomas.tools import windows_auth


class _PyWinTypesError(Exception):
    pass


def _install_fake_pywin32(monkeypatch, *, result: int, calls: list) -> None:
    def prompt(target, auth_error, username, password, save, flags, ui_info):
        # pywin32's own check, verbatim in effect: the seventh argument is CREDUI_INFO.
        if not isinstance(ui_info, dict):
            raise TypeError("CREDUI_INFO must be a dict")
        calls.append({"target": target, "flags": flags, "ui_info": ui_info})
        return result, username, "", False

    win32cred = types.ModuleType("win32cred")
    win32cred.CredUIPromptForCredentials = prompt
    win32cred.CREDUI_FLAGS_GENERIC_CREDENTIALS = 0x40000
    win32cred.CREDUI_FLAGS_EXPECT_CONFIRMATION = 0x20000
    win32cred.CREDUI_FLAGS_COMPLETE_USERNAME = 0x800
    win32api = types.ModuleType("win32api")
    win32api.GetUserName = lambda: "corbe"
    pywintypes = types.ModuleType("pywintypes")
    pywintypes.error = _PyWinTypesError
    for name, module in (("win32cred", win32cred), ("win32api", win32api), ("pywintypes", pywintypes)):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(windows_auth.platform, "system", lambda: "Windows")


def test_the_prompt_receives_the_credui_info_dict_and_a_confirmed_prompt_authorizes(monkeypatch) -> None:
    calls: list = []
    _install_fake_pywin32(monkeypatch, result=0, calls=calls)
    gate = windows_auth.WindowsAuthGate()

    assert gate.request_authorization("write thomas/server/web/js/browser_shell.js", "self-edit") is True

    assert len(calls) == 1
    info = calls[0]["ui_info"]
    assert "browser_shell.js" in info["MessageText"] and "self-edit" in info["MessageText"]
    assert info["CaptionText"]
    assert gate.session_summary()["active"] is True


def test_a_cancelled_prompt_denies_and_leaves_no_session(monkeypatch) -> None:
    calls: list = []
    _install_fake_pywin32(monkeypatch, result=1223, calls=calls)  # ERROR_CANCELLED
    gate = windows_auth.WindowsAuthGate()

    assert gate.request_authorization("delete output", "destructive") is False
    assert len(calls) == 1
    assert gate.session_summary() == {"active": False, "actions_approved": []}


def test_a_dialog_failure_is_a_denial_not_a_crash(monkeypatch) -> None:
    """Whatever pywin32 raises, the gate answers False; a crash in the prompt must
    not escape into the tool that asked, which is what the run saw."""
    _install_fake_pywin32(monkeypatch, result=0, calls=[])

    def broken(*args):
        raise TypeError("CREDUI_INFO must be a dict")

    sys.modules["win32cred"].CredUIPromptForCredentials = broken
    gate = windows_auth.WindowsAuthGate()
    assert gate.request_authorization("write a file", "why") is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
