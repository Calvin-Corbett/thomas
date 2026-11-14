"""The two tools a run is lent while the attention row is on: show a card beside the conversation, and read its answer.

They write to and read from :mod:`thomas.core.attention_cards`. A card is drawn by whichever Thomas page is on screen,
so a run can reach you while you are looking at something else.
"""

from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult

_SHOW = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "One short line saying what this is, at most 120 characters."},
        "kind": {
            "type": "string",
            "enum": ["notice", "question", "reply", "image", "preview", "html", "widget"],
            "description": (
                "notice: words only. question: words and up to four buttons. reply: words and a box the user types an "
                "answer in. image: a picture (image_url). preview: a live page you built (preview_url). html: your own "
                "layout (html), drawn in a sandboxed frame with no network. widget: blocks the page draws in the app's own "
                "style (blocks); prefer it for readings, lists, progress and switches."
            ),
        },
        "body": {
            "type": "string",
            "description": "One or two plain sentences under the title, at most 600 characters.",
        },
        "tone": {
            "type": "string",
            "enum": ["info", "done", "warn", "ask"],
            "description": "The colour of the card's edge.",
        },
        "options": {
            "type": "array",
            "description": 'Buttons for a question, at most four: [{"id": "yes", "label": "Do it"}].',
            "items": {"type": "object", "properties": {"id": {"type": "string"}, "label": {"type": "string"}}},
        },
        "image_url": {
            "type": "string",
            "description": "A picture served by Thomas or from 127.0.0.1, or a data:image URL.",
        },
        "preview_url": {
            "type": "string",
            "description": "A page served by Thomas or from 127.0.0.1, shown live in the card.",
        },
        "html": {
            "type": "string",
            "description": "Your own layout, at most 20,000 characters. It cannot load anything from the network.",
        },
        "ttl_seconds": {
            "type": "number",
            "description": "How long it stays. 0 stays until closed. Default 300; a question or reply stays.",
        },
        "blocks": {
            "type": "array",
            "description": (
                "For a widget, up to 12 blocks. Each has a type: text, reading, meter, rows, steps, spark, buttons or "
                "toggle. Call attention_widget with no name for what each takes and the live readings a block can name."
            ),
            "items": {"type": "object"},
        },
        "every_seconds": {
            "type": "number",
            "description": "For a widget with live readings: how often to refill them.",
        },
        "key": {
            "type": "string",
            "description": "Showing a card with the key of an open one updates that card instead of adding another.",
        },
    },
    "required": ["title"],
}


class AttentionShowTool(Tool):
    name = "attention_show"
    category = "attention"
    description = (
        "Show the user a small card beside the conversation, on whichever Thomas page they are looking at. Use it for "
        "something they should see now and would otherwise miss: a task that finished, a result to look at, a question "
        "that blocks you, a warning. Do not use it for what you are already saying in your reply. It answers with the "
        "card's id; for a question or reply card, call attention_read with that id later to get the answer."
    )
    parameters = _SHOW

    def __init__(self, store: Any) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            card = self._store.show(args, source="thomas")
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))
        if card is None:
            return ToolResult(
                ok=True, data={"shown": False, "why": "the user closed a card with this key in the last ten minutes"}
            )
        return ToolResult(ok=True, data={"shown": True, "card_id": card["id"], "kind": card["kind"]})


class AttentionReadTool(Tool):
    name = "attention_read"
    category = "attention"
    description = (
        "Read what the user did with a card you showed: still open, closed without answering, or answered, with the "
        "button they chose or the words they typed. A card is forgotten an hour after it closes."
    )
    parameters = {
        "type": "object",
        "properties": {"card_id": {"type": "string", "description": "The id attention_show answered with."}},
        "required": ["card_id"],
    }

    def __init__(self, store: Any) -> None:
        self._store = store

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        card = self._store.read(str(args.get("card_id") or ""))
        if card is None:
            return ToolResult(ok=False, error="no such card: it expired, or it closed more than an hour ago")
        return ToolResult(ok=True, data={"state": card["state"], "answer": card["answer"], "title": card["title"]})


_BLOCKS_HELP = {
    "text": {"text": "words"},
    "reading": {
        "label": "what it is",
        "value": "one number or word",
        "unit": "optional",
        "hint": "optional small line",
    },
    "meter": {"label": "what it is", "value": "0 to 100", "mark": "optional limit, 0 to 100", "hint": "optional"},
    "rows": {"label": "optional heading", "rows": [{"label": "name", "value": "value", "note": "optional"}]},
    "steps": {"label": "optional heading", "steps": [{"label": "step", "state": "done | active | pending | blocked"}]},
    "spark": {"label": "what it is", "points": [1, 2, 3], "unit": "optional"},
    "buttons": {"options": [{"id": "go", "label": "Run it"}]},
    "toggle": {"setting": "row:<plugin row id>"},
}


class AttentionWidgetTool(Tool):
    name = "attention_widget"
    category = "attention"
    description = (
        "Summon a widget beside the conversation by its name, for example machine, thomas, plugins, switches or "
        "overview. A widget shows live readings and controls in the app's own style and stays until the user closes "
        "it. Call it with no name to list every widget there is, the live readings a block can name, and what each "
        "kind of block takes, which is what you need to make a new one with attention_show or attention_widget_save."
    )
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The widget to summon. Leave out to list them."}},
    }

    def __init__(self, store: Any, widgets: Any) -> None:
        self._store = store
        self._widgets = widgets

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        name = str(args.get("name") or "").strip()
        if not name:
            return ToolResult(ok=True, data={**self._widgets.catalogue(), "blocks": _BLOCKS_HELP})
        try:
            card = self._store.show(self._widgets.spec(name), source="thomas")
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))
        if card is None:
            return ToolResult(
                ok=True, data={"shown": False, "why": "the user closed this widget in the last ten minutes"}
            )
        return ToolResult(ok=True, data={"shown": True, "card_id": card["id"], "widget": name})


class AttentionWidgetSaveTool(Tool):
    name = "attention_widget_save"
    category = "attention"
    description = (
        "Save a widget you designed as a named template, so it can be summoned again with attention_widget. Give it "
        "a short lowercase name, a title, its blocks, and every_seconds if any block names a live reading. A block "
        "names a reading by carrying a reading field, such as machine.cpu, in place of its own value."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "2 to 40 lowercase letters, digits and dashes."},
            "title": {"type": "string", "description": "What the widget is called on screen."},
            "about": {"type": "string", "description": "One sentence saying what it is for."},
            "every_seconds": {"type": "number", "description": "How often live readings refill. 0 for none."},
            "blocks": {"type": "array", "description": "Up to 12 blocks.", "items": {"type": "object"}},
        },
        "required": ["name", "title", "blocks"],
    }

    def __init__(self, widgets: Any) -> None:
        self._widgets = widgets

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            saved = self._widgets.save(str(args.get("name") or ""), args)
        except (ValueError, OSError) as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(
            ok=True, data={"saved": str(args.get("name")), "title": saved["title"], "blocks": len(saved["blocks"])}
        )


def build_attention_tools(store: Any, widgets: Any = None) -> list[Tool]:
    tools: list[Tool] = [AttentionShowTool(store), AttentionReadTool(store)]
    if widgets is not None:
        tools += [AttentionWidgetTool(store, widgets), AttentionWidgetSaveTool(widgets)]
    return tools
