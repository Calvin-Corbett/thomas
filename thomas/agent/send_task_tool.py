"""The `send_task` tool — how Thomas (the chat agent) hands real work off.

This is the organic, no-regex dispatch mechanism Calvin asked for. Instead of a
regex classifier deciding "is this a task?" behind the model's back (and the chat
then faking an "On it!" it didn't earn), the MODEL decides — in the natural flow
of the conversation — whether to call `send_task`. If it calls the tool, a real
background task card is created (so any "I'm handing this off" it says is TRUE).
If it doesn't, it just talks. No keyword trigger, no instant canned ack, no regex.

The tool is offered to the chat model only; the chat agent itself never executes
the work — calling `send_task` hands it to the task manager / worker bots.
"""

from __future__ import annotations

SEND_TASK_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "send_task",
        "description": (
            "Hand a concrete piece of work to the task manager, which runs it in "
            "the background as a live task card and reports back. Call this when "
            "the user wants something built, made, fixed, edited, implemented, "
            "researched, or run — work you (the chat layer) do not do yourself. "
            "Do NOT call it for ordinary conversation, questions you can just "
            "answer, or chit-chat. Decide naturally from the conversation; there "
            "is no keyword that triggers it. After you call it, a real card "
            "appears, so it is honest to tell the user it's been handed off."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "A short, specific name for the task as it should appear on "
                        "the card, e.g. 'Build a Pac-Man browser game' — not a "
                        "restatement of the whole message."
                    ),
                },
                "instructions": {
                    "type": "string",
                    "description": "The full instructions the worker needs to do the job.",
                },
            },
            "required": ["title", "instructions"],
        },
    },
}

SEND_TASK_TOOL_NAME = "send_task"

__all__ = ["SEND_TASK_TOOL", "SEND_TASK_TOOL_NAME"]
