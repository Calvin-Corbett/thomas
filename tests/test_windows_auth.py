from __future__ import annotations

from unittest.mock import patch

import thomas.tools.windows_auth as windows_auth
from thomas.tools.windows_auth import WindowsAuthGate


def test_prompt_content_is_not_classified_or_pre_rejected() -> None:
    assert not hasattr(windows_auth, "check_prompt_suspicious")
    assert not hasattr(windows_auth, "gate_suspicious_prompt")
    assert not hasattr(windows_auth, "_SUSPICIOUS_PATTERNS")


def test_structured_high_risk_action_still_uses_native_authorization() -> None:
    gate = WindowsAuthGate()
    with (
        patch("thomas.tools.windows_auth.platform.system", return_value="Windows"),
        patch.object(gate, "_show_windows_dialog", return_value=True) as show,
    ):
        approved = gate.request_authorization(
            "Delete selected export",
            "This concrete structured action requires approval.",
        )

    assert approved is True
    show.assert_called_once_with(
        "Delete selected export",
        "This concrete structured action requires approval.",
    )


def test_non_windows_structured_authorization_fails_closed() -> None:
    gate = WindowsAuthGate()
    with patch("thomas.tools.windows_auth.platform.system", return_value="Linux"):
        assert gate.request_authorization("Delete selected export") is False
