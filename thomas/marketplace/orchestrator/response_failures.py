"""User-facing explanations for Chat provider failures and partial replies."""

from __future__ import annotations

import asyncio
import os
import socket
import time
from typing import Any
from urllib.parse import urlsplit

from thomas.core.claude_plan import (
    CLAUDE_CLI_LOGIN_GUIDANCE,
    CLAUDE_CLI_MISSING_GUIDANCE,
    CLAUDE_CLI_NO_SUBPROCESS_GUIDANCE,
    is_claude_cli_login_error,
)
from thomas.core.provider_limits import ModelLimit, read_limit, when_words

# What a model call reads like when the connection itself failed, however deep
# the wrapper: "All connection attempts failed", "[WinError 10061] ... refused",
# "Token refresh could not reach the OAuth service." Never the bare "connect":
# "OAuth is not connected" is a sign-in, not a network.
_NETWORK_MARKERS = ("connection", "connecterror", "refused", "could not reach", "unreachable")
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _loopback(url: str) -> bool:
    try:
        host = str(urlsplit(url).hostname or "")
    except ValueError:
        return False
    return host in _LOOPBACK or host.startswith("127.")


def _egress_proxy_refuses(detail: str, target: str = "") -> bool:
    """True when a network failure came through a loopback HTTPS_PROXY that refuses connections now.

    The caged server reaches its models only through the egress proxy in the
    promoter service (scripts/cage/caged_server.py sets HTTPS_PROXY). When that
    process is gone every call fails with a plain connection error that names
    neither the proxy nor the model, so the proxy is asked directly. A model on
    this machine (*target* on loopback) never goes through the proxy. A listener
    on loopback accepts at once; Windows takes two seconds to refuse, hence the
    short timeout.
    """
    if not any(marker in detail for marker in _NETWORK_MARKERS) or (target and _loopback(target)):
        return False
    try:
        proxy = urlsplit(os.environ.get("HTTPS_PROXY", "").strip())
        host, port = proxy.hostname, proxy.port
    except ValueError:
        return False
    if host not in _LOOPBACK or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return False
    except OSError:
        return True


async def egress_proxy_down(error: str | None, *, target: str = "") -> bool:
    """_egress_proxy_refuses, run off the event loop: the probe may wait 0.3 s."""
    return await asyncio.to_thread(_egress_proxy_refuses, str(error or "").strip().lower(), target)


def failing_target(llm: Any) -> str:
    """The base url of the model call that failed last this turn, when the client keeps a trace; else ''."""
    trace_of = getattr(llm, "runtime_trace", None)
    try:
        trace = trace_of() if callable(trace_of) else None
    except (AttributeError, KeyError, TypeError, ValueError):
        trace = None
    if not isinstance(trace, dict):
        return ""
    for attempt in reversed(list(trace.get("attempts") or [])):
        if isinstance(attempt, dict) and str(attempt.get("status") or "") == "error":
            return str(attempt.get("base_url") or "")
    requested = trace.get("requested")
    return str(requested.get("base_url") or "") if isinstance(requested, dict) else ""


# What kind of thing the provider's account is, in your words. A ChatGPT or Claude
# subscription is a plan with a reset; an Anthropic API key is an account with a bill.
_ACCOUNT_KINDS = {"ChatGPT": "plan", "Claude": "plan", "Anthropic": "account"}

# Anthropic's API refusing a request for want of a valid key is not your ChatGPT
# sign-in, and `codex login` cannot touch it -- but the 401 branch below answered
# every 401 with that command. The keyless Anthropic profile still reaches this
# API when the model it names is one of Anthropic's own versioned ids rather than
# a name your Claude plan offers (llm_transport_pool.py), so this is a state Chat
# can really be in. The plan itself is named as the way out, with the condition
# that makes it true rather than a promise about a menu this text cannot see.
ANTHROPIC_AUTH_GUIDANCE = (
    "Anthropic's API refused this request as unauthorized — this connection's API key is missing or no longer "
    "valid. That is not your ChatGPT sign-in, so `codex login` cannot fix it: add a working Anthropic key in "
    "Settings, or switch to your Claude plan (Claude Opus, Sonnet or Haiku in the model menu), which answers "
    "without a key wherever Claude Code is signed in."
)


async def ready_elsewhere(reader: Any, config: Any, llm: Any) -> tuple[str, ...]:
    """The models this turn could switch to, named by the caller's catalog reader.

    Only the model catalog knows what actually answered last check, and the
    orchestrator may not import ``thomas.models`` (``thomas/_architecture.py``),
    so the reader is handed in: ``thomas/models/ready_elsewhere.py``, passed to
    the brain by whoever builds the turn. Without one, nothing is named — an
    invented alternative is the failure this text exists to stop. The catalog is
    read from disk, so it goes to a thread rather than stalling the stream this
    turn is in the middle of writing.
    """
    if reader is None:
        return ()
    besides = str(getattr(getattr(llm, "config", None), "name", "") or "")
    return await asyncio.to_thread(reader, config, besides=besides)


async def deliver_failure_text(
    dispatcher: Any,
    *,
    delivered_prefix: str,
    failure_text: str,
    partial_text: str,
) -> str:
    """Put the explanation on the wire, and answer with the transcript to save.

    A finished-work note (``delivered_prefix``) goes out whatever else went
    wrong: a completed task must never be silently lost on an error turn. When
    text has already reached the wire, only the terminal explanation is appended
    to it, so nothing is said twice.
    """
    suffix = "\n\n".join(part for part in (delivered_prefix, failure_text) if part)
    if partial_text:
        await dispatcher.emit_text("\n\n" + suffix)
        return f"{partial_text.rstrip()}\n\n{suffix}"
    chunk = 80  # sent in pieces, so it arrives the way a written reply does
    for start in range(0, len(suffix), chunk):
        await dispatcher.emit_text(suffix[start : start + chunk])
    return suffix


def _whose(limit: ModelLimit) -> str:
    account = limit.account
    if not account:
        return "The provider of the selected model"
    return f"Your {account} {_ACCOUNT_KINDS.get(account.split(' ')[0], 'account')}"


def _instead(alternatives: tuple[str, ...]) -> str:
    """What to use meanwhile — or the truth that there is nothing."""
    if not alternatives:
        return (
            " No other model on this machine is ready, so I cannot answer here until then. Adding a key in "
            "Settings, or signing in to the Claude CLI, gives me one straight away."
        )
    listed = alternatives[0] if len(alternatives) == 1 else f"{', '.join(alternatives[:-1])} or {alternatives[-1]}"
    return f" I can answer on {listed} meanwhile — pick one from the model menu above the message box."


def limit_message(
    limit: ModelLimit,
    *,
    alternatives: tuple[str, ...] = (),
    partial_note: str = "",
    autopilot: bool = False,
    now: float | None = None,
) -> str:
    """What Chat says when a provider refuses the turn on a limit.

    This replaced one sentence for every 429 -- "The selected model is temporarily
    rate-limited. Please wait a moment or choose another model." You met it on a
    ChatGPT plan limit with 36 hours left to run: "The limit lasts until Saturday
    morning, not a moment, and there was no other model I could choose." So the
    three things you asked for are the three things it says: which limit, when it
    resets, and what you can use instead -- including when the honest answer is
    that there is nothing else.
    """
    at = time.time() if now is None else now
    whose = _whose(limit)
    if not limit.is_account_limit(at):
        # A burst limit really does clear in moments, and saying so is not the lie.
        clears = limit.reached_at(at)
        soon = f" It clears in about {max(1, int(clears - at))}s." if clears is not None else ""
        stopped = ", and I stopped" if autopilot else ""
        retry = "" if autopilot else " Send it again and it should go through."
        return (
            f"{whose} refused this request for asking too fast — a short burst limit, "
            f"not a usage limit{stopped}.{soon}{retry}{partial_note}"
        )
    moment = limit.reached_at(at)
    if moment is None:
        when = ", and it did not say when it resets"
    elif limit.estimated:
        when = f" — it resets by {when_words(moment)} (read from the words it printed, so it may be sooner)"
    else:
        when = f" — it resets {when_words(moment)}"
    return (
        f"{whose} has reached its usage limit{when}. This is not a wait of moments."
        f"{_instead(alternatives)}{partial_note}"
    )


def _chat_failure_message(
    error: str | None,
    *,
    attempts: int = 1,
    partial_output: bool = False,
    autonomy_level: int = 2,
    turn_timeout_s: float | None = None,
    proxy_down: bool | None = None,
    target: str = "",
    alternatives: tuple[str, ...] = (),
) -> str:
    """Turn provider failures into useful guidance without leaking internals.

    ``autonomy_level`` gates the "try again" instruction: on Autopilot (5) Thomas
    is expected to keep going on its own, so no Chat failure text hands the
    problem back to the user (You asked: "he should never reply back with this
    didnt work say go and ill do it again"). ``turn_timeout_s`` lets a timeout
    name the turn's own time limit instead of blaming "the selected model",
    which never actually failed -- see
    thomas/marketplace/specialists/final_pass.py. Every branch says only what
    actually happened: nothing here promises a follow-up no code performs.
    """
    detail = str(error or "").strip().lower()
    retry_note = " I retried once, but it still failed." if attempts > 1 else ""
    partial_note = " The text above was preserved." if partial_output else ""
    autopilot = int(autonomy_level or 0) >= 5
    if proxy_down is None:  # the chat turn passes it in, measured off the event loop (egress_proxy_down)
        proxy_down = _egress_proxy_refuses(detail, target)
    if proxy_down:
        # Not the model, and not your sign-in: nothing could leave this machine.
        stopped = ", and I stopped" if autopilot else ""
        return (
            "Thomas's network proxy (the promoter service) is not running, so no model outside this machine "
            f"could be reached{stopped}. It restarts within 15 minutes or at your next sign-in.{partial_note}"
        )
    # Read the refusal once, before anything decides whose credential it was: the
    # transports name themselves in it ("Anthropic HTTP 401: ...").
    refusal = read_limit(str(error or ""), at=time.time())
    # Record verified live-login refusals and refresh-token 401s for /api/health.
    # A bare 401 cannot establish that the local sign-in has stopped working.
    try:
        from thomas.core.model_auth_health import record_auth_failure

        if (
            "chatgpt/codex http 401: the live codex login was" in detail
            or "the live codex login still contains the rejected stored token" in detail
            or "token refresh failed with http 401" in detail
        ):
            record_auth_failure(detail=str(error or ""))
    except (ImportError, ModuleNotFoundError, OSError, ValueError, TypeError):  # pragma: no cover
        pass
    # The ways your Claude plan cannot serve a turn already carry sentences written
    # for a person, and say what to do. The generic text at the foot of this
    # function would replace them with one that does neither.
    if is_claude_cli_login_error(detail):
        return f"{CLAUDE_CLI_LOGIN_GUIDANCE}{partial_note}"
    for sentence in (CLAUDE_CLI_MISSING_GUIDANCE, CLAUDE_CLI_NO_SUBPROCESS_GUIDANCE):
        if sentence.lower() in detail:
            return f"{sentence}{partial_note}"
    if "oauth" in detail and ("not connected" in detail or "sign in" in detail):
        return "The ChatGPT model isn't connected yet. Choose the Local model or sign in through Easy Setup."
    # The refusal read above handles a known Anthropic login failure separately.
    # An otherwise unattributed 401 does not establish which login was rejected.
    if refusal is not None and refusal.status == 401 and refusal.provider == "Anthropic":
        return f"{ANTHROPIC_AUTH_GUIDANCE}{partial_note}"
    # A provider 401 affects ChatGPT-backed models, not necessarily the Local model.
    # A rejected live access token or refresh token warrants signing in again.
    if "token refresh failed with http 401" in detail:
        return (
            "The server rejected the Codex login's refresh token (HTTP 401). "
            "Run `codex login` to sign in again — or switch to the Local model."
        )
    if "the live codex login still contains the rejected stored token" in detail:
        return (
            "The server rejected the token in your live Codex login. "
            "Run `codex login` to sign in again — or switch to the Local model."
        )
    if "chatgpt/codex http 401: the live codex login was" in detail:
        reason = (
            "revoked or invalidated"
            if "live codex login was revoked or invalidated" in detail
            else "expired"
            if "live codex login was expired" in detail
            else "rejected"
        )
        return (
            f"The server {reason} your live Codex login, so ChatGPT-backed models can't be reached. "
            "Run `codex login` to sign in again — or switch to the Local model."
        )
    if "token_revoked" in detail or "invalidated oauth token" in detail:
        return (
            "The server revoked or invalidated a ChatGPT access token. "
            "I can't confirm from this error whether your live Codex login works; I won't ask you to sign in again."
        )
    if any(
        token in detail
        for token in (
            "token refresh failed",
            "invalid_grant",
            "http 401",
            "status 401",
            "unauthorized",
        )
    ):
        return (
            "ChatGPT authentication was rejected, so the ChatGPT-backed models can't be reached. "
            "I can't confirm from this error whether your live Codex login works; "
            "the Local model does not need that sign-in."
        )
    # The refusal is read, not pattern-matched: a plan limit says "usage limit
    # reached" and a burst says "rate limited", and the old test for the word
    # "rate limit" answered for one of them in the words of the other. Read once,
    # above, so one turn's failure is never read two ways.
    if refusal is not None and refusal.status == 429:
        return limit_message(refusal, alternatives=alternatives, partial_note=partial_note, autopilot=autopilot)
    if "rate-limit" in detail or "rate limit" in detail or "status 429" in detail:
        # A 429 that named no provider (a proxy, a gateway): nothing to be read
        # out of it, so it claims nothing about how long it lasts.
        return (
            "The selected model refused this request with a rate limit, and said nothing about which limit or "
            f"when it resets.{_instead(alternatives)}"
        )
    if any(token in detail for token in ("timed out", "timeout")):
        if autopilot:
            return f"I hit this turn's time limit and stopped -- nothing is running in the background.{partial_note}"
        limit = f" ({int(turn_timeout_s)}-second limit)" if turn_timeout_s else ""
        return f"I hit this turn's time limit before finishing{limit}.{retry_note}{partial_note} Please try again."
    if any(token in detail for token in ("connection", "connecterror")):
        if autopilot:
            return f"I couldn't reach the selected model, and stopped.{retry_note}{partial_note}"
        return f"I couldn't reach the selected model.{retry_note}{partial_note} Please check that it is running and try again."
    answer_kind = "a complete answer" if partial_output else "an answer"
    if autopilot:
        return f"I couldn't get {answer_kind} from the selected model, and stopped.{retry_note}{partial_note}"
    return f"I couldn't get {answer_kind} from the selected model.{retry_note}{partial_note} Please try again or choose another model."
