"""Reasoning Specialist — deep thinking, planning, multi-step analysis.

The default/fallback specialist.  Handles general conversation,
complex reasoning, and multi-step planning tasks.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from thomas.core.send_task_tool import (
    RECALL_TOOL,
    RECALL_TOOL_NAME,
    REMEMBER_TOOL,
    REMEMBER_TOOL_NAME,
    SEND_TASK_TOOL,
    SEND_TASK_TOOL_NAME,
    UPDATE_TASK_TOOL,
    UPDATE_TASK_TOOL_NAME,
)
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.base import BaseSpecialist

# Thomas's own source repo (thomas/marketplace/specialists/reasoning.py -> repo root).
_REPO_ROOT = Path(__file__).resolve().parents[3]

# The chat model sometimes NARRATES a hand-off ("on it — I've handed that off") but
# never actually calls the send_task tool, so no worker ever starts. This matches that
# kind of CLAIM in the model's own reply, so a backstop can complete the real hand-off.
# It reads the MODEL'S OUTPUT (did it say it handed off?), never the user's input — so
# it's not the regex "is this a task?" classifier Calvin retired.
_CLAIMS_HANDOFF_RE = re.compile(
    r"(hand(?:ed|ing)?\s+(?:it|this|that|the\s+\w+)?\s*off"
    r"|handed\s+(?:it|this|that)?\s*(?:to|over)"
    r"|sent\s+(?:it|this|that)\s+(?:to|over)"
    r"|\bon\s+it\b"
    r"|task\s+manager"
    r"|task\s+card"
    r"|i'?ll\s+get\s+(?:it|this|that|you).*(?:built|made|done|set\s+up|going)"
    r"|i'?ve\s+(?:sent|handed|kicked|passed|routed)"
    r"|(?:building|making|creating|designing)\s+(?:it|this|that)\s+now"
    r"|the\s+(?:worker|team|crew).*(?:will|are|is|on\s+it))",
    re.I,
)
# Read-only filesystem tools the chat layer may use to ground answers. NEVER write/shell.
_READ_TOOL_NAMES = ("fs.read_file", "fs.list_dir", "fs.search")

# The model sometimes CLAIMS it stopped/cancelled a running task ("I've cancelled the
# jazz report") without actually calling update_task — a false claim that leaves the
# worker running. When that happens and there IS a running task the user's request
# resolves to, the backstop executes the cancel for real so the words become true.
_CLAIMS_CANCEL_RE = re.compile(r"\b(cancel|cancell?ed|cancell?ing|stop|stopp?ed|stopping|halt|abort|kill)\w*\b", re.I)

# The model sometimes writes a tool CALL as plain text — `send_task {…}` or
# `update_task {…}` — instead of invoking it. It's a real gpt-5.5/codex quirk: the
# JSON lands in the content channel, so no function_call fires and nothing happens
# (no worker starts; no task gets cancelled). We watch the stream for this literal
# ANYWHERE (the cancel form often arrives after a sentence of prose), suppress the
# raw JSON from the user, then honor the intent by calling the tool for real.
# (chat sweep, 2026-06-27)
# Matches the literal however the model dresses it: `send_task {…}`, `update_task(…)`,
# `[update_task {…}]`, or `[update_task] {…}` (it wraps the call in brackets and may put
# a `]` between the name and the JSON).
_TEXT_TOOLCALL_START_RE = re.compile(r"(send_task|update_task)\s*[\]}]?\s*[(\[{]", re.I)
_TEXT_TOOLCALL_NAMES = ("send_task", "update_task")


def _safe_stream_prefix_len(buf: str) -> int:
    """How many leading chars of `buf` are safe to stream RIGHT NOW. Holds back only a
    trailing run that could still be growing into a 'send_task'/'update_task' literal —
    so ordinary prose streams token-by-token (the live "typing" effect is preserved) and
    only a budding tool-call leak is buffered until it's confirmed or ruled out."""
    low = buf.lower()
    n = len(buf)
    # Only the last few chars can be an incomplete literal head; scan that tail.
    for i in range(max(0, n - 14), n):
        seg = low[i:].lstrip("[")  # the literal may be wrapped in '['
        if seg == "":
            return i  # a lone trailing '[' could precede a tool name — hold it
        for name in _TEXT_TOOLCALL_NAMES:
            if name.startswith(seg) or seg.startswith(name):
                return i
    return n


def _parse_text_toolcall(raw: str) -> tuple[str, dict[str, Any]] | None:
    """Pull (name, args) out of a tool call the model emitted as TEXT, e.g.
    `send_task {"title": "..."}` or `[update_task {"task_ref": "...", "cancel": true}]`.
    Degrades gracefully: if the JSON body won't parse, returns empty args — for
    send_task the caller still dispatches with the user's raw prompt, so a parse
    failure never blocks the hand-off."""
    m = _TEXT_TOOLCALL_START_RE.search(raw or "")
    if not m:
        return None
    name = m.group(1).lower()
    args: dict[str, Any] = {}
    start = raw.find("{", m.start())
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                args = parsed
        except Exception:
            args = {}
    return name, args


def _repo_self_context() -> str:
    """Identity + repo awareness + read-only capability, injected every chat turn so
    Thomas knows who he is, that this repo IS him, and that he can READ (not write)."""
    return (
        "WHERE YOU ARE — repo & self awareness (you know this for real):\n"
        f"- You ARE this software. Your own source code lives in the repository at "
        f"{_REPO_ROOT}, and the project is named 'Thomas'. If asked who you are or what "
        "you're part of: you're Thomas, an AI-first workspace platform, and this repo is "
        "your own codebase — say so plainly, don't call yourself a generic 'AI assistant'.\n"
        "- You can READ files to ground your answers — call fs.read_file (a path), "
        "fs.list_dir (a folder), or fs.search (find text). Read the real thing (e.g. "
        "IDENTITY.md, SOUL.md, README.md, AGENTS.md, or any source file) instead of "
        "guessing. Reading is your superpower.\n"
        "- You CANNOT write, edit, delete, or run commands — reading is your only "
        "filesystem power, by design. Anything that changes files is the task manager's "
        "job (hand it off). So, honestly: 'I can read this, but I can't change it.'\n\n"
    )


def _read_tool_specs(registry: Any) -> list[dict]:
    """OpenAI-style function specs for the read-only filesystem tools present in the
    registry, so the chat model can call them. Write/shell tools are never included."""
    specs: list[dict] = []
    if not (registry and hasattr(registry, "get")):
        return specs
    for name in _READ_TOOL_NAMES:
        try:
            tool = registry.get(name)
        except Exception:
            tool = None
        if tool is None:
            continue
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": str(getattr(tool, "name", name)),
                    "description": str(getattr(tool, "description", "") or "")[:1024],
                    "parameters": getattr(tool, "parameters", None) or {"type": "object", "properties": {}},
                },
            }
        )
    return specs


# Thomas's identity is a Calvin design law, not a tunable: he is ONLY a chatbot.
# He talks and may read to stay aware; he never builds/writes/runs/PLANS anything,
# and there are no modes that change this. One canonical constant, guarded by
# tests/test_reasoning_identity.py + thomas/chat/README.md. Do NOT soften it or add
# behavior toggles. See memory: thomas-chatbot-only-no-modes-law.
THOMAS_CHATBOT_SYSTEM_PROMPT = (
    "You are Thomas. Your name is Thomas. "
    "You are a sharp, resourceful friend — not a customer service bot.\n\n"
    "Be direct, warm, and real. Lead with the answer. "
    "Keep it short in casual conversation, match the user's energy. "
    "Never open with filler or a formulaic acknowledgement like 'Great question!', "
    "'Got it!', 'Sure!', 'Certainly', or 'Of course' — answer directly and vary how "
    "you start. "
    "Respond in plain text only (never respond with JSON).\n\n"
    "WHO YOU ARE — THIS IS YOUR ENTIRE JOB:\n"
    "- You are an incredibly proactive, forward-thinking assistant. You assist the user: "
    "you understand what they want, hand the real work to the task manager, and then "
    "present and talk through whatever comes back. You make things happen by routing them "
    "to the crew — that is your superpower, and you use it eagerly.\n"
    "- Think of a top executive's personal assistant. When the boss says 'I want X done', "
    "you don't do the hands-on work yourself — you get it to the people who do it, keep an "
    "eye on it, and report back. You are the boss's proactive right hand. The boss is the "
    "user; the 'people' are the task manager and its worker bots, who can build literally "
    "anything — code, games, documents, charts, designs, drawings, research, even whole "
    "new capabilities and integrations.\n"
    "- You don't run commands, write files, or do the hands-on building inside this chat — "
    "the workers do that part. But you are NEVER stuck and you NEVER refuse. Anything the "
    "user wants made, built, designed, drawn, charted, rendered, fixed, researched, set "
    "up, or run, you hand to the task manager, where a worker actually does it and returns "
    "it to you to present (visuals and designs render live on the Canvas). So you never "
    "say 'I can't do that', 'I can't make visuals', or 'use Excel/Sheets/Canva instead' — "
    "you say 'on it' and hand it off.\n"
    "- Hand work off with your send_task tool, and be PROACTIVE about it: the moment you "
    "see the user wants something done, route it — don't make them ask twice. Pass their "
    "request through as they said it; the task manager reads the real ask and handles the "
    "details. You don't scope, plan, or design the work yourself — you recognize it's a "
    "task and pass it on.\n"
    "- CRITICAL: the send_task TOOL CALL is the ONLY thing that actually hands work off. "
    "Saying 'on it', 'I've handed that off', or 'I sent it to the task manager' WITHOUT "
    "calling send_task does nothing — the worker never starts, and your words are a false "
    "claim. So the instant you decide it's a task, CALL send_task in that same turn, THEN "
    "tell the user it's handed off. The tool call IS the handoff; your words only narrate "
    "it. Never tell the user you handed something off unless you actually called the tool. "
    "Internal task tags like '[task 3]' or '[task <ref>]' are ONLY for your update_task "
    "tool — never write them into your reply; refer to work in plain words.\n"
    "- You CAN read and look things up so you can answer directly. If they ask 'how's the "
    "evolve loop going?' you go read the relevant files/state and tell them. Reading to "
    "inform the conversation is part of your superpower.\n"
    "- MEMORY IS YOURS — never a task. You have remember and recall tools. The MOMENT the user "
    "tells you to remember something, or shares a fact, preference, name, or date worth keeping, "
    "CALL remember. When they ask what they told you, whether something is in your memory, or to "
    "think back, CALL recall and answer from what it returns. NEVER hand memory off to the task "
    "manager — remembering and recalling are YOUR OWN job, done inline right in the conversation.\n"
    "- You do NOT produce the deliverable yourself in the chat — no code, no HTML, no "
    "files, no finished documents typed into your reply. That's the worker's job; you hand "
    "it off and let the worker build and render it. You can of course explain, summarize, "
    "and talk it through.\n"
    "- Be honest about state. Hand work off eagerly — once you actually call send_task it "
    "is true to say you've handed it off. But never claim a worker has FINISHED, or that a "
    "result or file already exists, unless your context actually says so: proactive about "
    "starting, honest about finishing.\n"
    "- REPORTING FINISHED WORK (this is part of your job, not an exception to it): "
    "when your context explicitly states that a background worker has FINISHED a task "
    "and gives its result — for example a note that begins 'Background work just "
    "finished' — you SHOULD tell the user, in your own natural words, that it's done "
    "and what came of it. That is the 'report back' half of being their assistant. The "
    "worker did the work, not you, so never take credit for doing it yourself; and only "
    "report a completion your context actually confirms — never guess or assume one "
    "finished.\n"
    "- This is who you are, always. No setting changes it. Autonomy levels only "
    "affect how much gets handed off and how much asks for approval first — they "
    "NEVER turn you into something that does the work itself. There is no other "
    "mode for you and no alternative version of you.\n"
    "- You CAN keep chatting normally while background tasks run. If the user "
    "asks something casual while work is going, just answer it naturally.\n\n"
)


# Injected ONLY on turns where the send_task tool is NOT wired (autonomy L1/L2). The
# identity prompt above pushes hard to "say 'on it' and hand it off" and assumes the
# tool is always there. When it isn't, the model role-plays a hand-off it cannot do
# ("On it — I've handed that off, you'll have it shortly"), which is a flat lie: no
# worker ever starts. The backstop further down only fires when send_task EXISTS, so at
# L1/L2 nothing catches the false claim. Prevent it at the source, as the LAST line of
# the system prompt so it wins on recency. (honesty fix, 2026-06-27)
_NO_DISPATCH_HONESTY = (
    "DISPATCH UNAVAILABLE THIS TURN — READ THIS CAREFULLY: You do NOT have the "
    "send_task tool right now, so you literally cannot hand anything to the task "
    "manager and no worker can start this turn. Because of that you must NOT say 'on "
    "it', 'I've handed that off', 'I've sent it to the task manager', 'I'll get "
    "started', 'a worker is on it', or 'you'll have it shortly', and you must NOT imply "
    "that a file, document, drawing, or result is being made or already exists — every "
    "one of those would be a false claim. Instead, when the user wants something built "
    "or done, briefly and warmly OFFER: say what you'd hand to the crew, and that "
    "raising the autonomy level (to Agent or Full) lets you actually do it. Answering, "
    "explaining, reading the repo, and remembering all still work normally this turn — "
    "do those directly and fully."
)


class ReasoningSpecialist(BaseSpecialist):
    """General-purpose reasoning and conversation specialist."""

    @property
    def specialist_id(self) -> str:
        return "reasoning"

    @property
    def description(self) -> str:
        return (
            "Deep thinking, planning, multi-step analysis, general conversation. "
            "Handles anything that doesn't need specialised tools."
        )

    @property
    def capabilities(self) -> set[str]:
        return {
            "reasoning",
            "planning",
            "analysis",
            "conversation",
            "summarization",
            "explanation",
            "brainstorming",
        }

    async def _execute_impl(
        self,
        contract: DelegationContract,
        token: CapabilityToken,
        prompt: str,
        conversation_context: list[dict[str, Any]],
        memory_context: str,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "thinking", "text": "Reasoning through the request...", "phase": "reasoning"}

        # Thomas's identity is the single canonical constant (Calvin law).
        system = THOMAS_CHATBOT_SYSTEM_PROMPT
        # Autonomy-aware delegation posture. The identity above never changes (he
        # still never does the work himself); this only sets whether he ASKS before
        # handing off, which is exactly what the autonomy level is for. Threaded from
        # brain._dispatch_single via input_context so "Max autonomy" stops asking.
        try:
            autonomy = (getattr(contract, "input_context", None) or {}).get("autonomy") or {}
            directive = str(autonomy.get("directive") or "").strip()
            if directive:
                system += directive + "\n\n"
        except Exception:
            pass
        # Repo & self awareness + read-only capability (Calvin: "he has no idea who he
        # is" / "should be able to read the repo, not write"). Injected every turn.
        system += "\n" + _repo_self_context()
        if memory_context:
            system += f"Context from memory:\n{memory_context}\n\n"

        messages = [{"role": "system", "content": system}]
        # FIX (2026-03-18): Include ALL conversation context, not just last 10.
        # Previously [-10:] caused Thomas to forget names, topics, and context
        # from earlier in the conversation. Also filters out system-role messages
        # to prevent the orchestrator's routing prompt ("You are an orchestrator
        # brain...") from leaking as a visible message.
        for msg in conversation_context:
            if msg.get("role") == "system":
                continue  # Don't leak orchestrator system prompts
            if msg.get("role") == "user" and msg.get("content") == prompt:
                continue  # Skip duplicate of current prompt
            # Filter out internal orchestrator content that got persisted
            # in old sessions. These should NEVER be visible to the user.
            content = str(msg.get("content", ""))
            if "orchestrator brain" in content.lower():
                continue
            if "specialist(s) should handle" in content.lower():
                continue
            if content.strip().startswith('{"specialists"'):
                continue
            messages.append(msg)
        messages.append({"role": "user", "content": prompt})

        # send_task: the organic, no-regex way Thomas hands real work off. The
        # callback (wired by chat_v2 to the task manager) is threaded in via the
        # contract. When present, the MODEL decides — in the natural flow — whether
        # to call the tool. If it does, a REAL card is created, so any "handing
        # this off" it says is true; if it doesn't, it just talks. No regex, no
        # canned instant ack.
        send_task = None
        update_task = None
        remember = None
        recall = None
        try:
            _ctx = getattr(contract, "input_context", None) or {}
            send_task = _ctx.get("send_task")
            update_task = _ctx.get("update_task")
            remember = _ctx.get("remember")
            recall = _ctx.get("recall")
        except Exception:
            send_task = None
            update_task = None
            remember = None
            recall = None
        # Tools the chat layer may use: READ-ONLY repo tools (fs.read_file/list_dir/
        # search) so it can ground answers in the real repo, plus send_task to hand
        # actionable work off. It still never writes/builds — the token is scoped
        # read-only (brain._dispatch_single) and write/shell tools are never offered.
        tools: list[dict] | None = None
        if hasattr(self.llm, "stream_chat"):
            built = _read_tool_specs(self.tools)
            if send_task:
                built.append(SEND_TASK_TOOL)
            if update_task:
                built.append(UPDATE_TASK_TOOL)
            if remember:
                built.append(REMEMBER_TOOL)
            if recall:
                built.append(RECALL_TOOL)
            tools = built or None

        # No hand-off tool this turn (autonomy L1/L2) → clamp the eager "say 'on it'"
        # language so Thomas OFFERS instead of faking a hand-off it can't perform.
        # Appended last so it wins on recency over the identity prompt above.
        if not send_task:
            messages[0]["content"] += "\n\n" + _NO_DISPATCH_HONESTY

        response = ""
        dispatched_titles: list[str] = []
        task_action_verb = ""  # "cancelled"/"updated" when the model steers a running task
        handed_off = False
        try:
            if hasattr(self.llm, "stream_chat"):
                # Enough passes for a few reads then an answer; bounded so reads can't loop.
                max_passes = 6 if tools else 1
                for _pass in range(max_passes):
                    streamed_parts: list[str] = []
                    tool_ends: list[dict[str, str]] = []
                    stream_err: str | None = None
                    # Stream prose token-by-token, but hold back only a trailing run that
                    # could be a tool CALL the model writes as plain text ('send_task {…}' /
                    # '[update_task] {…}', sometimes after a sentence of prose). The instant
                    # the literal is confirmed we flush the prose before it and suppress the
                    # rest, so the raw JSON NEVER reaches the user — without chunking normal
                    # replies (the live "typing" effect is preserved).
                    hold = ""
                    suppress_textcall = False
                    async for stream_event in self.llm.stream_chat(messages=messages, tools=tools):
                        event_type = str(getattr(stream_event, "type", "") or "")
                        data = getattr(stream_event, "data", {}) or {}
                        if event_type == "token":
                            token_text = str(data.get("text", "") or "")
                            if not token_text:
                                continue
                            streamed_parts.append(token_text)
                            if suppress_textcall:
                                continue  # swallow the leaked JSON; executed after the stream
                            hold += token_text
                            m = _TEXT_TOOLCALL_START_RE.search(hold)
                            if m:
                                # Emit the prose before the literal (trim a dangling '[' or
                                # whitespace the call was wrapped in), then suppress the rest.
                                pre = re.sub(r"[\s\[]*$", "", hold[: m.start()])
                                if pre:
                                    yield {"type": "text", "text": pre}
                                suppress_textcall = True
                                hold = ""
                                continue
                            k = _safe_stream_prefix_len(hold)
                            if k:
                                yield {"type": "text", "text": hold[:k]}
                                hold = hold[k:]
                        elif event_type == "tool_call_end":
                            tool_ends.append(
                                {
                                    "id": str(data.get("id") or ""),
                                    "name": str(data.get("name") or ""),
                                    "arguments": str(data.get("arguments") or ""),
                                }
                            )
                        elif event_type == "error":
                            stream_err = str(data.get("error") or "Unknown streaming error")
                            break
                    # Flush the hold-back tail when it was just normal prose.
                    if hold and not suppress_textcall:
                        yield {"type": "text", "text": hold}
                        hold = ""
                    if stream_err:
                        yield {"type": "error", "error": f"Reasoning failed: {stream_err}"}
                        return

                    # The model wrote a tool call as TEXT (the JSON we just suppressed)
                    # instead of invoking it, so nothing happened. Honor the clear intent
                    # by calling the tool for real, then confirm honestly — never leave the
                    # raw JSON or a dead non-action.
                    if suppress_textcall and not tool_ends:
                        parsed = _parse_text_toolcall("".join(streamed_parts))
                        _name = parsed[0] if parsed else ""
                        _args = parsed[1] if parsed else {}
                        if _name == "send_task" and send_task:
                            _title = str(_args.get("title") or "").strip() or (
                                str(prompt or "").strip()[:60] or "New task"
                            )
                            _instructions = (
                                str(prompt or "").strip() or str(_args.get("instructions") or "").strip() or _title
                            )
                            _surface = str(_args.get("surface") or "").strip().lower()
                            if _surface not in ("canvas", "task"):
                                _surface = ""
                            try:
                                await send_task(title=_title, instructions=_instructions, surface=_surface)
                                dispatched_titles.append(_title)
                                handed_off = True
                                yield {"type": "task_request", "title": _title}
                                response = (
                                    "On it — drawing it on the canvas now."
                                    if _surface == "canvas"
                                    else "On it — handed that to the crew. You'll see it on the task card."
                                )
                            except Exception as exc:
                                response = f"I tried to hand that off but hit an error: {exc}"
                            yield {"type": "text", "text": response}
                            break
                        if _name == "update_task" and update_task:
                            _ref = str(_args.get("task_ref") or "").strip()
                            _upd = str(_args.get("update") or "").strip()
                            _cancel = bool(_args.get("cancel"))
                            try:
                                outcome = await update_task(task_ref=_ref, update=_upd, cancel=_cancel)
                            except Exception as exc:
                                outcome = {"ok": False, "error": str(exc)}
                            if isinstance(outcome, dict) and outcome.get("ok"):
                                handed_off = True
                                task_action_verb = "cancelled" if outcome.get("action") == "cancel" else "updated"
                                yield {"type": "task_update", "ok": True, "action": outcome.get("action")}
                                response = (
                                    "Done — I've cancelled that task; the worker is stopping."
                                    if task_action_verb == "cancelled"
                                    else "Done — I've passed that change to the running task."
                                )
                            else:
                                _err = (outcome or {}).get("error", "I couldn't match a running task to change.")
                                response = f"I couldn't update that task: {_err}"
                            yield {"type": "text", "text": response}
                            break
                        # No dispatch tool (L1/L2) or unparseable → never show raw JSON; offer honestly.
                        response = "I can hand that to the crew — raise the autonomy level and I'll start it."
                        yield {"type": "text", "text": response}
                        break

                    if tool_ends and tools:
                        assistant_tool_calls: list[dict[str, Any]] = []
                        tool_results: list[dict[str, Any]] = []
                        for tc in tool_ends:
                            name = tc["name"]
                            try:
                                args = json.loads(tc["arguments"] or "{}")
                            except Exception:
                                args = {}
                            if name == SEND_TASK_TOOL_NAME and send_task:
                                title = str(args.get("title") or "").strip() or "New task"
                                # Forward the USER'S RAW request to the task manager, NOT
                                # Thomas's reworded version. Thomas is chat-only and is told
                                # he "can't build", so when he re-defines a task he tends to
                                # hedge or mangle it. The task manager has no such baggage and
                                # reads the real ask correctly, so it won't fuck it up.
                                # (Calvin, 2026-06-26.) Thomas only flags "this is a task".
                                instructions = (
                                    str(prompt or "").strip() or str(args.get("instructions") or "").strip() or title
                                )
                                # The MODEL declares the surface (canvas vs task) — organic
                                # routing, not a regex. Empty => routing falls back to a tightened
                                # visual hint. (Calvin's no-keyword law, 2026-06-27.)
                                surface = str(args.get("surface") or "").strip().lower()
                                if surface not in ("canvas", "task"):
                                    surface = ""
                                try:
                                    await send_task(title=title, instructions=instructions, surface=surface)
                                    dispatched_titles.append(title)
                                    handed_off = True
                                    yield {"type": "task_request", "title": title}
                                    result_text = f"Task '{title}' created and handed to the task manager."
                                except Exception as exc:
                                    result_text = f"Task hand-off failed: {exc}"
                            elif name == UPDATE_TASK_TOOL_NAME and update_task:
                                # Re-direct a RUNNING task: the model picked which one by
                                # ref, so the update lands on the right task — not a guess.
                                task_ref = str(args.get("task_ref") or "").strip()
                                update_text = str(args.get("update") or "").strip()
                                cancel = bool(args.get("cancel"))
                                try:
                                    outcome = await update_task(task_ref=task_ref, update=update_text, cancel=cancel)
                                    if isinstance(outcome, dict) and outcome.get("ok"):
                                        handed_off = True
                                        verb = "cancelled" if outcome.get("action") == "cancel" else "updated"
                                        task_action_verb = verb
                                        yield {"type": "task_update", "ok": True, "action": outcome.get("action")}
                                        result_text = f"Task {verb} (the running worker will pick up the change)."
                                    else:
                                        err = (outcome or {}).get("error", "could not match a running task")
                                        result_text = f"Could not update that task: {err}"
                                except Exception as exc:
                                    result_text = f"Task update failed: {exc}"
                            elif name == REMEMBER_TOOL_NAME and remember:
                                # Thomas's OWN memory — stored inline, no task. Not a hand-off.
                                _mtext = str(args.get("text") or "").strip()
                                if _mtext:
                                    try:
                                        _saved = await remember(text=_mtext)
                                    except Exception as exc:
                                        _saved = False
                                        result_text = f"Couldn't save that to memory: {exc}"
                                    else:
                                        # Honesty: only claim a save if memory actually stored it.
                                        result_text = (
                                            f"Saved to your memory: {_mtext}"
                                            if _saved
                                            else "Memory is unavailable right now, so this was NOT saved — "
                                            "tell the user honestly that you couldn't store it."
                                        )
                                else:
                                    result_text = "Nothing to remember (no text was given)."
                            elif name == RECALL_TOOL_NAME and recall:
                                # Thomas looks it up himself and answers in this same turn.
                                _q = str(args.get("query") or "").strip()
                                try:
                                    _hit = await recall(query=_q)
                                except Exception as exc:
                                    result_text = f"Memory lookup failed: {exc}"
                                else:
                                    result_text = (
                                        f"From your memory:\n{_hit}"
                                        if _hit
                                        else "Nothing about that is in your memory yet — tell the user you don't have it."
                                    )
                            elif name in _READ_TOOL_NAMES:
                                # Token-gated read execution. The read-only token denies
                                # write/shell, so this can only ever read.
                                if not token.permits_tool(name):
                                    result_text = f"Permission denied: '{name}' (you have read-only access)."
                                elif self.tools and hasattr(self.tools, "execute"):
                                    try:
                                        res = await self.tools.execute(name, args)
                                        ok = bool(getattr(res, "ok", True))
                                        payload = getattr(res, "data", None) if ok else getattr(res, "error", None)
                                        result_text = str(payload if payload is not None else "")[:6000]
                                        yield {"type": "tool_result", "name": name, "ok": ok}
                                    except Exception as exc:
                                        result_text = f"Read failed: {exc}"
                                else:
                                    result_text = "No filesystem tools are available right now."
                            else:
                                # Anything else (write/shell/etc.) is off-limits to the chat layer.
                                result_text = f"'{name}' is not available to the chat layer (read-only)."
                            assistant_tool_calls.append(
                                {
                                    "id": tc["id"],
                                    "type": "function",
                                    "function": {"name": name, "arguments": tc["arguments"]},
                                }
                            )
                            tool_results.append({"role": "tool", "tool_call_id": tc["id"], "content": result_text})
                        # Feed results back so the model can read more or answer naturally.
                        messages.append(
                            {
                                "role": "assistant",
                                "content": "".join(streamed_parts),
                                "tool_calls": assistant_tool_calls,
                            }
                        )
                        messages.extend(tool_results)
                        if handed_off:
                            # Work was handed off (send_task/update_task): withdraw all
                            # tools so the next pass is a pure natural confirmation and the
                            # model cannot double-dispatch the same work.
                            tools = None
                        continue

                    response = "".join(streamed_parts).strip()
                    # BACKSTOP (cancel): the model said it stopped/cancelled a task but never
                    # called update_task, leaving the worker running — a false claim. If the
                    # user's request resolves to a real RUNNING task, do the cancel for real so
                    # the words become true. resolve gates it (subject/ordinal match) — an
                    # unrelated claim resolves to nothing and cancels nothing. (chat sweep 2026-06-27)
                    if not handed_off and update_task and _CLAIMS_CANCEL_RE.search(response or ""):
                        try:
                            _outcome = await update_task(task_ref=str(prompt or ""), update="", cancel=True)
                        except Exception:
                            _outcome = None
                        if isinstance(_outcome, dict) and _outcome.get("ok"):
                            handed_off = True
                            task_action_verb = "cancelled"
                            yield {"type": "task_update", "ok": True, "action": "cancel"}
                            if not response:
                                response = "Done — I've cancelled that task; the worker is stopping."
                    # BACKSTOP: the model claimed a hand-off in its words but never called
                    # send_task, so no worker would start. Complete the real hand-off with
                    # the user's RAW request. Only at L3+ (at L2 Thomas offers and waits for
                    # a yes). This executes the model's OWN stated decision — it does not
                    # classify whether the user's message is a task.
                    if not handed_off and send_task and _CLAIMS_HANDOFF_RE.search(response or ""):
                        try:
                            _alvl = int(
                                ((getattr(contract, "input_context", None) or {}).get("autonomy") or {}).get("level")
                                or 2
                            )
                        except Exception:
                            _alvl = 2
                        if _alvl >= 3:
                            _bt = str(prompt or "").strip()[:60] or "task"
                            try:
                                # Backstop: the model narrated a hand-off but didn't call the
                                # tool, so it never declared a surface — let routing fall back to
                                # the tightened visual hint (surface="").
                                await send_task(title=_bt, instructions=str(prompt or ""), surface="")
                                handed_off = True
                                dispatched_titles.append(_bt)
                                yield {"type": "task_request", "title": _bt}
                            except Exception:
                                pass
                    break
            else:
                response = await self._call_llm(messages, max_tokens=4_000)
        except Exception as exc:
            yield {"type": "error", "error": f"Reasoning failed: {exc}"}
            return

        if not response or not response.strip():
            if dispatched_titles:
                # Model handed work off but produced no confirmation text — emit a
                # short honest one (a true statement, not a pre-dispatch canned ack).
                response = "Handed that to the task manager — you'll see it on the task card."
                yield {"type": "text", "text": response}
            elif task_action_verb:
                # Model steered/cancelled a running task but produced no confirmation —
                # emit a true one (the update already succeeded). (chat sweep, 2026-06-27)
                response = (
                    "Done — I've cancelled that task; the worker is stopping."
                    if task_action_verb == "cancelled"
                    else "Done — I've passed that change to the running task."
                )
                yield {"type": "text", "text": response}
            else:
                yield {"type": "error", "error": "Model returned an empty response"}
                return
        elif not hasattr(self.llm, "stream_chat"):
            yield {"type": "text", "text": response}

        yield {"type": "done", "content": response, "iterations": 1}
