"""Chat on your Claude plan: the Claude Code CLI driven as an LLM transport.

Build has run on your Claude plan since 2026-09-24 through ``claude -p
--output-format stream-json`` (``thomas/forge/anvil/dispatch_claude_cli.py``).
Chat reached the same plan only through Anthropic's API, which needs a key, so
picking Claude in Chat was impossible while a ChatGPT limit held: "your Chat
can't answer at all until Saturday, even though you can build on my Claude plan
through Claude Code."

This is the same CLI, the same stream-json protocol and the same refusal
vocabulary, shaped into the ``StreamEvent`` contract every other transport in
``thomas/core`` speaks, so the chat turn, the token economy and the specialist
tool loop above it need no Claude-specific branch.

Two honest differences from the Anthropic API transport:

* The CLI takes ONE prompt, not a message list, so the conversation is rendered
  into text (``render_prompt``). Roles stay labelled; nothing is dropped except
  image bytes, which are named in place rather than silently discarded.
* The CLI has no function-calling wire, so Thomas's tools are offered in the
  prompt and a reply that is exactly one JSON call is turned back into real
  tool-call events through ``embedded_tool_call`` — the same seam
  ``stream_openai`` already uses for models with no native tool calling. Prose
  is never held back for longer than it takes to see it is prose.

The CLI's own tools (Read, Bash, Edit, ...) are all denied: a chat turn answers,
it does not act on this machine. Thomas's own tools, with Thomas's own policy
around them, are the only ones a chat turn may reach.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from thomas.core.claude_alias_ids import remember_engine_model
from thomas.core.claude_plan import (
    CLAUDE_CLI_MISSING_GUIDANCE,
    CLAUDE_CLI_NO_SUBPROCESS_GUIDANCE,
    PLAN_LIMIT_PREFIX,
    claude_cli_path,
    is_claude_cli_login_error,
    login_error_text,
    plan_limit_text,
    plan_limit_words,
    remember_not_signed_in,
    signed_in_again,
)
from thomas.core.llm_shared import LLMError, StreamEvent, TokenUsage, embedded_tool_call
from thomas.core.provider_limits import read_limit

log = logging.getLogger(__name__)

# Every built-in tool the CLI could otherwise reach, named one by one. A chat
# turn must not read, write or run anything on this machine: Thomas's own tool
# policy (thomas/server/chat_tool_policy.py) decides what a turn may touch, and
# a second unpoliced tool surface inside the model would go around it.
DENIED_CLI_TOOLS = (
    "Task",
    "Bash",
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    "Read",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "TodoWrite",
)

_ROLE_LABELS = {"user": "You", "assistant": "Thomas", "tool": "Tool result", "developer": "System"}
_IMAGE_NOTE = "[an image you attached — this model answers through the Claude CLI, which is sent text only]"
_CALL_PROTOCOL = (
    "To use one, reply with ONE JSON object and nothing else: "
    '{"name": "<tool name>", "arguments": { ... }}. Any other reply is read as your answer to the person.'
)


def _block_text(block: Any) -> str:
    if not isinstance(block, dict):
        return str(block or "")
    kind = str(block.get("type") or "")
    if kind in {"image", "image_url", "input_image"}:
        return _IMAGE_NOTE
    return str(block.get("text") or "")


def content_text(content: Any) -> str:
    """One message's content as text, naming what cannot be sent instead of dropping it."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part for part in (_block_text(block) for block in content) if part)
    return str(content or "")


def tool_names(tools: list[dict[str, Any]] | None) -> frozenset[str]:
    """The names of the tools this request offered, as ``embedded_tool_call`` matches them."""
    names = set()
    for spec in tools or []:
        function = spec.get("function") if isinstance(spec, dict) else None
        name = str((function or {}).get("name") or "") if isinstance(function, dict) else ""
        if name:
            names.add(name)
    return frozenset(names)


def _tool_catalogue(tools: list[dict[str, Any]] | None) -> str:
    lines = []
    for spec in tools or []:
        function = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(function, dict) or not function.get("name"):
            continue
        description = " ".join(str(function.get("description") or "").split())
        parameters = function.get("parameters")
        schema = json.dumps(parameters, ensure_ascii=False) if isinstance(parameters, dict) else "{}"
        lines.append(f"- {function['name']}: {description}\n  arguments: {schema}")
    return "\n".join(lines)


def render_prompt(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> str:
    """The conversation as one prompt for ``claude -p``.

    Labelled by role so the model can tell your words from its own and from a
    tool's result, with the system instructions first and the newest message
    last. The CLI is given no project directory, so these instructions are the
    whole of what it knows about Thomas.
    """
    system = [content_text(m.get("content")) for m in messages if str(m.get("role") or "") == "system"]
    turns = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role == "system":
            continue
        label = _ROLE_LABELS.get(role, role.title())
        if role == "tool" and message.get("name"):
            label = f"Tool result ({message['name']})"
        text = content_text(message.get("content"))
        if text.strip():
            turns.append(f"{label}: {text.strip()}")
    parts = []
    if any(part.strip() for part in system):
        parts.append("[Your instructions for this turn]\n" + "\n\n".join(part for part in system if part.strip()))
    catalogue = _tool_catalogue(tools)
    if catalogue:
        parts.append(f"[Tools you may use]\n{_CALL_PROTOCOL}\n{catalogue}")
    parts.append("[The conversation]\n" + ("\n\n".join(turns) if turns else "You: (no message)"))
    parts.append("[Now]\nReply to the last message as Thomas, in plain text.")
    return "\n\n".join(parts)


@dataclass
class _JsonHold:
    """Hold back a reply that might turn out to be one JSON tool call.

    Identical in intent to the hold in ``stream_openai``: content that opens
    like JSON waits until the reply ends, when it is either the call it turned
    out to be or text released whole. Prose is released the moment its first
    non-space character proves it is prose, so a normal answer still streams.
    """

    offered: frozenset[str] = frozenset()
    held: str = ""
    holding: bool = field(default=False)

    def __post_init__(self) -> None:
        self.holding = bool(self.offered)

    def feed(self, piece: str) -> str:
        if not self.holding:
            return piece
        self.held += piece
        opening = self.held.lstrip()
        if not opening:
            return ""
        if opening[0] in "{`":
            return ""
        self.holding = False
        text, self.held = self.held, ""
        return text

    def finish(self) -> tuple[str, tuple[str, str] | None]:
        """What is left as ``(text, call)``: exactly one of the two is ever set."""
        self.holding = False
        held, self.held = self.held, ""
        if not held.strip():
            return "", None
        call = embedded_tool_call(held, self.offered) if self.offered else None
        return ("", call) if call is not None else (held, None)


def _usage_event(owner: Any, raw: Any) -> StreamEvent | None:
    """The CLI's own token counts for this turn, in Thomas's accounting."""
    if not isinstance(raw, dict):
        return None
    try:
        cached = int(raw.get("cache_read_input_tokens") or 0)
        written = int(raw.get("cache_creation_input_tokens") or 0)
        prompt = int(raw.get("input_tokens") or 0) + cached + written
        completion = int(raw.get("output_tokens") or 0)
    except (TypeError, ValueError):
        return None
    if not prompt and not completion:
        return None
    usage = TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cached_prompt_tokens=cached,
        cache_write_prompt_tokens=written,
    )
    owner.session_usage.add(usage)
    return StreamEvent(type="usage", data={"usage": usage})


def _call_events(call: tuple[str, str]) -> list[StreamEvent]:
    name, arguments = call
    call_id = f"call_claude_cli_{int(time.time() * 1000)}"
    return [
        StreamEvent(type="tool_call_start", data={"id": call_id, "name": name, "index": 0}),
        StreamEvent(type="tool_call_delta", data={"id": call_id, "delta": arguments}),
        StreamEvent(type="tool_call_end", data={"id": call_id, "name": name, "arguments": arguments}),
    ]


def cli_command(binary: str, model: str) -> list[str]:
    """The exact command a chat turn runs. Separate so a test can read it."""
    return [
        binary,
        "-p",
        "--model",
        model,
        "--permission-mode",
        "dontAsk",
        "--disallowedTools",
        *DENIED_CLI_TOOLS,
        "--strict-mcp-config",
        "--output-format",
        "stream-json",
        "--input-format",
        "stream-json",
        "--verbose",
        # Stream assistant prose as token-progressive ``content_block_delta``
        # events, so a chat reply appears as it is written.
        "--include-partial-messages",
    ]


async def _spawn(command: list[str], *, cwd: str) -> Any:
    return await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        # A single stream-json line carries a whole assistant message; the 64 KiB
        # default would raise part-way through a long answer.
        limit=8 * 1024 * 1024,
    )


def _plan_error(owner: Any, text: str, *, rejected: bool, resets_at: int | None) -> LLMError:
    """A 429 from the CLI, worded so every surface reads the same limit out of it.

    Handed to the park as well as raised, which is what the three HTTP transports
    do with theirs (``llm_streaming.py``, ``llm_streaming_anthropic.py``). The park
    is not bookkeeping: it is what the next message meets instead of the provider,
    what the countdown under the composer reads (``provider_cooldowns.py``), and
    what keeps a plan whose allowance is spent out of the models offered as the way
    out (``thomas/models/ready_elsewhere.py``). Your Claude plan was the one engine
    that never parked, so a Claude limit was invisible to all three: the composer
    line said nothing, and a later ChatGPT limit would have answered "I can answer
    on Claude Sonnet meanwhile" while the plan was out until its reset.
    """
    worded = plan_limit_text(text, rejected=rejected, resets_at=resets_at)
    owner._mark_rate_limited(owner.config, None, worded)
    if not worded.startswith(PLAN_LIMIT_PREFIX):
        # Anthropic's short-lived throttling: retrying it is right, and it is not your plan's limit.
        return LLMError(worded, status=429, retryable=True)
    limit = read_limit(worded, at=time.time())
    return LLMError(
        worded,
        status=429,
        retryable=False,  # the allowance is spent; another attempt cannot pass before it resets
        error_code="usage_limit_reached",
        response_headers=limit.headers if limit is not None else {},
    )


async def _stdout_lines(proc: Any, deadline: float) -> AsyncIterator[str]:
    """Decoded stdout lines until the child ends or ``deadline`` (monotonic) passes."""
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("the Claude CLI did not finish in time")
        raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
        if not raw:
            return
        yield raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)


async def stream_claude_cli(
    owner: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    spawn: Callable[..., Any] | None = None,
    cli_path: str = "",
) -> AsyncIterator[StreamEvent]:
    """One chat turn on your Claude plan, as ``StreamEvent``s.

    ``spawn`` is injectable the way ``dispatch_via_claude_cli``'s ``runner`` is,
    so a test can drive the real stream-json protocol without the CLI.
    """
    binary = cli_path or claude_cli_path()
    if not binary:
        raise LLMError(CLAUDE_CLI_MISSING_GUIDANCE, status=0, retryable=False)
    model = str(getattr(owner.config, "model", "") or "sonnet").split(":")[-1].strip() or "sonnet"
    prompt = render_prompt(messages, tools)
    hold = _JsonHold(offered=tool_names(tools))
    timeout_s = max(30.0, float(getattr(owner.config, "timeout_s", 0) or 0) or 300.0)

    lease = await owner.begin_budget_attempt(messages, tools)
    fed = False
    delta_seen = False
    rejected = False
    resets_at: int | None = None
    usage_raw: Any = None
    failure = ""
    answer = ""
    try:
        # No project directory: a chat turn is a conversation, and a CLI started
        # in a repository would read that repository's instructions as its own.
        with tempfile.TemporaryDirectory(prefix="thomas-chat-claude-") as workspace:
            try:
                proc = await (spawn or _spawn)(cli_command(binary, model), cwd=workspace)
            except NotImplementedError as exc:
                # A Windows selector event loop cannot spawn a subprocess at all. The
                # sentence lives beside the other two refusals so Chat's failure text
                # passes it through whole instead of replacing it with "no answer".
                raise LLMError(CLAUDE_CLI_NO_SUBPROCESS_GUIDANCE, status=0, retryable=False) from exc
            except OSError as exc:
                # The binary was there a moment ago (claude_cli_path found it) and will
                # not start now: gone, or not executable. Worth one more attempt.
                raise LLMError(f"The Claude CLI would not start: {exc}", status=0, retryable=True) from exc
            try:
                if proc.stdin is None or proc.stdout is None:
                    raise LLMError("The Claude CLI started without its pipes.", status=0, retryable=True)
                proc.stdin.write(
                    (json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n").encode()
                )
                await proc.stdin.drain()
                proc.stdin.close()
                async for line in _stdout_lines(proc, asyncio.get_running_loop().time() + timeout_s):
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        if is_claude_cli_login_error(line):
                            failure = login_error_text(line)
                        continue
                    if not isinstance(event, dict):
                        continue
                    kind = str(event.get("type") or "")
                    if kind == "system" and event.get("subtype") == "init":
                        # The CLI names the exact model it started. Chat asks for
                        # the same aliases Build does, on the same program, so
                        # this observation is the same evidence -- and it is what
                        # makes the model menu's label true on a machine where
                        # Chat ran before any build did.
                        remember_engine_model(model, str(event.get("model") or ""))
                    elif kind == "rate_limit_event":
                        info = event.get("rate_limit_info")
                        if isinstance(info, dict) and info.get("status") == "rejected":
                            rejected = True
                            raw_reset = str(info.get("resetsAt") or "")
                            resets_at = int(float(raw_reset)) if raw_reset.replace(".", "", 1).isdigit() else None
                    elif kind == "stream_event":
                        inner = event.get("event")
                        delta = inner.get("delta") if isinstance(inner, dict) else None
                        if not isinstance(delta, dict):
                            continue
                        if delta.get("type") == "text_delta" and str(delta.get("text") or ""):
                            delta_seen = True
                            fed = True
                            release = hold.feed(str(delta["text"]))
                            if release:
                                yield StreamEvent(type="token", data={"text": release})
                        elif delta.get("type") == "thinking_delta" and str(delta.get("thinking") or ""):
                            yield StreamEvent(type="thinking", data={"text": str(delta["thinking"])})
                    elif kind == "assistant" and not delta_seen:
                        message = event.get("message")
                        blocks = message.get("content") if isinstance(message, dict) else None
                        for block in blocks if isinstance(blocks, list) else []:
                            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                                fed = True
                                release = hold.feed(str(block["text"]))
                                if release:
                                    yield StreamEvent(type="token", data={"text": release})
                    elif kind == "result":
                        usage_raw = event.get("usage")
                        answer = str(event.get("result") or "")
                        if event.get("is_error"):
                            if is_claude_cli_login_error(answer):
                                failure = login_error_text(answer)
                            elif event.get("api_error_status") == 429 or plan_limit_words(answer) or rejected:
                                raise _plan_error(owner, answer, rejected=rejected, resets_at=resets_at)
                            else:
                                failure = answer or "the Claude CLI reported an error"
                await proc.wait()
            finally:
                # Only a turn that ended early (a limit, a timeout, a cancel) still
                # has a child here; the line above already reaped a finished one.
                if getattr(proc, "returncode", None) is None:
                    proc.kill()
                    await proc.wait()
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise LLMError(f"Claude CLI timed out after {int(timeout_s)}s.", status=0, retryable=True) from exc
    finally:
        await owner.finish_budget_attempt(lease)

    profile = str(getattr(owner.config, "name", "") or "")
    if failure:
        signed_out = is_claude_cli_login_error(failure)
        if signed_out:
            # Nothing else can learn this: the model catalog lists the plan's three
            # names without asking the CLI anything, so a plan with no sign-in reads
            # there as a connection that answered. Remembering the refusal is what
            # keeps it out of the models named as the way out of another limit.
            remember_not_signed_in(profile)
        raise LLMError(failure, status=401 if signed_out else 500, retryable=False)
    signed_in_again(profile)  # it answered, so nothing remembered about its sign-in still holds
    if not fed and answer.strip():
        # A reply that arrived only in the CLI's terminal ``result`` (no partial
        # messages): still this turn's answer, and the one place it can be read.
        release = hold.feed(answer)
        if release:
            yield StreamEvent(type="token", data={"text": release})
    text, call = hold.finish()
    if text:
        yield StreamEvent(type="token", data={"text": text})
    for event in _call_events(call) if call is not None else ():
        yield event
    usage_event = _usage_event(owner, usage_raw)
    if usage_event is not None:
        yield usage_event
    yield StreamEvent(type="done")
