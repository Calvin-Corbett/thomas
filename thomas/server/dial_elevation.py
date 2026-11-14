"""Raising one of Thomas's own limits needs a native OS prompt, every time.

Owner direction, 2026-09-22: "agents should be able to trigger toggle changes.
agents cant change stuff that important if they try its password protected so
there is no worry." That was true of Thomas's code, protected files and safety
settings. It was not true of the chat dials: autonomy, file access and internet
reach were guarded by a browser ``window.confirm()`` any automation can click
through, and the server honoured whatever level a request carried. This module
is what makes the owner's premise true.

Two rules:

* **The server decides, not the menu.** A request carrying an elevated level is
  honoured only if the owner approved that level at a native OS prompt (Windows
  Hello, the macOS admin prompt, polkit). Without one it runs at the highest level
  that needs no approval -- degraded, never refused, so nothing stops the work.
  Anything that can reach the API, including an agent, can *ask*; only the person
  at the machine can *approve*.
* **Every approval is a fresh, verified prompt.** The answer is checked with
  Windows, and no earlier approval counts: not the shared auth gate's
  five-minute session, not an open break-glass window. Either would let an
  agent ride the owner's last tap -- given for something unrelated -- and raise
  its own limits without being asked. See :func:`_fresh_native_prompt`.

Grants live in process memory, because a file on disk is something an agent with
file access could write. The one exception is the cage: there the server runs as
thomas-agent, and the owner's desk (running as you) records each approval beside
its answers, in a folder the cage account can read but never write
(scripts/cage/owner_desk.py). That record survives a restart, so Autopilot you
approved stays Autopilot: measured 2026-09-23, a restart had quietly dropped two
Autopilot builds to autonomy 3 while the screen still said Autopilot.
"""

from __future__ import annotations

import logging
import platform
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

# Each dial's values, lowest first, and the first value that needs a tap. These
# mirror the `elevates` flags in thomas/server/web/js/chat_preferences.js; the
# tests pin the two against each other.
_LADDERS: dict[str, tuple[list[Any], Any]] = {
    "autonomy": ([1, 2, 3, 4, 5], 4),
    "file_access": (["read_only", "workspace", "project", "pc", "full"], "pc"),
    "guardrails": (["fortress", "guarded", "open"], "open"),
}

_LABELS = {
    "autonomy": "its autonomy",
    "file_access": "the files it can change",
    "guardrails": "its reach onto the internet",
}

Authorizer = Callable[[str, str], bool]

_lock = threading.Lock()
# dial -> index of the highest value the owner approved this process lifetime.
_grants: dict[str, int] = {}


def _index(dial: str, value: Any) -> int | None:
    """Where *value* sits on its dial's ladder, read the way the run will read it.

    Requests spell levels many ways -- ``5``, ``"L5"``, ``"autopilot"``, ``"home"``,
    ``"read"``. Reading them with Thomas's own parsers keeps this check and the
    run agreeing on what was asked for; a private list of spellings would treat an
    alias as unknown and could move it the wrong way. ``None`` means the parser
    would not recognise it either.
    """
    if dial == "autonomy":
        from thomas.core.autonomy import clamp_autonomy_level, parse_autonomy_level

        # Readers disagree on numbers: Build takes a bare int(value), which turns
        # the JSON float 4.0 -- or 4.9 -- into Full autonomy, while the string
        # parser below does not recognise "4.0" at all. Anything that is a number
        # is read the most generous way any reader reads it, so no reader can end
        # up higher than this check allowed. (Found by review: {"autonomy_level":
        # 4.0} reached Build at level 4 with no prompt.)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return clamp_autonomy_level(int(value)) - 1
            except (OverflowError, ValueError):  # inf / nan: no reader gets a level from these
                return None
        # The parser answers an unknown value with its default, so ask with two
        # different defaults: a value it recognises gives the same answer both times.
        level = parse_autonomy_level(value, default=1)
        return level - 1 if level == parse_autonomy_level(value, default=2) else None
    if dial == "file_access":
        from thomas.core.file_access import parse_file_access_level

        level = parse_file_access_level(value, default=-1)
        return level if level >= 0 else None
    if dial == "guardrails":
        values = _LADDERS[dial][0]
        text = str(value or "").strip().lower()
        return values.index(text) if text in values else None
    return None


def rank(dial: str, value: Any) -> int | None:
    """Where *value* sits on *dial*'s ladder (0 is lowest); None if either is unknown."""
    if dial not in _LADDERS or value is None:
        return None
    return _index(dial, value)


def _recorded_rank(dial: str) -> int:
    """The highest level the owner's desk recorded for *dial*, or -1.

    Read only in the cage. There the desk writes as you, beside its answers, and
    the server can only read (scripts/cage/owner_desk.py), so the record outlives a
    restart without becoming something an agent could write. Outside the cage the
    server runs as you and could write that file itself, so it is not trusted.
    """
    from thomas.tools import owner_desk

    if not owner_desk.enabled():
        return -1
    found = rank(dial, owner_desk.recorded_grants().get(dial))
    return -1 if found is None else found


def _threshold(dial: str) -> int:
    values, first_elevated = _LADDERS[dial]
    return values.index(first_elevated)


def is_elevated(dial: str, value: Any) -> bool:
    """True when *value* is one the owner has to approve."""
    idx = _index(dial, value)
    return idx is not None and idx >= _threshold(dial)


def cap(dial: str, value: Any) -> Any:
    """The level a request actually runs at.

    An approved or unelevated value passes through exactly as sent. An elevated
    value the owner has not approved comes back as the highest level that needs
    no approval, so the work still runs. A value no parser recognises also passes
    through: the run falls back to its own default, which is never elevated, and
    replacing it here could only move it -- possibly upward.
    """
    if dial not in _LADDERS:
        return value
    idx = _index(dial, value)
    if idx is None or idx < _threshold(dial):
        return value
    values = _LADDERS[dial][0]
    safest_open = values[_threshold(dial) - 1]
    with _lock:
        granted = _grants.get(dial, -1)
    if idx <= max(granted, _recorded_rank(dial)):
        return value
    log.info("dial_elevation: %s=%r not approved; running at %r", dial, value, safest_open)
    return safest_open


# The request keys each dial arrives under. Build accepts "guardrails" as well
# as the chat name "thomas_guardrails", so both are capped.
_PAYLOAD_KEYS = {
    "autonomy_level": "autonomy",
    "file_access": "file_access",
    "thomas_guardrails": "guardrails",
    "guardrails": "guardrails",
}


def cap_payload(payload: Any) -> Any:
    """A copy of a request body with every dial level passed through :func:`cap`.

    Call it once, where a handler reads its body, so everything downstream --
    settings, approval hashes, the run itself -- sees the level that will actually
    be honoured. Keys the request did not send stay absent: "not sent" means "use
    the saved default", and inventing a value would change that.
    """
    if not isinstance(payload, dict):
        return payload
    capped = dict(payload)
    for key, dial in _PAYLOAD_KEYS.items():
        if key in capped and capped[key] is not None and capped[key] != "":
            capped[key] = cap(dial, capped[key])
    # Per-group modes override the preset outright (guardrails_state.
    # build_effective_guardrails), so capping only the preset would leave the
    # side door open: "guarded" plus {"reach": "permissive"} is "open" in all but
    # name. A permissive group is what the Open preset means, and needs its tap.
    modes = capped.get("thomas_guardrail_modes")
    if isinstance(modes, dict) and cap("guardrails", "open") != "open":
        capped["thomas_guardrail_modes"] = {
            group: ("standard" if str(mode).strip().lower() == "permissive" else mode) for group, mode in modes.items()
        }
    return capped


def _fresh_native_prompt(action: str, reason: str) -> bool:
    """Ask at the OS, verify the answer, and reuse no earlier approval.

    On Windows this is Thomas's one standard prompt,
    ``windows_auth.verified_sign_in``: Windows' own sign-in (PIN or password),
    whose answer Windows checks. It is called directly, never through the shared
    gate (``get_auth_gate`` / ``WindowsAuthGate``), because that gate treats a tap
    from the last five minutes as approval. Nor through ``authorize_breakglass``,
    which honours an open break-glass window. Either would let an earlier,
    unrelated approval raise these limits silently.
    """
    try:
        if platform.system() == "Windows":
            from thomas.tools.windows_auth import verified_sign_in

            return verified_sign_in(action, reason)
        from thomas.tools.native_auth import request_native_authorization

        return bool(request_native_authorization(action, reason))
    # A prompt that cannot be shown is a "no", never a "yes" -- failing closed is
    # the entire point of asking.
    except (OSError, RuntimeError, ValueError, ImportError, AttributeError) as exc:
        log.warning("dial_elevation: native prompt unavailable: %s", exc)
        return False


def approve(dial: str, value: Any, *, authorize: Authorizer | None = None) -> bool:
    """Ask the owner to allow *dial* up to *value*. True means it is allowed.

    A value that needs no approval is allowed without prompting. An unknown dial
    or value is refused without prompting, so nothing can be approved by accident.
    """
    idx = _index(dial, value)
    if idx is None:
        return False
    if idx < _threshold(dial):
        return True
    # Worded by the pinned catalogue like every other PIN prompt, and refused
    # outright if that catalogue is not the pinned one (thomas/tools/trusted_card.py).
    from thomas.tools import trusted_card

    try:
        trusted_card.require_trusted_catalogue()
    except trusted_card.CatalogueTampered as exc:
        log.error("dial_elevation: refused raising %s without asking -- %s", dial, exc)
        return False
    title, body = trusted_card.load_catalogue().render("raise_dial", {"dial": _LABELS[dial], "value": value})
    action = f"{title}\n\n{body}"
    reason = "Something asked to raise one of Thomas's own limits. Approve only if you meant it."
    from thomas.tools import owner_desk

    if authorize is None and owner_desk.enabled():
        # Running as the cage account: no desktop to prompt on, so the desk asks
        # as you, from the same pinned card, and only its answer counts.
        details = {"dial": _LABELS[dial], "value": value}
        ok = owner_desk.ask_owner("raise_dial", details, content_hash=f"{dial}={value}")
    else:
        ok = (authorize or _fresh_native_prompt)(action, reason)
    if ok:
        with _lock:
            _grants[dial] = max(_grants.get(dial, -1), idx)
        log.info("dial_elevation: owner approved %s up to %r", dial, value)
    return bool(ok)


def grants() -> dict[str, Any]:
    """What the owner has approved, as dial -> highest value: in this process, and
    in the cage also what the desk recorded before a restart."""
    with _lock:
        ranks = dict(_grants)
    for dial in _LADDERS:
        recorded = _recorded_rank(dial)
        if recorded > ranks.get(dial, -1):
            ranks[dial] = recorded
    return {dial: _LADDERS[dial][0][idx] for dial, idx in ranks.items()}


def reset_grants() -> None:
    with _lock:
        _grants.clear()


__all__ = ["approve", "cap", "cap_payload", "grants", "is_elevated", "rank", "reset_grants"]
