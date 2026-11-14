"""Your Claude plan as a model Thomas can run: where the CLI is, and how it refuses.

Build has run on your Claude plan since 2026-09-24 by driving the Claude Code
CLI, which carries its own sign-in and needs no Anthropic API key
(``thomas/forge/anvil/dispatch_claude_cli.py``). Chat could not: the catalog
marked those model names ``build_only`` and the Anthropic profile without a key
counted as "needs key", so the Claude plan was visible in Build and absent from
Chat. You asked for it in Chat too, "the same way Build does", which is what
this module makes possible for the transport in
``thomas/core/llm_streaming_claude_cli.py``.

The plan-limit and not-signed-in vocabulary lives here rather than in Build
because Chat now meets the same two refusals, and a second spelling of either
would be a second answer to the same question.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The provider string of a profile the Claude CLI can serve. Anthropic's own API
# uses the same name; the key is what tells them apart.
CLAUDE_PLAN_PROVIDER = "anthropic"
_LOOKUP_TTL_S = 60.0  # the CLI does not appear and vanish mid-conversation; don't scan PATH for every menu paint
_lock = threading.Lock()
_looked: tuple[float, str] | None = None


def claude_cli_path(*, which: Callable[[str], str | None] | None = None) -> str:
    """Where the ``claude`` CLI is on this machine, or "" when it is not installed.

    Cached for a minute: ``/api/models`` asks on every model-menu paint, and a
    PATH scan per paint is measurable. A caller that must not cache passes
    ``which``.
    """
    global _looked
    finder = which or shutil.which
    if which is not None:
        return str(finder("claude") or finder("claude.cmd") or "")
    now = time.monotonic()
    with _lock:
        if _looked is not None and now - _looked[0] < _LOOKUP_TTL_S:
            return _looked[1]
    found = str(finder("claude") or finder("claude.cmd") or "")
    with _lock:
        _looked = (now, found)
    return found


def runs_on_claude_plan(provider: str, api_key: str) -> bool:
    """Whether this profile is served by your Claude plan rather than by an Anthropic key.

    A structural rule, not a guess: the Anthropic provider with no key has
    nowhere else to go, and the CLI holds a sign-in of its own. Adding a key
    moves the same profile back to Anthropic's API.
    """
    normalized = str(provider or "").strip().lower().replace("-", "_")
    return normalized == CLAUDE_PLAN_PROVIDER and not str(api_key or "").strip()


def claude_plan_ready(provider: str, api_key: str, *, which: Callable[[str], str | None] | None = None) -> bool:
    """``runs_on_claude_plan``, and the CLI it needs is actually here."""
    return runs_on_claude_plan(provider, api_key) and bool(claude_cli_path(which=which))


# The model names your Claude plan answers to, and the whole of what it offers in
# the model menu: thomas/models/sources/claude_cli.py builds that list from these.
# The CLI resolves these aliases to an exact model privately -- not always the
# newest (thomas/core/claude_alias_ids.py) -- and Anthropic's API never names a
# model this way: its ids carry a version.
CLAUDE_PLAN_MODEL_IDS = ("opus", "sonnet", "haiku")


def chose_claude_plan(provider: str, api_key: str, model: str) -> bool:
    """Whether THIS turn asked for your Claude plan, and so runs through the CLI.

    ``runs_on_claude_plan`` answers about a profile — which engine the model menu
    should offer for it. A transport needs the narrower question, because a
    missing key is not by itself a request for the Claude program: an Anthropic
    profile carrying a versioned model name and no key means Anthropic's API, and
    starting a local program instead of the HTTP call it asked for would be a
    different request than the one made. Only the names the plan itself offers,
    which are the only ones the menu can hand back when you pick it, run the CLI.
    """
    chosen = str(model or "").split(":")[-1].strip().lower()
    return runs_on_claude_plan(provider, api_key) and chosen in CLAUDE_PLAN_MODEL_IDS


# --- The Claude CLI's not-signed-in failure -------------------------------------
# "Not logged in — Please run /login", exit 1. ``/login`` is a claude-CLI command
# a Thomas owner has no way to run from the product, so surfacing the raw text
# verbatim was a dead end. The translation names the real situation and the ways
# out, and keeps the CLI's own words attached as the detail.
_CLAUDE_CLI_LOGIN_RE = re.compile(r"not logged in|please run /login", re.IGNORECASE)

CLAUDE_CLI_LOGIN_GUIDANCE = (
    "The Claude engine isn't signed in on this machine — run `claude` in a terminal and sign in, "
    "add an Anthropic key in Settings, or pick one of the ready OpenAI models."
)

# The other way the plan cannot serve a turn. Both sentences live here so Chat's
# failure text can recognise them and pass them through whole, instead of
# replacing a sentence that says what to do with one that does not.
CLAUDE_CLI_MISSING_GUIDANCE = (
    "Your Claude plan runs through the Claude CLI, and it is not installed on this machine. "
    "Install Claude Code and sign in, or add an Anthropic API key in Settings to use Anthropic's API instead."
)

# A third way the plan cannot serve a turn: the surface running it cannot start a
# subprocess at all. A Windows selector event loop raises NotImplementedError on the
# attempt, and the terminal REPL asks for one (thomas/cli/_commands_misc.py) because
# prompt_toolkit needs it. Chat in the browser runs on a proactor loop and never meets
# this, so the sentence says which surface can.
CLAUDE_CLI_NO_SUBPROCESS_GUIDANCE = (
    "Your Claude plan runs through the Claude CLI, and this Thomas surface cannot start it: its event loop "
    "does not support subprocesses. Chat in the browser can — or add an Anthropic API key in Settings to use "
    "Anthropic's API here instead."
)


def is_claude_cli_login_error(text: str) -> bool:
    """True iff ``text`` carries the Claude CLI's not-logged-in failure.

    Matches the raw CLI wording, and therefore also the mapped guidance text,
    which quotes the raw wording as its detail — so a dispatcher watching the
    emitted stream can recognize the situation either way.
    """
    return bool(_CLAUDE_CLI_LOGIN_RE.search(str(text or "")))


def login_error_text(raw: str) -> str:
    return f"{CLAUDE_CLI_LOGIN_GUIDANCE} (Claude CLI said: {str(raw or '').strip()})"


# A sign-in the CLI does not have, remembered for as long as this process runs.
# Every other connection's catalog check spends its credential and records the
# refusal, so an expired sign-in keeps that connection out of the models named as
# the way out of a limit (``thomas/models/ready_elsewhere.py``). Listing this
# plan's models asks the CLI nothing -- ``opus``, ``sonnet``, ``haiku`` is a
# constant -- so the check answers whether or not Claude Code is signed in, and a
# ChatGPT limit would have replied "I can answer on Claude Sonnet meanwhile" with
# nothing behind it: "there was no other model I could choose", in another
# provider's name. The CLI's own refusal is the cheap way to know, and it is
# forgotten the moment that profile answers, so signing in needs no restart.
_signin_lock = threading.Lock()
_no_signin: set[str] = set()


def remember_not_signed_in(profile: str) -> None:
    """This profile's turn was refused for want of a Claude Code sign-in."""
    name = str(profile or "").strip()
    if name:
        with _signin_lock:
            _no_signin.add(name)


def signed_in_again(profile: str) -> None:
    """This profile has answered, so whatever was remembered about its sign-in is stale."""
    name = str(profile or "").strip()
    if name:
        with _signin_lock:
            _no_signin.discard(name)


def profiles_without_a_signin() -> frozenset[str]:
    """The profiles whose Claude CLI has refused for want of a sign-in and not answered since."""
    with _signin_lock:
        return frozenset(_no_signin)


# --- The Claude plan's usage limit ---------------------------------------------
# Claude Code 2.1.278 ends a run your plan refused with a ``rate_limit_event``
# (``status: "rejected"``, ``resetsAt``) and a 429 result: "You've hit your session
# limit · resets 12:20pm (America/Chicago)". Anthropic's short-lived throttling has
# the same status, so only that event or the plan's wording marks a limit. It is
# written the way the ChatGPT and Anthropic clients write theirs, reset first, so
# the 220 characters a crash cause keeps always hold it (autopilot_park reads it).
PLAN_LIMIT_PREFIX = "Claude HTTP 429 usage limit reached."
_PLAN_LIMIT_WORDS = re.compile(r"^You(?:'ve hit your|'ve reached your|'re out of usage credits)")
_RESETS_WORDS = re.compile(
    r"\bresets (?:(?P<mon>[A-Z][a-z]{2}) (?P<day>\d{1,2}),? (?:(?P<year>\d{4}),? )?)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s?(?P<half>am|pm)\b(?:\s*\((?P<zone>[^)]+)\))?",
    re.IGNORECASE,
)
_ZONE_MARGIN_S = 3600  # the zone could not be read: carry on an hour late rather than early


def plan_limit_words(text: str) -> bool:
    """Whether the CLI's own sentence says your plan refused the request."""
    return bool(_PLAN_LIMIT_WORDS.match(str(text or "")))


def _now() -> datetime:
    return datetime.now().astimezone()


def reset_from_words(text: str, now: datetime) -> tuple[int, bool] | None:
    """The reset the CLI printed, as ``(Unix seconds, exact)``. A bare time is its next occurrence (a date is
    printed only a day or more ahead). Without ``tzdata`` for the zone, it is read on this machine's clock, where
    the CLI runs, plus an hour, and is not exact."""
    words = _RESETS_WORDS.search(str(text or ""))
    if words is None:
        return None
    try:
        zone = ZoneInfo(words["zone"].strip()) if words["zone"] else None
    except (ValueError, ZoneInfoNotFoundError):
        zone = None
    local = now.astimezone(zone) if zone is not None else now.astimezone()
    hour = int(words["hour"]) % 12 + (12 if words["half"].lower() == "pm" else 0)
    try:
        at = local.replace(hour=hour, minute=int(words["minute"] or 0), second=0, microsecond=0)
        if words["mon"]:
            month = datetime.strptime(words["mon"].title(), "%b").month
            at = at.replace(year=int(words["year"] or local.year), month=month, day=int(words["day"]))
            if not words["year"] and at < local - timedelta(days=1):
                at = at.replace(year=at.year + 1)
        elif at <= local:
            at += timedelta(days=1)
    except ValueError:  # a month, day or minute no calendar has
        return None
    return int(at.timestamp()) + (0 if zone is not None else _ZONE_MARGIN_S), zone is not None


def plan_limit_text(text: str, *, rejected: bool = False, resets_at: int | None = None) -> str:
    """The error for a 429 from the CLI: a plan limit with its reset, or a short-lived rate limit.

    ``rejected`` and ``resets_at`` come from the ``rate_limit_event`` the CLI
    sends before the refusal, when it sent one.
    """
    txt = str(text or "").strip()
    if not (rejected or plan_limit_words(txt)):
        return f"Claude HTTP 429 rate limited. {txt}"  # no quota code: Autopilot retries it as before
    body: dict[str, Any] = {"type": "usage_limit_reached"}
    reset = (int(resets_at), True) if resets_at else None
    reset = reset or reset_from_words(txt, _now())
    if reset is not None:
        body["resets_at"] = reset[0]
        if not reset[1]:
            body["resets_at_estimated"] = True
    return f"{PLAN_LIMIT_PREFIX} {json.dumps({'error': body}, separators=(',', ':'))} {txt}".strip()
