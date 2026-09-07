"""Chat can answer "what did I ask you to make today" from its own record (2026-09-06).

Driving Chat as a user: a fresh chat asked "what did I ask you to build
earlier today, and what did I ask you to make into a CSV?" Thomas recalled an
unrelated ask from shared memory and honestly declined the rest. The morning's
three Build conversations and the CSV delegation were all on disk, listed by
the Library page, and out of the model's reach: no tool read that listing.
``recent_work.list`` reads the same Build conversations and chat executions
the Library shows, newest first, so the answer comes from the record.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_store
from thomas.tools import recent_work


def _build(root: Path, title: str, updated: str) -> None:
    conversation = forge_code_store.new_conversation(root, title=title)
    conversation["updated_at"] = updated
    forge_code_store._write_conversation(root, conversation)


def _tool(
    tmp_path: Path, executions: list[dict[str, Any]] | None = None, details: dict[str, dict[str, Any]] | None = None
) -> recent_work.RecentWorkTool:
    return recent_work.RecentWorkTool(
        conversation_roots=lambda: [tmp_path / "proj-a", tmp_path / "proj-b"],
        list_executions=lambda: list(executions or []),
        get_execution=lambda execution_id, root: (details or {}).get(execution_id),
        list_conversations=forge_code_store.list_conversations,
        now=lambda: "2026-09-06T15:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_builds_and_chat_deliverables_are_listed_newest_first(tmp_path: Path) -> None:
    (tmp_path / "proj-a").mkdir()
    (tmp_path / "proj-b").mkdir()
    _build(tmp_path / "proj-a", "Kanban board index.html", "2026-09-06T14:04:00+00:00")
    _build(tmp_path / "proj-b", "timer.html countdown timer", "2026-09-06T14:20:00+00:00")
    executions = [
        {
            "execution_id": "exec-1",
            "state": "failed",
            "created_at": "2026-09-06T14:36:21+00:00",
            "updated_at": "2026-09-06T14:37:10+00:00",
            "_record_root": str(tmp_path),
        }
    ]
    details = {
        "exec-1": {
            "summary": "Create a downloadable CSV file named planets.csv from the table",
            "salvaged_artifacts": ["planets.csv"],
            "state": "failed",
            "blocker": "unrecovered_tool_failure",
        }
    }
    result = await _tool(tmp_path, executions, details).execute({"limit": 10})
    assert result.ok, result.error
    text = result.data
    assert text.index("planets.csv") < text.index("timer.html") < text.index("Kanban board")
    assert "Build" in text and "Chat" in text
    assert "failed" in text and "planets.csv" in text  # the record's own verdict, not a guess
    assert "proj-b" in text  # where the build lives


@pytest.mark.asyncio
async def test_an_empty_record_says_so(tmp_path: Path) -> None:
    (tmp_path / "proj-a").mkdir()
    (tmp_path / "proj-b").mkdir()
    result = await _tool(tmp_path).execute({})
    assert result.ok and "nothing" in result.data.lower()


@pytest.mark.asyncio
async def test_the_day_window_drops_older_work(tmp_path: Path) -> None:
    (tmp_path / "proj-a").mkdir()
    (tmp_path / "proj-b").mkdir()
    _build(tmp_path / "proj-a", "Old tarot game", "2026-08-10T10:00:00+00:00")
    _build(tmp_path / "proj-b", "timer.html countdown timer", "2026-09-06T14:20:00+00:00")
    result = await _tool(tmp_path).execute({"days": 2})
    assert "timer.html" in result.data and "tarot" not in result.data


def test_the_tool_registers_for_chat() -> None:
    from thomas.server import tool_extensions

    seen: list[str] = []

    class Registry:
        def register(self, tool: Any) -> None:
            seen.append(tool.name)

    tool_extensions._register_recent_work(Registry())
    assert seen == ["recent_work.list"]


def test_the_tool_is_a_safe_read_for_chat() -> None:
    """The first live probe never called it: Chat offers tools by policy, and a
    tool outside the safe-read set is withheld at the default access level."""
    from thomas.server import chat_tool_policy_model as policy

    assert "recent_work.list" in policy._SAFE_READ_TOOLS
