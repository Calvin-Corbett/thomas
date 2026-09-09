"""Chat-native operation of Thomas runs from Slack (CAP-072).

This module exposes :class:`ChatOps`, a thin facade that maps the five
chat-platform operation verbs onto Thomas's existing runtime seams:

1. **dispatch** a background run from a chat command
   (``thomas.server.chat_delegation.start_background_delegation``);
2. **steer** an in-flight run
   (``thomas.server.chat_delegation.apply_task_update`` -> ``action="steer"``);
3. **approve / deny** a pending approval (an injected governed-approval seam,
   gated by an authorizer so an unauthorized approver is rejected);
4. **diff review** — render a change as a Block Kit diff message;
5. **request-to-merge** — trigger the governed merge and post a proof message
   built from the merge's validation evidence.

Design
------
The external edge (Slack) sits behind an injectable :class:`ChatTransport`.
The real default, :class:`SlackChatTransport`, talks to the live Slack Web API
through the repo's existing ``SlackIntegration`` / ``SlackMessaging`` client and
reads the bot token from the environment (or an injected provider) **at call
time** — the token is never stored on the instance in cleartext, never logged,
and is redacted from ``repr``. Tests inject :class:`FakeChatTransport`, a
hermetic recorder, so every verb is proven offline with no network.

The four runtime seams are injected via :class:`ChatOpsSeams`. ``dispatch`` and
``steer`` have real defaults wired to ``thomas.server.chat_delegation`` (an
allowed integrations -> server edge). ``approve`` and ``merge`` are governed
actions whose real implementations live in the ``forge`` tier, which the
integrations tier may not import; the server layer (which *may* import forge)
wires those callables in. Unwired governance seams raise a clear error rather
than silently succeeding.

Credential-gated live lane
--------------------------
The fake-backed tests fully exercise the five verbs offline. A live Slack post
only happens when ``SLACK_BOT_TOKEN`` (or an injected ``token_provider``) is
present; without a token :class:`SlackChatTransport` raises ``ChatOpsError``
instead of pretending a post succeeded.
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .integration import SlackIntegration
from .messaging import SlackMessaging

__all__ = [
    "ChatOps",
    "ChatOpsError",
    "ChatOpsSeams",
    "ChatTransport",
    "FakeChatTransport",
    "SlackChatTransport",
    "build_diff_blocks",
    "build_merge_proof_blocks",
]

# Slack's section ``text`` field caps at 3000 chars; headers at 150.
_SECTION_LIMIT = 2900
_HEADER_LIMIT = 150

DispatchSeam = Callable[..., Any]
SteerSeam = Callable[..., Any]
ApproveSeam = Callable[..., Any]
MergeSeam = Callable[..., Any]
TokenProvider = Callable[[], str]


class ChatOpsError(RuntimeError):
    """Raised when a chat-ops action cannot be completed (no token, unwired seam)."""


# ── transport ────────────────────────────────────────────────────────────────


@runtime_checkable
class ChatTransport(Protocol):
    """The chat edge ChatOps posts through. Async so the Slack default fits."""

    async def post_message(
        self,
        *,
        channel: str,
        text: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]: ...

    async def add_reaction(self, *, channel: str, ts: str, emoji: str) -> dict[str, Any]: ...


def _default_token_provider() -> str:
    """Read the Slack bot token from the environment at call time (never stored)."""
    return (os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_TOKEN") or "").strip()


class SlackChatTransport:
    """Real transport: posts via the live Slack Web API using the repo client.

    The bot token is fetched from ``token_provider`` (default: environment) on
    each call and used only to build a short-lived ``SlackIntegration``. It is
    never assigned to an attribute, never logged, and redacted from ``repr``.
    """

    def __init__(self, *, token_provider: TokenProvider | None = None, timeout_s: int = 30) -> None:
        self._token_provider: TokenProvider = token_provider or _default_token_provider
        self._timeout_s = int(timeout_s)

    def __repr__(self) -> str:  # pragma: no cover - trivial, but must not leak a token
        return f"SlackChatTransport(token=***redacted***, timeout_s={self._timeout_s})"

    def _new_integration(self) -> SlackIntegration:
        token = str(self._token_provider() or "").strip()
        if not token:
            raise ChatOpsError(
                "Slack bot token unavailable; set SLACK_BOT_TOKEN or inject a token_provider "
                "before using the live chat transport."
            )
        return SlackIntegration(client_id="", client_secret="", bot_token=token, timeout_s=self._timeout_s)

    async def post_message(
        self,
        *,
        channel: str,
        text: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        integration = self._new_integration()
        try:
            await integration.connect()
            messaging = SlackMessaging(integration)
            return await messaging.send_message(
                channel=channel,
                text=text,
                blocks=blocks,
                thread_ts=thread_ts,
            )
        finally:
            await integration.disconnect()

    async def add_reaction(self, *, channel: str, ts: str, emoji: str) -> dict[str, Any]:
        integration = self._new_integration()
        try:
            await integration.connect()
            messaging = SlackMessaging(integration)
            return await messaging.add_reaction(channel=channel, ts=ts, emoji=emoji)
        finally:
            await integration.disconnect()


class FakeChatTransport:
    """Hermetic transport used by tests: records posts, returns synthetic ``ts``."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.reactions: list[dict[str, Any]] = []
        self._counter = 0

    async def post_message(
        self,
        *,
        channel: str,
        text: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        self._counter += 1
        ts = f"170000000.{self._counter:06d}"
        record = {
            "ok": True,
            "channel": channel,
            "ts": ts,
            "text": text,
            "blocks": list(blocks or []),
            "thread_ts": thread_ts,
        }
        self.messages.append(record)
        return record

    async def add_reaction(self, *, channel: str, ts: str, emoji: str) -> dict[str, Any]:
        record = {"ok": True, "channel": channel, "ts": ts, "emoji": emoji}
        self.reactions.append(record)
        return record

    @property
    def last(self) -> dict[str, Any]:
        if not self.messages:
            raise AssertionError("no messages were posted")
        return self.messages[-1]


# ── Block Kit builders ───────────────────────────────────────────────────────


def _clip(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": _clip(text, _SECTION_LIMIT)}}


def _header(text: str) -> dict[str, Any]:
    return {"type": "header", "text": {"type": "plain_text", "text": _clip(text, _HEADER_LIMIT), "emoji": True}}


def build_diff_blocks(
    *,
    title: str,
    diff: str,
    summary: str = "",
    files: Collection[str] | None = None,
) -> list[dict[str, Any]]:
    """Render a change as a Block Kit diff message (header + code-fenced diff)."""
    blocks: list[dict[str, Any]] = [_header(f"Diff review: {title}")]
    if summary:
        blocks.append(_section(summary))
    if files:
        listing = "\n".join(f"• `{f}`" for f in files)
        blocks.append(_section(f"*Files changed:*\n{listing}"))
    body = _clip(str(diff or "").rstrip("\n"), _SECTION_LIMIT - 20)
    blocks.append(_section(f"```diff\n{body}\n```"))
    return blocks


def _validation_line(validation: dict[str, Any]) -> str:
    passed = bool(validation.get("passed"))
    icon = ":white_check_mark:" if passed else ":x:"
    command = str(validation.get("command") or "check").strip()
    evidence = str(validation.get("evidence") or ("PASS" if passed else "FAIL")).strip()
    return f"{icon} `{command}` — {evidence}"


def build_merge_proof_blocks(
    *,
    merge_ref: str,
    result: dict[str, Any],
    approver: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """Build the request-to-merge proof message from the merge's validation evidence.

    Returns ``(blocks, fallback_text)``. The proof always renders the validation
    evidence so the chat record carries the reason the merge was (or was not)
    allowed — not just a bare "merged" claim.
    """
    result = result or {}
    merged = bool(result.get("merged") or result.get("ok"))
    headline_icon = ":white_check_mark:" if merged else ":x:"
    status = "merged" if merged else "blocked"
    commit = str(result.get("commit") or result.get("backup_path") or "").strip()

    fallback = f"Merge proof for {merge_ref}: {status}"
    blocks: list[dict[str, Any]] = [_header(f"Merge proof: {merge_ref}")]

    summary_lines = [f"{headline_icon} Request-to-merge `{merge_ref}` — *{status}*."]
    if approver:
        summary_lines.append(f"Requested by <@{approver}>.")
    if commit:
        summary_lines.append(f"Commit: `{commit}`")
    blocks.append(_section("\n".join(summary_lines)))

    validations = [v for v in (result.get("validations") or []) if isinstance(v, dict)]
    if validations:
        evidence = "\n".join(_validation_line(v) for v in validations)
        blocks.append(_section(f"*Validation evidence*\n{evidence}"))
    else:
        note = str(result.get("evidence") or result.get("reason") or "no validation evidence provided")
        blocks.append(_section(f"*Validation evidence*\n{note}"))
    return blocks, fallback


# ── seams ────────────────────────────────────────────────────────────────────


def _unwired(name: str) -> Callable[..., Any]:
    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise ChatOpsError(
            f"the '{name}' governance seam is not wired; inject it via ChatOpsSeams "
            f"(the server layer binds it to the governed {name} implementation)"
        )

    return _raise


@dataclass(frozen=True)
class ChatOpsSeams:
    """The four runtime seams the five verbs drive (diff review is pure render)."""

    dispatch: DispatchSeam
    steer: SteerSeam
    approve: ApproveSeam
    merge: MergeSeam

    @classmethod
    def live(
        cls,
        *,
        app: Any = None,
        repo_root: Any = None,
        approve: ApproveSeam | None = None,
        merge: MergeSeam | None = None,
    ) -> ChatOpsSeams:
        """Bind ``dispatch`` and ``steer`` to the live chat_delegation seams.

        ``approve`` and ``merge`` are governed forge-tier actions the integrations
        tier may not import directly; pass them in (the server wires them).
        """
        # Imported here (integrations -> server is an allowed edge) so the module
        # stays importable without pulling the heavy server graph at import time.
        from thomas.server.chat_delegation import apply_task_update, start_background_delegation

        async def _dispatch(
            prompt: str,
            *,
            session_id: str,
            mode: str,
            recent_messages: list[dict[str, Any]] | None = None,
            emit_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
            **kwargs: Any,
        ) -> Any:
            if app is None:
                raise ChatOpsError("live dispatch requires an aiohttp app; pass app=... to ChatOpsSeams.live")

            async def _sink(_event: dict[str, Any]) -> None:
                return None

            return await start_background_delegation(
                app,
                session_id=session_id,
                prompt=prompt,
                mode=mode,
                recent_messages=recent_messages,
                emit_event=emit_event or _sink,
                repo_root=repo_root,
                **kwargs,
            )

        def _steer(session_id: str, task_ref: str, instruction: str, **kwargs: Any) -> Any:
            return apply_task_update(session_id, task_ref, instruction, repo_root=repo_root, **kwargs)

        return cls(
            dispatch=_dispatch,
            steer=_steer,
            approve=approve or _unwired("approve"),
            merge=merge or _unwired("merge"),
        )


# ── facade ───────────────────────────────────────────────────────────────────


async def _resolve(value: Any) -> Any:
    """Await ``value`` if the injected seam returned a coroutine; else pass through."""
    if inspect.isawaitable(value):
        return await value
    return value


def _execution_id(record: Any) -> str:
    if isinstance(record, list):
        record = record[0] if record else {}
    if isinstance(record, dict):
        return str(record.get("execution_id") or record.get("task_id") or "")
    return ""


def _normalize_authorizer(spec: Collection[str] | Callable[[str], bool] | None) -> Callable[[str], bool]:
    if spec is None:
        return lambda _approver: True
    if callable(spec):
        return lambda approver: bool(spec(approver))
    allowed = {str(item).strip() for item in spec if str(item).strip()}
    return lambda approver: str(approver).strip() in allowed


class ChatOps:
    """Chat-native operation of Thomas runs. All verbs are async and post proof."""

    def __init__(
        self,
        *,
        transport: ChatTransport | None = None,
        seams: ChatOpsSeams | None = None,
        authorized_approvers: Collection[str] | Callable[[str], bool] | None = None,
        default_channel: str | None = None,
    ) -> None:
        self._transport: ChatTransport = transport or SlackChatTransport()
        self._seams = seams or ChatOpsSeams.live()
        self._authorized = _normalize_authorizer(authorized_approvers)
        self._default_channel = default_channel

    def _channel(self, channel: str | None) -> str:
        resolved = str(channel or self._default_channel or "").strip()
        if not resolved:
            raise ChatOpsError("no channel given and no default_channel configured")
        return resolved

    # (1) DISPATCH ────────────────────────────────────────────────────────────
    async def dispatch_run(
        self,
        prompt: str,
        *,
        session_id: str,
        channel: str | None = None,
        mode: str = "max",
        recent_messages: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
        **dispatch_kwargs: Any,
    ) -> dict[str, Any]:
        channel = self._channel(channel)
        record = await _resolve(
            self._seams.dispatch(
                prompt,
                session_id=session_id,
                mode=mode,
                recent_messages=recent_messages,
                **dispatch_kwargs,
            )
        )
        exec_id = _execution_id(record)
        text = f":rocket: Dispatched run `{exec_id or 'pending'}` — {_clip(prompt, 200)}"
        message = await self._transport.post_message(
            channel=channel, text=text, blocks=[_section(text)], thread_ts=thread_ts
        )
        return {"ok": True, "verb": "dispatch", "record": record, "execution_id": exec_id, "message": message}

    # (2) STEER ─────────────────────────────────────────────────────────────────
    async def steer_run(
        self,
        task_ref: str,
        instruction: str,
        *,
        session_id: str,
        channel: str | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        channel = self._channel(channel)
        result = await _resolve(self._seams.steer(session_id, task_ref, instruction))
        ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
        if not ok:
            error = result.get("error") if isinstance(result, dict) else "unknown error"
            text = f":warning: Could not steer `{task_ref}`: {error}"
        else:
            eid = result.get("execution_id") if isinstance(result, dict) else ""
            text = f":arrows_counterclockwise: Steered `{eid or task_ref}` — {_clip(instruction, 200)}"
        message = await self._transport.post_message(
            channel=channel, text=text, blocks=[_section(text)], thread_ts=thread_ts
        )
        return {"ok": ok, "verb": "steer", "result": result, "message": message}

    # (3) APPROVE / DENY ────────────────────────────────────────────────────────
    async def resolve_approval(
        self,
        approval_id: str,
        *,
        approver: str,
        decision: str = "approve",
        channel: str | None = None,
        thread_ts: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        channel = self._channel(channel)
        decision = str(decision or "approve").strip().lower()
        if decision not in ("approve", "deny"):
            raise ChatOpsError(f"unknown approval decision: {decision!r}")

        if not self._authorized(approver):
            text = f":no_entry: <@{approver}> is not authorized to {decision} approval `{approval_id}`."
            message = await self._transport.post_message(
                channel=channel, text=text, blocks=[_section(text)], thread_ts=thread_ts
            )
            return {
                "ok": False,
                "authorized": False,
                "verb": "approval",
                "approval_id": approval_id,
                "message": message,
            }

        result = await _resolve(self._seams.approve(approval_id, decision=decision, approver=approver, reason=reason))
        if decision == "approve":
            text = f":white_check_mark: <@{approver}> approved `{approval_id}`."
        else:
            text = f":x: <@{approver}> denied `{approval_id}`" + (f": {reason}" if reason else ".")
        message = await self._transport.post_message(
            channel=channel, text=text, blocks=[_section(text)], thread_ts=thread_ts
        )
        return {
            "ok": True,
            "authorized": True,
            "decision": decision,
            "verb": "approval",
            "approval_id": approval_id,
            "result": result,
            "message": message,
        }

    # (4) DIFF REVIEW ───────────────────────────────────────────────────────────
    async def post_diff_review(
        self,
        *,
        title: str,
        diff: str,
        channel: str | None = None,
        summary: str = "",
        files: Collection[str] | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        channel = self._channel(channel)
        blocks = build_diff_blocks(title=title, diff=diff, summary=summary, files=files)
        message = await self._transport.post_message(
            channel=channel, text=f"Diff review: {title}", blocks=blocks, thread_ts=thread_ts
        )
        return {"ok": True, "verb": "diff_review", "blocks": blocks, "message": message}

    # (5) REQUEST-TO-MERGE ──────────────────────────────────────────────────────
    async def request_to_merge(
        self,
        merge_ref: str,
        *,
        approver: str,
        channel: str | None = None,
        thread_ts: str | None = None,
        **merge_kwargs: Any,
    ) -> dict[str, Any]:
        channel = self._channel(channel)
        if not self._authorized(approver):
            text = f":no_entry: <@{approver}> is not authorized to request merge of `{merge_ref}`."
            message = await self._transport.post_message(
                channel=channel, text=text, blocks=[_section(text)], thread_ts=thread_ts
            )
            return {
                "ok": False,
                "authorized": False,
                "verb": "merge",
                "merge_ref": merge_ref,
                "message": message,
            }

        result = await _resolve(self._seams.merge(merge_ref, approver=approver, **merge_kwargs))
        result_dict = result if isinstance(result, dict) else {"ok": bool(result)}
        blocks, fallback = build_merge_proof_blocks(merge_ref=merge_ref, result=result_dict, approver=approver)
        message = await self._transport.post_message(channel=channel, text=fallback, blocks=blocks, thread_ts=thread_ts)
        merged = bool(result_dict.get("merged") or result_dict.get("ok"))
        return {
            "ok": merged,
            "authorized": True,
            "verb": "merge",
            "merge_ref": merge_ref,
            "result": result_dict,
            "message": message,
        }
