"""What a widget is made of: a short list of blocks, each one of eight kinds the page knows how to draw.

A widget is a card whose body is blocks. Thomas does not write markup for one. He names blocks and the page draws them
the way the rest of the app is drawn, so a widget he makes on the fly looks like one that shipped.

    text     words                                  {"type": "text", "text": "..."}
    reading  one big number or word, with a unit    {"type": "reading", "label": "Open cards", "value": 3}
    meter    a bar from 0 to 100, with a limit mark {"type": "meter", "label": "CPU", "value": 62, "mark": 90}
    rows     a list of name and value               {"type": "rows", "rows": [{"label": "Version", "value": "0.19"}]}
    steps    a checklist with a count               {"type": "steps", "steps": [{"label": "Build", "state": "done"}]}
    spark    a small line of recent values          {"type": "spark", "label": "CPU", "points": [12, 40, 33]}
    buttons  up to four buttons that answer         {"type": "buttons", "options": [{"id": "go", "label": "Run"}]}
    toggle   a switch for one plugin row            {"type": "toggle", "setting": "row:agents"}

A block may name a live reading in place of its own value (``"reading": "machine.cpu"``). The server fills it in each
time the widget refreshes (``thomas/server/attention_widgets.py`` holds the readings). A toggle's label and position are
never taken from whoever made the widget: the server writes them from the row's real name and state, so a switch
cannot be labelled as something it is not.

``docs/attention_widgets.md`` is the guide to making a widget and adding a template.
"""

from __future__ import annotations

import re
from typing import Any

KINDS = ("text", "reading", "meter", "rows", "steps", "spark", "buttons", "toggle")
STEP_STATES = ("done", "active", "pending", "blocked")
MAX_BLOCKS = 12
MAX_ROWS = 12
MAX_POINTS = 120
_SETTING = re.compile(r"^row:[a-z0-9_-]{1,60}$")
# What a live reading may fill in for each kind. Anything else it answers is dropped.
FILLS = {
    "text": ("text",),
    "reading": ("value", "unit", "hint"),
    "meter": ("value", "mark", "hint"),
    "rows": ("rows",),
    "steps": ("steps",),
    "spark": ("points", "unit"),
}


def _words(value: Any, limit: int) -> str:
    return " ".join(str("" if value is None else value).split())[:limit]


def _percent(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(min(max(float(value), 0.0), 100.0), 1)
    except (TypeError, ValueError):
        raise ValueError("a meter's value and mark are numbers from 0 to 100") from None


def _rows(value: Any, keys: tuple[str, ...]) -> list[dict[str, str]]:
    found = []
    for row in (value if isinstance(value, list) else [])[:MAX_ROWS]:
        if isinstance(row, dict) and _words(row.get("label"), 80):
            found.append({key: _words(row.get(key), 80) for key in keys if _words(row.get(key), 80)})
    return found


def clean_block(raw: Any) -> dict[str, Any]:
    """One block with only what its kind carries, or ``ValueError`` saying what is wrong with it."""
    if not isinstance(raw, dict):
        raise ValueError("a block is an object with a type")
    kind = str(raw.get("type") or "")
    if kind not in KINDS:
        raise ValueError(f"a block's type must be one of: {', '.join(KINDS)}")
    block: dict[str, Any] = {"type": kind}
    bound = _words(raw.get("reading"), 60) if kind in FILLS else ""
    if bound:
        block["reading"] = bound
    label = _words(raw.get("label"), 60)
    if label and kind != "toggle":
        block["label"] = label
    if kind == "text":
        block["text"] = str(raw.get("text") or "").strip()[:400]
    elif kind == "reading":
        block.update({"value": _words(raw.get("value"), 24), "unit": _words(raw.get("unit"), 16)})
        block["hint"] = _words(raw.get("hint"), 120)
    elif kind == "meter":
        block.update({"value": _percent(raw.get("value")), "mark": _percent(raw.get("mark"))})
        block["hint"] = _words(raw.get("hint"), 120)
    elif kind == "rows":
        block["rows"] = _rows(raw.get("rows"), ("label", "value", "note"))
    elif kind == "steps":
        steps = _rows(raw.get("steps"), ("label", "state", "note"))
        block["steps"] = [
            {**step, "state": step.get("state") if step.get("state") in STEP_STATES else "pending"} for step in steps
        ]
    elif kind == "spark":
        points = raw.get("points") if isinstance(raw.get("points"), list) else []
        try:
            block["points"] = [round(float(point), 2) for point in points[-MAX_POINTS:]]
        except (TypeError, ValueError):
            raise ValueError("a spark's points are numbers") from None
        block["unit"] = _words(raw.get("unit"), 16)
    elif kind == "buttons":
        options = raw.get("options") if isinstance(raw.get("options"), list) else []
        block["options"] = [
            {"id": _words(row.get("id"), 40) or f"option-{index + 1}", "label": _words(row.get("label"), 40)}
            for index, row in enumerate(options[:4])
            if isinstance(row, dict) and _words(row.get("label"), 40)
        ]
        if not block["options"]:
            raise ValueError("a buttons block needs at least one button with a label")
    else:
        setting = str(raw.get("setting") or "")
        if not _SETTING.match(setting):
            raise ValueError('a toggle names one plugin row, as "row:<its id>"')
        block["setting"] = setting
    return block


def clean_blocks(raw: Any) -> list[dict[str, Any]]:
    """A widget's blocks, cleaned. At least one, at most :data:`MAX_BLOCKS`."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("a widget needs a list of blocks")
    if len(raw) > MAX_BLOCKS:
        raise ValueError(f"a widget takes at most {MAX_BLOCKS} blocks")
    return [clean_block(block) for block in raw]


def fill(block: dict[str, Any], values: Any) -> dict[str, Any]:
    """``block`` with what its live reading answered, cleaned again. An answer that is not usable changes nothing."""
    allowed = FILLS.get(block["type"], ())
    if not isinstance(values, dict) or not allowed:
        return block
    merged = {**block, **{key: values[key] for key in allowed if key in values}}
    try:
        return clean_block(merged)
    except ValueError:
        return block
