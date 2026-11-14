"""Thomas's own notes to a Thomas project's team are never read as the request.

Every Thomas project's first message is your request followed by Thomas's notes: standing notes, lessons from earlier
hand-ins, and the files other running projects have changed. On 2026-09-27 the completion gate read that whole
message as the request, so the files other projects had changed became required outputs of this one ("`tests/
test_build_revoked_login_ends.py` exists and is non-empty when the work is done (the task names it as an output)")
and no project could finish. The notes now sit between markers the contract reads past, in the first message and in
Autopilot's goal, which quotes every message whole.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from tests.test_a_thomas_project_starts_without_chat import _client, _start, w  # noqa: F401 -- w is a fixture
from thomas.core.acceptance_contract import build_contract
from thomas.core.acceptance_notes import THOMAS_NOTES_END, THOMAS_NOTES_START
from thomas.server import thomas_project_words
from thomas.server.routes.autopilot_goal import goal_text

REQUEST = "Split thomas/server/web/settings.html and write the new styles to thomas/server/web/css/settings_split.css."
NOTES = (
    "Lessons from earlier hand-ins: record the change in changelog.d/lessons_only_fragment.md.\n\n"
    "Other Thomas projects are working in their own copies right now. Files they have changed so far:\n"
    "- thomas-other: tests/test_build_revoked_login_ends.py, docs/TASK_CARD_PROGRESS_FINDINGS.md"
)


def _outputs(text: str, root: Path) -> set[str]:
    return {item.item_id for item in build_contract(text, root) if item.item_id.startswith("output:")}


def _first_message() -> str:
    return f"{REQUEST}\n\n{THOMAS_NOTES_START}\n{NOTES}\n{THOMAS_NOTES_END}"


def test_the_files_other_projects_changed_are_not_this_projects_outputs(tmp_path: Path) -> None:
    outputs = _outputs(_first_message(), tmp_path)

    assert "output:thomas/server/web/css/settings_split.css" in outputs  # what was asked still counts
    assert "output:tests/test_build_revoked_login_ends.py" not in outputs
    assert "output:docs/TASK_CARD_PROGRESS_FINDINGS.md" not in outputs
    assert "output:changelog.d/lessons_only_fragment.md" not in outputs  # a path only the notes name


def test_a_message_from_before_the_markers_still_loses_the_other_projects_list(tmp_path: Path) -> None:
    unmarked = f"{REQUEST}\n\n{NOTES}"

    outputs = _outputs(unmarked, tmp_path)

    assert "output:thomas/server/web/css/settings_split.css" in outputs
    assert "output:tests/test_build_revoked_login_ends.py" not in outputs


def test_autopilots_goal_quotes_the_notes_and_the_contract_still_reads_past_them(tmp_path: Path) -> None:
    turns = [
        {"role": "user", "text": _first_message()},
        {"role": "agent", "text": "done"},
        {"role": "user", "text": "Also write a note to docs/settings_split.md."},
    ]
    goal = goal_text(turns)
    assert THOMAS_NOTES_START in goal and THOMAS_NOTES_END in goal

    outputs = _outputs(goal, tmp_path)

    assert {"output:thomas/server/web/css/settings_split.css", "output:docs/settings_split.md"} <= outputs
    assert "output:tests/test_build_revoked_login_ends.py" not in outputs


def test_the_team_notes_of_a_message_from_before_the_markers_are_not_the_request(tmp_path: Path) -> None:
    # The notes name docs/monolith_guard_baseline.json and `python -m pytest`; read as the request, every baseline
    # key became a field to consume and the whole suite a command that had to exit 0 (2026-09-27).
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "monolith_guard_baseline.json").write_text('{"version": 1, "hard_limits": {}}')
    unmarked = f"{REQUEST}\n\n{thomas_project_words.TEAM_NOTES}\n\n{NOTES}"
    quoted = goal_text(
        [
            {"role": "user", "text": unmarked},
            {"role": "agent", "text": "done"},
            {"role": "user", "text": "Also write a note to docs/settings_split.md."},
        ]
    )

    for text in (unmarked, quoted):
        ids = {item.item_id for item in build_contract(text, tmp_path)}
        assert "command:python -m pytest" not in ids
        assert not [i for i in ids if i.startswith("field:monolith_guard_baseline.json")]
        assert "output:thomas/server/web/css/settings_split.css" in ids  # the request still counts
    assert "output:docs/settings_split.md" in {item.item_id for item in build_contract(quoted, tmp_path)}


def test_a_thomas_project_sends_its_notes_between_the_markers(w: SimpleNamespace) -> None:  # noqa: F811
    async def scenario() -> str:
        client = await _client(w)
        try:
            await _start(client)
        finally:
            await client.close()
        return w.starts[-1]["message"]

    message = asyncio.run(scenario())
    start, end = message.index(THOMAS_NOTES_START), message.index(THOMAS_NOTES_END)
    assert start < message.index(thomas_project_words.LESSONS[0]) < end
    assert message.rstrip().endswith(THOMAS_NOTES_END)
