"""Two ways the claim tools failed an agent through no fault of its own, found 2026-11-09.

A task named ``boot speedups: port lookup`` made the plan folder ``...\\boot speedups: port lookup`` and Windows refused
it (WinError 267), after the claim was already written. And an agent that re-pointed its claim at a renamed task held
two Active Task rows, so releasing its claim failed, and the rows it left behind blocked every other agent's commit.
"""

from __future__ import annotations

from pathlib import Path

from scripts.crew.tasks import plan_metadata
from scripts.crew.workboard import claim_release, claim_utils


def test_a_task_name_with_characters_windows_refuses_still_makes_its_folder(tmp_path: Path) -> None:
    for task in ("boot: speedups", "a/b", 'what? "now" <ok>|*', "ends with a dot.", "  padded  "):
        rel = plan_metadata.default_artifact_path(task, "plans/tasks", "PLAN.md", repo_root=tmp_path)
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)  # the call that raised WinError 267
        target.write_text("x", encoding="utf-8")
        assert not set('<>:"\\|?*') & set(target.parent.name), target.parent.name
        assert not target.parent.name.endswith((".", " "))


def test_a_plain_task_name_keeps_its_folder_name() -> None:
    name = "[WIP][HSK-20261109-155640] boot speedups"
    assert plan_metadata.folder_name_for(name) == name


def _lines(*rows: str) -> list[str]:
    return [
        "## Agent Claims (Active)\n",
        "\n",
        "- none\n",
        "\n",
        "## Active Tasks\n",
        "\n",
        *[f"{row}\n" for row in rows],
        "\n",
        "## Issues / Blockers\n",
    ]


def test_releasing_an_agents_claim_drops_all_of_its_task_rows_and_only_its_own() -> None:
    lines = _lines(
        "- task_id=T-ONE; agent=me; scope=a; summary=first; status=in_progress",
        "- task_id=T-OTHER; agent=other; scope=b; summary=theirs; status=active",
        "- task_id=T-TWO; agent=me; scope=a; summary=renamed; status=in_progress",
    )
    ok, message = claim_release._release_all_active_tasks(lines, agent="me")
    text = "".join(lines)
    assert ok is True, message
    assert "T-ONE" in message and "T-TWO" in message
    assert "agent=me" not in text
    assert "T-OTHER" in text


def test_the_last_row_released_leaves_the_section_saying_none() -> None:
    lines = _lines("- task_id=T-ONE; agent=me; scope=a; summary=first; status=in_progress")
    ok, _ = claim_release._release_all_active_tasks(lines, agent="me")
    assert ok is True
    assert claim_utils.NONE_ENTRY + "\n" in lines


def test_an_agent_with_no_task_row_gets_a_plain_answer() -> None:
    lines = _lines("- task_id=T-OTHER; agent=other; scope=b; summary=theirs; status=active")
    assert claim_release._release_all_active_tasks(lines, agent="me") == (False, "no active tasks found")


def test_taking_over_another_agents_claim_still_refuses_when_it_has_two_rows() -> None:
    lines = _lines(
        "- task_id=T-ONE; agent=other; scope=a; summary=first; status=active",
        "- task_id=T-TWO; agent=other; scope=b; summary=second; status=active",
    )
    ok, message = claim_utils._release_active_task(lines, agent="other")
    assert ok is False and "multiple active tasks" in message


def test_a_release_clears_the_plan_rows_of_the_tasks_it_dropped(monkeypatch, tmp_path: Path) -> None:
    from scripts.crew.tasks import plans

    asked: dict[str, object] = {}

    def fake_sync(**kwargs):
        asked.update(kwargs)
        return True, {}

    monkeypatch.setattr(plans, "_sync_task_plans", fake_sync)
    board = tmp_path / "WORKBOARD.md"
    assert claim_release.sync_plans_after_release(board) == "plan rows synced"
    assert asked["apply"] is True and asked["workboard_path"] == board
    assert asked["plan_root"] == "plans/thomas/tasks" and asked["problem_root"] == "plans/thomas/problems"


def test_a_sync_that_fails_says_so_instead_of_claiming_success(monkeypatch, tmp_path: Path) -> None:
    from scripts.crew.tasks import plans

    monkeypatch.setattr(plans, "_sync_task_plans", lambda **_kw: (False, {"error": "board unreadable"}))
    said = claim_release.sync_plans_after_release(tmp_path / "WORKBOARD.md")
    assert said.startswith("plan rows not synced") and "board unreadable" in said
