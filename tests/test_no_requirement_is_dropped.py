"""No requirement of yours is dropped from the contract a Build team works to (spec 2026-10-12 Part 1 item 10).

The contract reader dropped every requirement over 300 characters and everything past the 24th: 292 of 1,026
requirements (28%) in 38 of 43 saved asks. Now each is kept whole, however long and however many.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from tests.test_a_thomas_project_starts_without_chat import CLAUDE, URL, _client, w  # noqa: F401 -- w is the fixture
from thomas.core import acceptance_contract as ac
from thomas.core.acceptance_notes import THOMAS_NOTES_END, THOMAS_NOTES_START

NAMES = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliett", "Kilo",
         "Lima", "Mike", "November", "Oscar", "Papa", "Quebec", "Romeo", "Sierra", "Tango", "Uniform", "Victor",
         "Whiskey", "Xray", "Yankee", "Zulu", "Amber", "Cobalt", "Ivory", "Scarlet")  # fmt: skip
MANY = " ".join(f"Add the {name} button to the toolbar." for name in NAMES)
NOTED = "You must " + "keep every earlier project's files exactly as they are " * 8
LONG = (
    "Make the log viewer keep every line it has ever shown in the order it arrived with the time it arrived beside "
    "it and the name of the run that wrote it and the file it came from and the level it was written at and whether "
    "it was cut short and how long the original was so that someone reading it later can tell what happened without "
    "opening the raw file and without guessing which run wrote which line or when any of it arrived on the screen "
    "and keep all of this when the viewer is closed and opened again later the same day or the next morning"
)


def _requirements(prompt: str, workspace: Path) -> list[ac.ContractItem]:
    return [item for item in ac.build_contract(prompt, workspace, learned=[]) if item.kind == ac.KIND_REQUIREMENT]


def test_a_requirement_past_the_twenty_fourth_is_kept(tmp_path: Path) -> None:
    reqs = _requirements(MANY, tmp_path)

    assert len(NAMES) == 30 and len(reqs) == 30
    assert reqs[-1].item_id == "req:30" and reqs[-1].description == "Add the Scarlet button to the toolbar."


def test_a_long_requirement_is_kept_whole(tmp_path: Path) -> None:
    reqs = _requirements(f"{LONG}. Keep the old log readable.", tmp_path)

    assert len(LONG) > 300
    whole = [item for item in reqs if item.description == f"{LONG}."]
    assert len(whole) == 1 and whole[0].target == f"{LONG}."


def test_the_contract_block_shows_every_requirement_whole(tmp_path: Path) -> None:
    items = ac.build_contract(f"{MANY} {LONG}.", tmp_path, learned=[])

    block = ac.contract_prompt_block(items)

    reqs = [item for item in items if item.kind == ac.KIND_REQUIREMENT]
    assert f"{LONG}." in block and "Add the Scarlet button to the toolbar." in block
    assert block.count("- [judge] ") == len(reqs) == 31


def test_the_reader_and_the_contract_read_the_same_list(tmp_path: Path) -> None:
    prompt = f"{MANY} {LONG}.\n{THOMAS_NOTES_START}\n{NOTED}.\n{THOMAS_NOTES_END}\n"

    statements = ac.requirement_statements(prompt)

    assert statements == [item.description for item in _requirements(prompt, tmp_path)]
    assert len(statements) == 31 and all(NOTED[:40] not in statement for statement in statements), "notes never"


def test_thomas_notes_are_never_required(tmp_path: Path) -> None:
    """A guard: it passes on dev before this change and after it, because the contract never reads Thomas's notes."""
    prompt = f"Add the Alpha button to the toolbar.\n{THOMAS_NOTES_START}\n{NOTED}.\n{THOMAS_NOTES_END}\n"

    assert [item.description for item in _requirements(prompt, tmp_path)] == ["Add the Alpha button to the toolbar."]


def test_a_short_ask_gets_no_notice(w: SimpleNamespace) -> None:
    """A guard: a launch with no long requirement answers exactly as it did before (Task 9 adds the notice)."""

    async def scenario() -> dict:
        client = await _client(w)
        try:
            response = await client.post(URL, json={"request": "Make the Send button blue", "settings": CLAUDE})
            assert response.status == 200, await response.text()
            return await response.json()
        finally:
            await client.close()

    assert sorted(asyncio.run(scenario())) == ["conversation_id", "execution_id", "ok", "project_root"]
