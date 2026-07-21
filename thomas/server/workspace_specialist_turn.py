"""One direct model turn for a resident Thomas workspace specialist."""

from __future__ import annotations

import json
from typing import Any

from thomas.chat.conversation import ConversationManager
from thomas.chat.memory_layers import MemoryCoordinator
from thomas.server.workspace_specialist_operator import WorkspaceResidentOperator
from thomas.server.workspace_specialist_policy import WORKSPACE_LABELS, workspace_tool_spec


def _receipt_final_text(receipt: dict[str, Any]) -> str:
    if not bool(receipt.get("ok")):
        error = str(receipt.get("error") or "The requested action was not completed safely.")
        return f"I did not make that workspace change. {error}"
    action = str(receipt.get("action") or "workspace action")
    evidence = receipt.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    readback = evidence.get("after", evidence.get("observed", evidence))
    rendered = json.dumps(readback, ensure_ascii=False, sort_keys=True, default=str)[:4_000]
    return f"Verified from the server receipt: {action} succeeded. Current readback: {rendered}"


def _workspace_system_prompt(
    operator: WorkspaceResidentOperator,
    *,
    memory_text: str,
    workspace_context: dict[str, Any],
    persistent_instructions: str,
) -> str:
    label = WORKSPACE_LABELS[operator.workspace_key]
    actions = "\n".join(
        f"- {name}: {spec.description}" for name, spec in sorted(operator.policy.items())
    )
    prompt = f"""You are Thomas operating as the resident specialist inside {label}.

You work directly in this workspace through the operate_workspace tool. Never dispatch, delegate, create a task-manager task, call send_task/update_task, or claim that another worker will do the work. Stay inside {label}; if an action is not listed, say it is not available from this workspace yet. For mutations, call the tool and only claim success when its receipt says ok=true. Preserve the user's existing workspace state and explain denials plainly.

Available actions:
{actions}

Current server-owned workspace snapshot:
{json.dumps(workspace_context, ensure_ascii=False, default=str)[:12000]}
"""
    if memory_text:
        prompt += f"\nRelevant Thomas memory:\n{memory_text[:12000]}\n"
    if persistent_instructions:
        prompt += f"\nOwner-approved persistent instructions:\n{persistent_instructions[:8000]}\n"
    return prompt


async def run_workspace_resident_turn(
    *,
    llm: Any,
    conversation: ConversationManager,
    prompt: str,
    history_prompt: str,
    session_id: str,
    operator: WorkspaceResidentOperator,
    dispatcher: Any,
    memory_engine: Any,
    memory_policy: Any,
    persistent_instructions: str = "",
    images: list[dict[str, Any]] | None = None,
) -> ConversationManager:
    """Run one direct resident turn; no orchestration or delegation is reachable."""

    prior_messages = conversation.get_context_window(max_tokens=8_000)
    conversation = conversation.append_message("user", history_prompt)
    memory = MemoryCoordinator(memory_engine, session_id, context_budget=1_500, policy=memory_policy)
    memory_context = await memory.refresh(prompt=prompt, conversation=conversation, iteration=0)
    workspace_context = await operator.initial_context()
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": _workspace_system_prompt(
                operator,
                memory_text=memory_context.to_system_injection(),
                workspace_context=workspace_context,
                persistent_instructions=persistent_instructions,
            ),
        }
    ]
    messages.extend(msg for msg in prior_messages if msg.get("role") in {"user", "assistant"})
    user_content: Any = prompt
    if images:
        user_content = [{"type": "text", "text": prompt}, *images]
    messages.append({"role": "user", "content": user_content})

    tools: list[dict[str, Any]] | None = [workspace_tool_spec(operator.workspace_key)]
    final_text = ""
    tool_calls = 0
    last_receipt: dict[str, Any] | None = None
    for turn_pass in range(2):
        parts: list[str] = []
        selected_call: dict[str, str] | None = None
        async for stream_event in llm.stream_chat(messages=messages, tools=tools):
            event_type = str(getattr(stream_event, "type", "") or "")
            data = getattr(stream_event, "data", {}) or {}
            if event_type == "token":
                parts.append(str(data.get("text") or ""))
            elif event_type == "thinking":
                text = str(data.get("text") or "")
                if text:
                    await dispatcher.emit_thinking(text, phase="workspace")
            elif event_type == "tool_call_end" and selected_call is None:
                selected_call = {
                    "id": str(data.get("id") or f"workspace-call-{turn_pass}"),
                    "name": str(data.get("name") or ""),
                    "arguments": str(data.get("arguments") or "{}"),
                }
            elif event_type == "error":
                raise RuntimeError(str(data.get("error") or "Workspace model stream failed."))

        if selected_call is None:
            candidate = "".join(parts).strip()
            final_text = _receipt_final_text(last_receipt) if last_receipt is not None else candidate
            if final_text:
                await dispatcher.emit_text(final_text)
            break
        if last_receipt is not None:
            final_text = (
                "I stopped before a second workspace action because only one action is permitted "
                f"per turn. {_receipt_final_text(last_receipt)}"
            )
            await dispatcher.emit_text(final_text)
            break
        tool_calls += 1
        if selected_call["name"] != "operate_workspace":
            receipt = {
                "ok": False,
                "error": "Only operate_workspace is available to the workspace resident.",
            }
        else:
            try:
                args = json.loads(selected_call["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            await dispatcher.emit_tool_start("operate_workspace", selected_call["id"], args)
            receipt = await operator.execute(args)
        last_receipt = receipt
        await dispatcher.emit_tool_result(
            "operate_workspace",
            json.dumps(receipt, ensure_ascii=False, default=str),
            ok=bool(receipt.get("ok")),
            tool_id=selected_call["id"],
        )
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": "".join(parts),
                    "tool_calls": [
                        {
                            "id": selected_call["id"],
                            "type": "function",
                            "function": {
                                "name": "operate_workspace",
                                "arguments": selected_call["arguments"],
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": selected_call["id"],
                    "content": json.dumps(receipt, ensure_ascii=False, default=str),
                },
            ]
        )
        tools = None

    if not final_text:
        final_text = "I could not complete that workspace turn safely."
        await dispatcher.emit_text(final_text)
    conversation = conversation.append_message(
        "assistant",
        final_text,
        metadata={"specialists": [f"workspace:{operator.workspace_key}"], "mode": "workspace"},
    )
    await memory.capture_episode(
        turn_number=conversation.length // 2,
        user_message=history_prompt,
        assistant_response=final_text[:500],
        thinking="workspace_resident",
        tool_calls=["operate_workspace"] * tool_calls,
        specialist=f"workspace:{operator.workspace_key}",
    )
    await dispatcher.emit_done(
        session_id=session_id,
        conversation_version=conversation.version,
        thinking_summary="workspace_resident",
        iterations=1,
        tool_calls=tool_calls,
        specialists_used=[f"workspace:{operator.workspace_key}"],
    )
    return conversation


__all__ = ["run_workspace_resident_turn"]
