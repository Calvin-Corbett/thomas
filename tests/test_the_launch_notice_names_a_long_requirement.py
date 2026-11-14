"""A requirement over 300 characters is kept whole, and the launch answer names it (spec 2026-10-12 Part 1 item 10).

The judge rules on a long requirement as one item, so you are told which ones were long enough to be worth splitting.
They are named by length and opening words: the run numbers its requirements later, so a number given at launch could
be wrong.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tests.test_a_thomas_project_starts_without_chat import CLAUDE, URL, _client, w  # noqa: F401 -- w is the fixture
from tests.test_no_requirement_is_dropped import LONG
from thomas.core.acceptance_launch_notice import LONG_REQUIREMENT_CHARS, long_requirements, long_requirements_notice
from thomas.server.routes import self_project_routes

SECOND = "Make the export button write " + "every visible column and every hidden column " * 7 + "to the file"
EXACT = "Make the " + "x" * (LONG_REQUIREMENT_CHARS - 10) + "."
HUGE = "Make the viewer " + "keep every line it has ever shown " * 40 + "readable"


def test_each_long_requirement_is_named_once_in_order() -> None:
    assert len(EXACT) == LONG_REQUIREMENT_CHARS
    prompt = f"{LONG}. {SECOND}. {LONG}. {EXACT} Keep the old log readable."

    found = long_requirements(prompt)

    assert found == [
        {"chars": len(LONG) + 1, "opening": f"{LONG}."[:100] + "..."},
        {"chars": len(SECOND) + 1, "opening": f"{SECOND}."[:100] + "..."},
    ], "a requirement of exactly 300 characters is not long"


def test_the_notice_says_kept_whole_with_length_and_opening() -> None:
    found = long_requirements(f"{LONG}.")

    notice = long_requirements_notice(found)

    assert "kept whole" in notice.lower() and f"{len(LONG) + 1:,}" in notice and found[0]["opening"] in notice
    assert long_requirements_notice([]) == ""


def test_two_long_requirements_are_joined_in_order() -> None:
    found = long_requirements(f"{SECOND}. {LONG}.")

    notice = long_requirements_notice(found)

    named = [f'({item["chars"]:,} characters) "{item["opening"]}"' for item in found]
    assert [item["chars"] for item in found] == [len(SECOND) + 1, len(LONG) + 1], "in the order of the request"
    assert "2 of your requirements are longer than 300 characters" in notice
    assert "; ".join(named) in notice


def test_one_long_requirement_reads_in_the_singular_with_a_thousands_separator() -> None:
    found = long_requirements(f"{HUGE}.")

    notice = long_requirements_notice(found)

    assert len(HUGE) + 1 > 1000
    assert "1 of your requirements is longer than 300 characters" in notice and " are longer" not in notice
    assert f"({len(HUGE) + 1:,} characters)" in notice and "(1," in notice


def test_the_launch_answer_names_a_long_requirement(w: SimpleNamespace) -> None:
    async def scenario() -> dict:
        client = await _client(w)
        try:
            response = await client.post(
                URL, json={"request": f"{LONG}. Keep the old log readable.", "settings": CLAUDE}
            )
            assert response.status == 200, await response.text()
            return await response.json()
        finally:
            await client.close()

    body = asyncio.run(scenario())

    assert body["long_requirements"][0]["chars"] == len(LONG) + 1
    assert "kept whole" in body["notice"].lower()


def test_a_failing_notice_stops_the_launch_before_it_starts(
    w: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(found: object) -> str:
        raise RuntimeError("the notice could not be written")

    monkeypatch.setattr(self_project_routes, "long_requirements_notice", broken)

    async def scenario() -> int:
        client = await _client(w)
        try:
            response = await client.post(
                URL, json={"request": f"{LONG}. Keep the old log readable.", "settings": CLAUDE}
            )
            return response.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 500
    assert w.starts == [], "an error in the notice must never answer 500 for a project that is already running"
