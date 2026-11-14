"""Every Thomas project's team is told what the checks before your card kept finding.

You said on 2026-09-25: "he is really dumb like it doenst seem like he is learning anything". Each Thomas project
started from the same blank brief, so what one team was sent back for -- a changelog sentence the code did not bear
out, a test that still passed with its fix taken out, ruff never run -- the next team did again. The lessons now
ride in the notes every project's first message carries, through the real start route.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tests.test_a_thomas_project_starts_without_chat import _client, _start, w  # noqa: F401 -- w is a fixture
from thomas.forge.anvil import run_channel_mcp
from thomas.server import thomas_project_words


def test_the_lessons_reach_the_team_through_the_start_route(w: SimpleNamespace) -> None:  # noqa: F811
    async def scenario() -> str:
        client = await _client(w)
        try:
            await _start(client)
        finally:
            await client.close()
        return w.starts[-1]["message"]

    message = asyncio.run(scenario())
    assert len(thomas_project_words.LESSONS) == 6
    for lesson in thomas_project_words.LESSONS:
        assert lesson in message
    for must in ("ruff check", "tests/test_architecture.py", "watch the test fail", "conflict marker", "by id"):
        assert must in message


def test_the_delete_tool_it_names_is_the_one_an_editing_run_is_offered() -> None:
    server, tool = run_channel_mcp.DELETE_TOOL_NAME.split("__")[1:]
    assert server == run_channel_mcp.SERVER_NAME
    assert tool in {entry["name"] for entry in run_channel_mcp._tool_list(offer_delete=True)}
    assert run_channel_mcp.DELETE_TOOL_NAME in thomas_project_words.TEAM_NOTES


def test_a_team_proves_its_change_with_the_files_that_cover_it_not_the_whole_suite() -> None:
    """On 2026-10-26 four teams were steered off test runs they built themselves -- 138-file batches, a hand-made
    ``python -c`` harness, two check.run calls that hit the 10-minute limit -- after this lesson told them to run
    every test file that imports what they changed. The check before the card already runs that set, in parallel."""
    first = thomas_project_words.LESSONS[0]
    assert "check.run" in first and "at most 15 files" in first and "whole suite" in first
    assert "every test file that imports a module you changed" not in first
