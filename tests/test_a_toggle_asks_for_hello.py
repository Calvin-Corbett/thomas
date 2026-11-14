"""Raising an agent's own limits needs a Windows Hello tap, not an OK box.

Owner direction, 2026-09-22: "agents should be able to trigger toggle changes.
agents cant change stuff that important if they try its password protected so
there is no worry." Checked, that premise held for Thomas's code, protected
files and safety settings (all Hello) -- and did NOT hold for the chat dials.
Autonomy, file access and internet reach were guarded by ``window.confirm()``,
a browser OK/Cancel box any automation can click through, and the server took
whatever level a request carried. An agent that set itself to "Anywhere on my
PC" could write to the owner's Documents with no password at all.

This makes the premise true, and puts the check where an agent cannot skip it:

* A request carrying an elevated level is honoured only after the owner
  approved that level at a native OS prompt. Without an approval it runs at the
  highest level that needs none -- degraded, never refused (Rule 0).
* Every approval is a FRESH prompt. The shared Windows auth gate caches a Hello
  approval for five minutes process-wide, so reusing it would let an agent ride
  the owner's last tap -- for an unrelated protected-file write -- and escalate
  without any prompt at all.
"""

from __future__ import annotations

import inspect

import pytest

from thomas.server import dial_elevation as de


@pytest.fixture(autouse=True)
def _no_grants():
    de.reset_grants()
    yield
    de.reset_grants()


def _approve_all(*_args, **_kwargs) -> bool:
    return True


def _deny_all(*_args, **_kwargs) -> bool:
    return False


def test_the_levels_that_need_a_tap_match_the_ones_the_menu_marks() -> None:
    """The server's list and the UI's `elevates` flags must agree."""
    assert [lvl for lvl in (1, 2, 3, 4, 5) if de.is_elevated("autonomy", lvl)] == [4, 5]
    assert [v for v in ("workspace", "project", "pc", "full") if de.is_elevated("file_access", v)] == ["pc", "full"]
    assert [v for v in ("fortress", "guarded", "open") if de.is_elevated("guardrails", v)] == ["open"]


def test_without_a_tap_an_elevated_request_runs_at_the_highest_safe_level() -> None:
    """Degraded, not refused: the work still happens."""
    assert de.cap("autonomy", 5) == 3
    assert de.cap("file_access", "pc") == "project"
    assert de.cap("guardrails", "open") == "guarded"


def test_asking_for_a_level_that_needs_no_tap_is_left_alone() -> None:
    assert de.cap("autonomy", 3) == 3
    assert de.cap("file_access", "project") == "project"


def test_after_the_owner_taps_the_level_is_honoured() -> None:
    assert de.approve("autonomy", 5, authorize=_approve_all) is True
    assert de.cap("autonomy", 5) == 5


def test_an_approval_is_a_ceiling_not_an_exact_match() -> None:
    """Approving Autopilot also covers Full autonomy below it."""
    de.approve("autonomy", 5, authorize=_approve_all)
    assert de.cap("autonomy", 4) == 4


def test_a_lower_approval_does_not_cover_a_higher_level() -> None:
    de.approve("file_access", "pc", authorize=_approve_all)
    assert de.cap("file_access", "full") == "project"


def test_a_declined_prompt_grants_nothing() -> None:
    assert de.approve("autonomy", 5, authorize=_deny_all) is False
    assert de.cap("autonomy", 5) == 3


def test_a_level_that_needs_no_tap_is_approved_without_prompting() -> None:
    """Never pop a password box for something that does not need one."""
    calls: list[str] = []

    def _record(action: str, reason: str) -> bool:
        calls.append(action)
        return True

    assert de.approve("autonomy", 3, authorize=_record) is True
    assert calls == []


def test_every_approval_asks_again() -> None:
    """No caching inside this module: two raises are two prompts."""
    calls: list[str] = []

    def _record(action: str, reason: str) -> bool:
        calls.append(action)
        return True

    de.approve("autonomy", 5, authorize=_record)
    de.reset_grants()
    de.approve("autonomy", 5, authorize=_record)
    assert len(calls) == 2


def test_the_real_prompt_is_the_standard_one_and_reuses_nothing() -> None:
    """The dials use Thomas's one standard prompt, called fresh.

    ``verified_sign_in`` is Windows' own sign-in, and Windows checks the answer.
    The shared gate (``get_auth_gate`` / ``WindowsAuthGate``) reuses a tap from
    the last five minutes, and ``authorize_breakglass`` honours an open
    break-glass window, so neither may stand between you and a raised limit.
    """
    import ast
    import textwrap

    fn = ast.parse(textwrap.dedent(inspect.getsource(de._fresh_native_prompt))).body[0]
    fn.body = fn.body[1:]  # drop the docstring: only code counts
    code = ast.unparse(fn)
    assert "verified_sign_in" in code
    for rejected in ("get_auth_gate", "WindowsAuthGate", "authorize_breakglass"):
        assert rejected not in code, f"elevation uses {rejected}, which can approve without asking you"


def test_the_verified_prompt_is_really_there_and_really_verifies() -> None:
    """The dependency is a private name in a protected script; pin that it
    exists and that it validates what was entered rather than trusting OK."""
    from scripts import breakglass_auth

    src = inspect.getsource(breakglass_auth._run_windows_credential_prompt)
    assert "_validate_with_lsa" in src and "_validate_with_logon_user" in src
    assert "active_window" not in src, "the prompt must not accept an open break-glass window"


def test_an_unknown_dial_or_value_is_never_treated_as_approved() -> None:
    assert de.approve("self_destruct", "yes", authorize=_approve_all) is False
    assert de.approve("autonomy", "not a level", authorize=_approve_all) is False


def test_an_unrecognised_value_is_left_for_the_run_to_default() -> None:
    """Replacing it could only move it, and possibly up. The run's own default
    for a value it cannot read is never an elevated level."""
    assert de.cap("autonomy", "not a level") == "not a level"


def test_aliases_are_read_the_way_the_run_reads_them() -> None:
    """A private list of spellings would call "read" unknown and could lift a
    read-only request to project access. The server's parsers decide."""
    assert de.cap("file_access", "read") == "read"
    assert de.cap("file_access", "home") == "project"  # "home" is the PC level
    assert de.cap("autonomy", "L5") == 3
    assert de.cap("autonomy", "autopilot") == 3
    assert de.cap("autonomy", 9) == 3  # the run clamps 9 to Autopilot


@pytest.mark.parametrize("sneaky", [4.0, 4.9, 5.0, 17.5])
def test_a_float_cannot_slip_past_to_build(sneaky: float) -> None:
    """Build reads autonomy with a bare int(), so 4.0 and 4.9 are Full autonomy
    there. Found by review: the check once read them as unknown and let them
    through untouched, which reached Build at level 4 with no prompt."""
    from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings

    capped = de.cap_payload({"message": "x", "autonomy_level": sneaky})
    assert ForgeCodeSettings.from_payload(capped).autonomy_level == 3


def test_an_approved_autopilot_reaches_build() -> None:
    """Build validated 1 through 4 while the menu offered 5, so an approved
    Autopilot turned every Build run into a settings error."""
    from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings

    de.approve("autonomy", 5, authorize=_approve_all)
    assert ForgeCodeSettings.from_payload(de.cap_payload({"message": "x", "autonomy_level": 5})).autonomy_level == 5


def test_a_request_body_is_capped_where_it_is_read() -> None:
    body = {"message": "hi", "autonomy_level": 5, "file_access": "pc", "thomas_guardrails": "open"}
    capped = de.cap_payload(body)
    assert (capped["autonomy_level"], capped["file_access"], capped["thomas_guardrails"]) == (3, "project", "guarded")
    assert body["autonomy_level"] == 5, "the caller's dict must not be mutated"
    assert "memory" not in de.cap_payload({"message": "hi"}), "a key not sent stays unsent"


def test_build_spells_guardrails_both_ways() -> None:
    assert de.cap_payload({"guardrails": "open"})["guardrails"] == "guarded"


def test_per_group_modes_cannot_open_the_side_door() -> None:
    """Explicit per-group modes override the preset, so a permissive group is
    "open" in all but name and needs the same tap."""
    body = {"thomas_guardrails": "guarded", "thomas_guardrail_modes": {"reach": "permissive", "inspector": "strict"}}
    assert de.cap_payload(body)["thomas_guardrail_modes"] == {"reach": "standard", "inspector": "strict"}
    de.approve("guardrails", "open", authorize=_approve_all)
    assert de.cap_payload(body)["thomas_guardrail_modes"]["reach"] == "permissive"


def test_the_server_ladder_matches_the_menu_file() -> None:
    """Pin the two lists together: a level the menu marks `elevates` must be one
    the server holds back, and none the server holds back may be unmarked."""
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "thomas/server/web/js/chat_preferences.js").read_text(encoding="utf-8")
    marked = set(re.findall(r"\[\s*'?(\w+)'?,[^\]]*\{ elevates: true \}", js))
    assert marked == {"4", "5", "pc", "open"}
    for value in marked:
        dial = "autonomy" if value.isdigit() else ("guardrails" if value == "open" else "file_access")
        assert de.is_elevated(dial, value), f"the menu asks for a tap on {value!r} but the server does not"


def test_the_dial_prompt_is_worded_by_the_pinned_catalogue() -> None:
    """Every word on a PIN prompt comes from the one catalogue whose hash is
    pinned (thomas/tools/trusted_card.py) -- dials included."""
    from thomas.tools import trusted_card

    seen: list[tuple[str, str]] = []
    de.approve("autonomy", 5, authorize=lambda action, reason: seen.append((action, reason)) or False)
    ((action, _reason),) = seen
    title, body = trusted_card.load_catalogue().render("raise_dial", {"dial": de._LABELS["autonomy"], "value": 5})
    assert action == f"{title}\n\n{body}"


def test_an_edited_catalogue_refuses_a_dial_without_asking(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from thomas.tools import cage_shell, trusted_card

    pins = Path(cage_shell.DEFAULT_PIN_ROOT)
    pins.mkdir(parents=True, exist_ok=True)
    (pins / trusted_card.PIN_NAME).write_text("0" * 64, encoding="utf-8")
    seen: list[str] = []
    assert de.approve("autonomy", 5, authorize=lambda action, reason: seen.append(action) or True) is False
    assert not seen, "asked for a PIN on wording that was not the pinned wording"
