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
            "answer, or chit-chat. CRITICAL: do NOT call send_task to STOP, CANCEL, "
            "or CHANGE work that is ALREADY running (anything shown in your "
            "background-work list) — that spawns a wrong new task. Use update_task "
            "for steering or cancelling an in-flight task; send_task is only for NEW "
            "work. Decide naturally from the conversation; there is no keyword that "
            "triggers it. After you call it, a real card appears, so it is honest to "
            "tell the user it's been handed off. "
            "You do NOT scope, plan, design, or define the work — the task manager "
            "and its worker bots read the user's real request and handle the details. "
            "Your only job is to recognize it's a task and pass it through."
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
                    "description": (
                        "What the user actually asked for, in their OWN words — pass the "
                        "real request straight through. Do NOT redefine it, narrow it, add "
                        "'I can't'/'visual content' caveats, or substitute your own plan. "
                        "The task manager interprets the real ask itself."
                    ),
                },
                "surface": {
                    "type": "string",
                    "enum": ["canvas", "task"],
                    "description": (
                        "Where the work should appear. Use 'canvas' ONLY when the user wants "
                        "a single visual artifact rendered live on the Canvas — a chart, graph, "
                        "diagram, flowchart, logo, icon, poster, mockup, illustration, or UI design "
                        "they watch draw itself. Use 'task' (the default) for everything else: "
                        "documents, plans, timelines, schemas, PDFs, resumes, research, writing, "
                        "code, files, or anything multi-step. When unsure, choose 'task'."
                    ),
                },
            },
            "required": ["title", "instructions"],
        },
    },
}

SEND_TASK_TOOL_NAME = "send_task"


# The `update_task` tool — how Thomas RE-DIRECTS work already running in the background.
# The user often refines or corrects an in-flight task ("actually make it blue", "also
# add a leaderboard", "stop that one"). Thomas was bad at this: with only send_task it
# either spawned a wrong NEW task or did nothing. This tool lets the MODEL — which has
# the full conversation and the background-work list (each item tagged [task <ref>]) —
# pick the RIGHT running task and route the change to it, instead of a blind heuristic
# guessing which task the user meant. (Calvin: "a skill where he tells the task manager
# 'that one task — the user wants this actually'.")
UPDATE_TASK_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "update_task",
        "description": (
            "Send a follow-up instruction to a task that is ALREADY running in the "
            "background — use this (NOT send_task) when the user is refining, "
            "correcting, or stopping work already in flight ('actually make it blue', "
            "'also add a leaderboard', 'cancel that one'). Identify the task by the "
            "[task <ref>] shown in the background-work list in your context; pick the "
            "one the user is referring to from the conversation. Set cancel=true to "
            "stop a task instead of changing it. Only running tasks can be updated."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_ref": {
                    "type": "string",
                    "description": (
                        "The [task <ref>] of the running task to update, copied from the "
                        "background-work list in your context."
                    ),
                },
                "update": {
                    "type": "string",
                    "description": (
                        "The new or changed instruction for that task, in plain language. "
                        "Leave empty only when cancel=true."
                    ),
                },
                "cancel": {
                    "type": "boolean",
                    "description": "Set true to stop/cancel the task instead of updating it.",
                },
            },
            "required": ["task_ref"],
        },
    },
}

UPDATE_TASK_TOOL_NAME = "update_task"


# Memory is THOMAS'S OWN capability — not a task. Calvin: "he should be the one able to use
# it, not a task manager; he shouldn't have to rely on a task." So Thomas gets first-class
# remember/recall tools he uses INLINE in the conversation, and is told never to dispatch
# memory work. (Calvin, 2026-06-27.)
REMEMBER_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "remember",
        "description": (
            "Save something to YOUR OWN long-term memory so you can recall it later. Call this "
            "the moment the user tells you to remember something, or shares a fact, preference, "
            "name, date, or detail worth keeping ('remember I like blue', 'my dog is named Rex', "
            "'the deadline is Friday'). This is YOUR memory — you store it yourself; you NEVER "
            "hand remembering off to a task. After you call it, tell the user you've got it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "The fact to remember as one clear standalone sentence, e.g. "
                        "'Calvin's favorite color is blue' (not 'blue')."
                    ),
                },
            },
            "required": ["text"],
        },
    },
}
REMEMBER_TOOL_NAME = "remember"

RECALL_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "recall",
        "description": (
            "Search YOUR OWN memory for something. Call this whenever the user asks what they "
            "told you, whether something is in your memory, or to think back ('what did I say "
            "about X', 'do you remember my address', 'is X in your memory'). This is YOUR memory "
            "— you look it up yourself; you NEVER hand recall off to a task. Use the result to "
            "answer the user directly; if nothing relevant comes back, say so plainly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look up, in a few words, e.g. 'favorite color' or 'project deadline'.",
                },
            },
            "required": ["query"],
        },
    },
}
RECALL_TOOL_NAME = "recall"


# Thomas's bounded inline operating surface. This intentionally names product
# actions rather than exposing the full registry: the V2 server maps each action
# to an existing tool behind guardrails and returns a post-action evidence receipt.
OPERATE_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "operate",
        "description": (
            "Perform a small, reversible action that belongs to Thomas himself instead of "
            "creating a background task. Use this for reading, listing, or changing the "
            "user's Thomas preferences when they ask. Never use it for files, shell commands, "
            "external messages, purchases, account changes, or artifact creation; send those "
            "to the task manager. A successful call returns effect evidence including readback."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["preferences.get", "preferences.list", "preferences.set"],
                    "description": "The bounded Thomas-owned action to perform.",
                },
                "key": {
                    "type": "string",
                    "description": "Preference key for preferences.get or preferences.set.",
                },
                "value": {
                    "description": "New preference value for preferences.set.",
                },
            },
            "required": ["action"],
        },
    },
}
OPERATE_TOOL_NAME = "operate"

__all__ = [
    "SEND_TASK_TOOL",
    "SEND_TASK_TOOL_NAME",
    "UPDATE_TASK_TOOL",
    "UPDATE_TASK_TOOL_NAME",
    "REMEMBER_TOOL",
    "REMEMBER_TOOL_NAME",
    "RECALL_TOOL",
    "RECALL_TOOL_NAME",
    "OPERATE_TOOL",
    "OPERATE_TOOL_NAME",
]
