"""Widgets: the blocks they are made of, the live readings, the ones that ship, saving one, and the switches (2026-11-09).

You looked at the first cards and said they were notifications, and that what you meant "looks like the stuff on the
right": the Steps and Context window panels. "Show readings of all different things ... settings like they are widgets.
It can just summon widgets ... make a bunch and he can make them on the fly, make a template for the various kinds and
how to make a new template."

So a widget is blocks Thomas names and the page draws in the app's own style (``thomas.core.attention_blocks``), filled
from live readings (``thomas.server.attention_widgets``). Five ship (``thomas.server.attention_widget_templates``),
Thomas can make one on the fly or save one, and ``docs/attention_widgets.md`` is the guide, which the last test here
holds to the code. A change to ``thomas.server.rows.attention`` or ``thomas.server.routes.attention_routes`` runs these.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from thomas.core import attention_blocks as blocks
from thomas.core import attention_cards as cards
from thomas.server.attention_tools import build_attention_tools
from thomas.server.attention_widget_templates import BUILT_IN
from thomas.server.attention_widgets import READINGS, Widgets
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, Required

ROOT = Path(__file__).resolve().parents[1]
ROWS = [
    {"id": "agents", "title": "Agents page", "state": "active", "required": False},
    {"id": "work", "title": "Jobs and Work", "state": "off", "required": False},
    {"id": "chat", "title": "Chat", "state": "active", "required": True},
    {"id": "voice", "title": "Voice", "state": "failed", "required": False},
]


class _Runtime:
    def __init__(self) -> None:
        self.rows = [dict(row) for row in ROWS]
        self.pressed: list[tuple[str, str]] = []

    def report(self) -> dict[str, Any]:
        return {"rows": self.rows}

    async def _turn(self, row_id: str, state: str) -> dict[str, Any]:
        row = next(row for row in self.rows if row["id"] == row_id)
        if row["required"] and state == "off":
            raise Required(row_id)
        row["state"] = state
        self.pressed.append((row_id, state))
        return row

    async def turn_on(self, row_id: str) -> dict[str, Any]:
        return await self._turn(row_id, "active")

    async def turn_off(self, row_id: str) -> dict[str, Any]:
        return await self._turn(row_id, "off")


@pytest.fixture
def widgets(tmp_path: Path) -> Widgets:
    return Widgets({APP_RUNTIME_PLUGINS: _Runtime()}, tmp_path / "attention" / "widgets")


@pytest.fixture
def store(widgets: Widgets) -> cards.CardStore:
    held = cards.CardStore()
    held.resolver = widgets.resolve
    return held


def test_each_kind_of_block_keeps_only_what_it_takes() -> None:
    cleaned = blocks.clean_blocks([
        {"type": "text", "text": "  Hello  ", "value": 9},
        {"type": "reading", "label": "Open", "value": 3, "unit": "cards", "html": "<b>"},
        {"type": "meter", "label": "CPU", "value": 140, "mark": "90"},
        {"type": "rows", "rows": [{"label": "Version", "value": "0.19"}, {"value": "no label"}, "junk"]},
        {"type": "steps", "steps": [{"label": "Build", "state": "done"}, {"label": "Check", "state": "sideways"}]},
        {"type": "spark", "label": "CPU", "points": [1, "2.5", 3]},
        {"type": "buttons", "options": [{"id": "go", "label": "Run"}, {"label": ""}]},
        {"type": "toggle", "setting": "row:agents", "label": "Free money", "on": True},
    ])  # fmt: skip
    assert [block["type"] for block in cleaned] == list(blocks.KINDS)
    assert cleaned[0] == {"type": "text", "text": "Hello"}
    assert cleaned[1]["value"] == "3" and "html" not in cleaned[1]
    assert cleaned[2]["value"] == 100.0 and cleaned[2]["mark"] == 90.0, "a meter is held between 0 and 100"
    assert cleaned[3]["rows"] == [{"label": "Version", "value": "0.19"}]
    assert [step["state"] for step in cleaned[4]["steps"]] == ["done", "pending"]
    assert cleaned[5]["points"] == [1.0, 2.5, 3.0]
    assert cleaned[6]["options"] == [{"id": "go", "label": "Run"}]
    assert cleaned[7] == {"type": "toggle", "setting": "row:agents"}, "a toggle's words are never the maker's"


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        ([], "needs a list of blocks"),
        ([{"type": "iframe"}], "type must be one of"),
        ([{"type": "meter", "value": "lots"}], "numbers from 0 to 100"),
        ([{"type": "toggle", "setting": "/api/plugins/off"}], "names one plugin row"),
        ([{"type": "buttons", "options": []}], "at least one button"),
        ([{"type": "text", "text": "x"}] * 13, "at most 12 blocks"),
    ],
)
def test_a_block_that_is_not_one_of_the_eight_is_refused_with_the_reason(bad: list[Any], why: str) -> None:
    with pytest.raises(ValueError, match=why):
        blocks.clean_blocks(bad)


def test_a_reading_fills_only_the_fields_its_kind_takes() -> None:
    meter = blocks.clean_block({"type": "meter", "label": "CPU", "reading": "machine.cpu"})
    filled = blocks.fill(meter, {"value": 62.36, "mark": 90, "label": "Renamed", "rows": [1]})
    assert filled["value"] == 62.4 and filled["mark"] == 90.0 and filled["label"] == "CPU" and "rows" not in filled
    assert blocks.fill(meter, {"value": "not a number"}) == meter, "an answer that cannot be used changes nothing"
    assert blocks.fill(meter, None) == meter


def test_every_widget_that_ships_is_made_of_real_blocks_and_real_readings() -> None:
    assert sorted(BUILT_IN) == ["machine", "overview", "plugins", "switches", "thomas"]
    for name, template in BUILT_IN.items():
        assert template["title"] and template["about"].endswith("."), name
        cleaned = blocks.clean_blocks(template["blocks"])
        named = [block["reading"] for block in cleaned if block.get("reading")]
        assert [reading for reading in named if reading not in READINGS] == [], name
        assert template["every_seconds"] >= 2 or not named, f"{name} names live readings and never refreshes"


def test_a_summoned_widget_stays_open_and_is_filled_from_the_live_readings(
    widgets: Widgets, store: cards.CardStore
) -> None:
    shown = store.show(widgets.spec("plugins"))
    assert shown["kind"] == "widget" and shown["expires"] == 0.0 and shown["key"] == "widget-plugins"
    summary, not_on = shown["blocks"]
    assert summary["rows"] == [
        {"label": "On", "value": "2"},
        {"label": "Off", "value": "1"},
        {"label": "Failed", "value": "1"},
    ]
    assert not_on["rows"] == [{"label": "Jobs and Work", "value": "off"}, {"label": "Voice", "value": "failed"}]
    again = store.show(widgets.spec("plugins"))
    assert again["id"] == shown["id"] and len(store.open_cards()) == 1, "summoned twice, it is one widget"
    with pytest.raises(ValueError, match="no widget called nope. There are: "):
        widgets.spec("nope")


def test_an_open_widget_is_refilled_in_place_when_it_is_due(widgets: Widgets, store: cards.CardStore) -> None:
    shown = store.show(widgets.spec("plugins"))
    widgets.app[APP_RUNTIME_PLUGINS].rows[1]["state"] = "active"
    assert store.refresh() == 0, "not due yet"
    assert store.refresh(everything=True) == 1
    after = store.open_cards()[0]
    assert after["id"] == shown["id"]
    assert after["blocks"][0]["rows"][0] == {"label": "On", "value": "3"}
    kept = after["source_blocks"][0]
    assert kept["reading"] == "plugins.summary" and kept["rows"] == [], "what it was made from is kept, unfilled"


def test_a_switch_is_labelled_from_the_row_and_turns_it(widgets: Widgets, store: cards.CardStore) -> None:
    made = {
        "kind": "widget",
        "title": "Mine",
        "blocks": [{"type": "toggle", "setting": f"row:{row}"} for row in ("work", "chat", "gone")],
    }
    work, chat, gone = store.show(made)["blocks"]
    assert (work["label"], work["on"], work["locked"]) == ("Jobs and Work", False, False)
    assert (chat["label"], chat["on"], chat["locked"]) == ("Chat", True, True), (
        "a row that cannot be turned off is locked"
    )
    assert gone["locked"] is True and "gone" in gone["label"]
    asyncio.run(widgets.press("row:work", True))
    assert widgets.app[APP_RUNTIME_PLUGINS].pressed == [("work", "active")]
    with pytest.raises(ValueError, match="cannot be turned off"):
        asyncio.run(widgets.press("row:chat", False))
    with pytest.raises(ValueError):
        asyncio.run(widgets.press("row:gone", True))
    assert widgets.app[APP_RUNTIME_PLUGINS].pressed == [("work", "active")], "a refused press turns nothing"


def test_thomas_lists_what_there_is_summons_one_makes_one_and_saves_one(
    widgets: Widgets, store: cards.CardStore, tmp_path: Path
) -> None:
    show, read, widget, save = build_attention_tools(store, widgets)
    assert [tool.name for tool in (show, read, widget, save)] == [
        "attention_show",
        "attention_read",
        "attention_widget",
        "attention_widget_save",
    ]
    listed = asyncio.run(widget.execute({})).data
    assert [row["name"] for row in listed["templates"]] == sorted(BUILT_IN)
    assert [row["name"] for row in listed["readings"]] == sorted(READINGS)
    assert sorted(listed["blocks"]) == sorted(blocks.KINDS), "every kind of block is described to him"

    assert asyncio.run(widget.execute({"name": "machine"})).data["widget"] == "machine"
    made = asyncio.run(
        show.execute(
            {
                "title": "Deploy",
                "kind": "widget",
                "blocks": [
                    {"type": "steps", "steps": [{"label": "Build", "state": "done"}]},
                    {"type": "buttons", "options": [{"id": "ship", "label": "Ship it"}]},
                ],
            }
        )
    )
    assert made.ok and made.data["kind"] == "widget"
    store.act(made.data["card_id"], "choose", "ship")
    assert asyncio.run(read.execute({"card_id": made.data["card_id"]})).data["answer"]["label"] == "Ship it"

    kept = asyncio.run(
        save.execute(
            {
                "name": "my-plugins",
                "title": "My plugins",
                "every_seconds": 5,
                "blocks": [{"type": "rows", "reading": "plugins.not_on"}],
            }
        )
    )
    assert kept.ok and kept.data == {"saved": "my-plugins", "title": "My plugins", "blocks": 1}
    assert (
        json.loads((tmp_path / "attention" / "widgets" / "my-plugins.json").read_text("utf-8"))["title"] == "My plugins"
    )
    after_a_restart = Widgets(widgets.app, widgets.folder)
    assert "my-plugins" in after_a_restart.templates(), "a saved widget is read back from the data folder"
    assert asyncio.run(widget.execute({"name": "my-plugins"})).ok
    for name, why in (("machine", "a widget that ships"), ("../x", "lowercase letters"), ("A", "lowercase letters")):
        refused = asyncio.run(save.execute({"name": name, "title": "x", "blocks": [{"type": "text", "text": "x"}]}))
        assert not refused.ok and why in refused.error, name


def test_every_kind_of_block_is_drawn_in_the_apps_own_style() -> None:
    out = subprocess.run(
        ["node", str(ROOT / "tests" / "web_node" / "attention_widgets.mjs"),
         str(ROOT / "thomas" / "server" / "web" / "js" / "attention_widget_view.js")],
        capture_output=True, check=False, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {
        "everyBlockDraws": True,
        "wordsAreEscaped": True,
        "readingsRefillInPlace": True,
    }
    css = (ROOT / "thomas" / "server" / "web" / "css" / "attention_cards.css").read_text("utf-8")
    assert "border-left: 3px" not in css and "--attn-edge" not in css, "no coloured edge: you said it looked generic"
    assert "border-radius: 14px" in css and "var(--c-menu-bg" in css, (
        "the Context window panel's own surface and corner"
    )


def test_the_guide_lists_every_block_reading_and_shipped_widget() -> None:
    guide = (ROOT / "docs" / "attention_widgets.md").read_text("utf-8")
    for name in (*blocks.KINDS, *READINGS, *BUILT_IN):
        assert f"| `{name}` |" in guide, f"docs/attention_widgets.md has no row for {name}"
    for place in (
        "attention_widget_templates.py",
        "attention_widgets.py",
        "attention_blocks.py",
        "attention_widget_view.js",
    ):
        assert place in guide, f"the guide does not say where {place} comes in"
