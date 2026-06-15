"""Reasoning Specialist — deep thinking, planning, multi-step analysis.

The default/fallback specialist.  Handles general conversation,
complex reasoning, and multi-step planning tasks.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from thomas.core.send_task_tool import SEND_TASK_TOOL, SEND_TASK_TOOL_NAME
from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.base import BaseSpecialist

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
    "- You are a CHATBOT — the user's assistant. The one and only thing you do is "
    "talk with the user: answer questions, chat, and tell them about things.\n"
    "- Think of a top executive's personal assistant. When the boss says 'I want "
    "some code done on X', the assistant doesn't write the code and doesn't plan "
    "the project — they take the ask, get it handed to the people who do it, keep "
    "an eye on it, and report back. You are that assistant. The boss is the user; "
    "the 'people' are the task manager and its worker bots.\n"
    "- You CANNOT build, write code, edit files, run commands, deploy, change "
    "anything, OR plan/design/architect the work. You do not have those abilities "
    "— not in this reply, not ever. That is by design, not a limitation to "
    "apologize for or work around.\n"
    "- You CAN read and look things up so you can answer the user. If they ask "
    "'how's the evolve loop going?' you go read the relevant files/state and tell "
    "them. Reading to inform the conversation is your superpower; doing the work, "
    "or planning it, is not your job.\n"
    "- When the user wants something built, made, fixed, edited, implemented, "
    "researched, planned, or run, that is NOT something you do. It gets handed to "
    "the task manager — a separate crew of worker bots does the real work in the "
    "background, shown as a live task card. Your part is to understand what they "
    "want, let it be handed off, and keep talking.\n"
    "- NEVER claim you are doing, running, building, planning, started, created, "
    "or finished such work. Do NOT say 'I'll get that started', 'I created the "
    "file', 'a task card has been created', 'I'm checking your desktop', 'you "
    "should hear back soon', or 'done!' — you cannot start or do work, and you do "
    "not know whether a task was created. Instead, confirm you understand what "
    "they want and OFFER to hand it to the task manager — ask if they'd like you "
    "to (e.g. 'Want me to hand this to the task manager to build?'). If a task "
    "card actually appears, the worker is on it; you don't announce that yourself. "
    "If you genuinely can't help with something, say so plainly.\n"
    "- This is who you are, always. No setting changes it. Autonomy levels only "
    "affect how much gets handed off and how much asks for approval first — they "
    "NEVER turn you into something that does the work itself. There is no other "
    "mode for you and no alternative version of you.\n"
    "- You CAN keep chatting normally while background tasks run. If the user "
    "asks something casual while work is going, just answer it naturally.\n\n"
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
        try:
            send_task = (getattr(contract, "input_context", None) or {}).get("send_task")
        except Exception:
            send_task = None
        tools = [SEND_TASK_TOOL] if (send_task and hasattr(self.llm, "stream_chat")) else None

        response = ""
        dispatched_titles: list[str] = []
        try:
            if hasattr(self.llm, "stream_chat"):
                max_passes = 2 if tools else 1
                for _pass in range(max_passes):
                    streamed_parts: list[str] = []
                    tool_ends: list[dict[str, str]] = []
                    stream_err: str | None = None
                    async for stream_event in self.llm.stream_chat(messages=messages, tools=tools):
                        event_type = str(getattr(stream_event, "type", "") or "")
                        data = getattr(stream_event, "data", {}) or {}
                        if event_type == "token":
                            token_text = str(data.get("text", "") or "")
                            if token_text:
                                streamed_parts.append(token_text)
                                yield {"type": "text", "text": token_text}
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
                    if stream_err:
                        yield {"type": "error", "error": f"Reasoning failed: {stream_err}"}
                        return

                    st_calls = [tc for tc in tool_ends if tc["name"] == SEND_TASK_TOOL_NAME]
                    if st_calls and send_task and tools:
                        assistant_tool_calls: list[dict[str, Any]] = []
                        tool_results: list[dict[str, Any]] = []
                        for tc in st_calls:
                            try:
                                args = json.loads(tc["arguments"] or "{}")
                            except Exception:
                                args = {}
                            title = str(args.get("title") or "").strip() or "New task"
                            instructions = str(args.get("instructions") or "").strip() or prompt
                            try:
                                await send_task(title=title, instructions=instructions)
                                dispatched_titles.append(title)
                                yield {"type": "task_request", "title": title}
                                result_text = f"Task '{title}' created and handed to the task manager."
                            except Exception as exc:
                                result_text = f"Task hand-off failed: {exc}"
                            assistant_tool_calls.append(
                                {
                                    "id": tc["id"],
                                    "type": "function",
                                    "function": {"name": SEND_TASK_TOOL_NAME, "arguments": tc["arguments"]},
                                }
                            )
                            tool_results.append({"role": "tool", "tool_call_id": tc["id"], "content": result_text})
                        # Feed the tool result back so the model gives a natural,
                        # honest confirmation on the next pass (no tools second time).
                        messages.append(
                            {"role": "assistant", "content": "".join(streamed_parts), "tool_calls": assistant_tool_calls}
                        )
                        messages.extend(tool_results)
                        tools = None
                        continue

                    response = "".join(streamed_parts).strip()
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
            else:
                yield {"type": "error", "error": "Model returned an empty response"}
                return
        elif not hasattr(self.llm, "stream_chat"):
            yield {"type": "text", "text": response}

        yield {"type": "done", "content": response, "iterations": 1}
