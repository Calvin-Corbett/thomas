"""A Windows sign-in counts only for the account Thomas runs as (Part 4 hardening of spec section 8.4).

No prompt is shown: the live test reads this process's own token, the rest use stand-in SIDs.
"""

from __future__ import annotations

import ast
import ctypes
import json
import sys
from pathlib import Path

import pytest
from scripts import breakglass_account as ba

REPO = Path(__file__).resolve().parents[1]


def test_the_same_account_counts_and_another_never_does() -> None:
    mine = "S-1-5-21-1-2-3-1001"
    assert ba.same_account(object(), "ok", sid_of=lambda _t: mine, mine=lambda: mine) == (True, "ok")
    ok, why = ba.same_account(object(), "ok", sid_of=lambda _t: "S-1-5-21-1-2-3-1002", mine=lambda: mine)
    assert not ok and "another account" in why


def test_an_account_that_cannot_be_read_is_a_no() -> None:
    def unreadable(_token: object) -> str:
        raise OSError("GetTokenInformation failed (6)")

    ok, why = ba.same_account(object(), "ok", sid_of=unreadable, mine=lambda: "S-1-5-21-1")
    assert not ok and "could not be read" in why


@pytest.mark.skipif(sys.platform != "win32", reason="reads a Windows token")
def test_this_process_own_token_is_its_own_account() -> None:
    from ctypes import wintypes

    advapi, kernel = ba._libs()
    token = wintypes.HANDLE()
    assert advapi.OpenProcessToken(kernel.GetCurrentProcess(), ba.TOKEN_QUERY, ctypes.byref(token))
    assert ba.same_account(token, "ok", close=True) == (True, "ok")
    assert ba.own_sid().startswith("S-1-5-")


def test_both_ways_breakglass_auth_validates_ask_whose_sign_in_it_was() -> None:
    tree = ast.parse((REPO / "scripts" / "breakglass_auth.py").read_text(encoding="utf-8"))
    for name in ("_validate_with_lsa", "_validate_with_logon_user"):
        found = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        assert "same_account" in {ast.unparse(n.func) for n in ast.walk(found) if isinstance(n, ast.Call)}, name


def test_breakglass_auth_stays_within_its_frozen_size() -> None:
    baseline = json.loads((REPO / "docs" / "monolith_guard_baseline.json").read_text(encoding="utf-8"))
    limit = next(v for k, v in baseline.items() if isinstance(v, dict) and "scripts/breakglass_auth.py" in v)
    lines = len((REPO / "scripts" / "breakglass_auth.py").read_text(encoding="utf-8").splitlines())
    assert lines <= limit["scripts/breakglass_auth.py"]["max_lines"]
