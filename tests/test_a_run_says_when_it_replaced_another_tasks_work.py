"""Replacing another task's work must not be silent.

Measured on the owner's own workspace: 106 separate code tasks bound to one
folder, and `index.html` written by five of them — each silently replacing the
last, four builds gone with no record anywhere. The only surviving trace was
`haunted-arcade.css`, an orphaned stylesheet whose page no longer existed.

This does not prevent the write and does not decide where projects should live.
It answers a question the run report could not previously ask.
"""

from __future__ import annotations

import json
from pathlib import Path

from thomas.forge.anvil.forge_code_store import conversations_dir, files_written_by_another_task
from thomas.forge.anvil.run_report import build_run_report


def _task(root: Path, cid: str, files: list[str]) -> None:
    payload = {"id": cid, "turns": [{"role": "agent", "changed_files": files}]}
    (conversations_dir(root) / f"{cid}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_a_file_another_task_created_is_reported(tmp_path) -> None:
    _task(tmp_path, "fc_other", ["index.html"])

    assert files_written_by_another_task(tmp_path, "fc_mine", ["index.html"]) == ["index.html"]


def test_overwriting_your_own_earlier_output_is_not_reported(tmp_path) -> None:
    """Iterating on your own build is the normal way a task works."""
    _task(tmp_path, "fc_mine", ["index.html"])

    assert files_written_by_another_task(tmp_path, "fc_mine", ["index.html"]) == []


def test_a_file_both_tasks_touched_is_not_reported(tmp_path) -> None:
    """If this task has ever written it, this is iteration rather than a
    stranger's work being replaced — conservative on purpose, because a false
    alarm here would train the owner to ignore the line."""
    _task(tmp_path, "fc_other", ["index.html"])
    _task(tmp_path, "fc_mine", ["index.html"])

    assert files_written_by_another_task(tmp_path, "fc_mine", ["index.html"]) == []


def test_a_brand_new_file_is_not_reported(tmp_path) -> None:
    _task(tmp_path, "fc_other", ["index.html"])

    assert files_written_by_another_task(tmp_path, "fc_mine", ["brand-new.html"]) == []


def test_unreadable_conversation_records_do_not_break_the_check(tmp_path) -> None:
    (conversations_dir(tmp_path) / "fc_broken.json").write_text("{not json", encoding="utf-8")
    _task(tmp_path, "fc_other", ["index.html"])

    assert files_written_by_another_task(tmp_path, "fc_mine", ["index.html"]) == ["index.html"]


def test_it_reaches_the_run_report_as_an_open_risk() -> None:
    """Wired, not merely written. An unreferenced helper is exactly what the
    orphan check added today exists to catch."""
    report = build_run_report(
        goal="g",
        transcript="",
        changed_files=["index.html"],
        returncode=0,
        ok=True,
        outcome="completed",
        reason="",
        foreign_writes=["index.html"],
    )
    risks = [str(item.get("risk") or "") for item in report["open_risks"]]
    detail = " ".join(str(item.get("detail") or "") for item in report["open_risks"])

    assert any("another code task" in risk for risk in risks)
    assert "index.html" in detail


def test_it_does_not_claim_this_run_wrote_the_other_task_s_files() -> None:
    """`changed_files` is a shared folder's git diff, not a record of who wrote what.

    Any uncommitted file another task left behind lands in it untouched, so
    "overwritten here" asserts authorship the data cannot support.

    Measured: five conversations share `Code task 2026-07-30 1145`. The Godot FPS
    run held that folder 17:05-17:17 UTC while two other tasks wrote alpha.txt
    (17:09:44) and gamma.txt (17:15:45) into it. The FPS report listed all three
    and said it had overwritten them -- their mtimes are still those of the tasks
    that made them. Thomas allows eight simultaneous Code runs, so two runs
    sharing a folder is ordinary, not exotic.

    The risk must still FIRE -- work from another task really is mixed into this
    run's file list, and that is the thing worth knowing. Only the claim about
    who wrote it was more than the data knew.
    """

    report = build_run_report(
        goal="g",
        transcript="",
        changed_files=["index.html"],
        returncode=0,
        ok=True,
        outcome="completed",
        reason="",
        foreign_writes=["index.html"],
    )
    text = " ".join(
        f"{item.get('risk')} {item.get('detail')}" for item in report["open_risks"]
    ).lower()

    assert "another code task" in text, "the risk must still fire"
    assert "index.html" in text, "it must still name the file"
    assert "overwritten here" not in text, (
        "the report cannot know this run overwrote a file it may never have touched"
    )


def test_a_run_that_replaced_nothing_says_nothing() -> None:
    report = build_run_report(
        goal="g",
        transcript="",
        changed_files=["index.html"],
        returncode=0,
        ok=True,
        outcome="completed",
        reason="",
        foreign_writes=[],
    )
    risks = [str(item.get("risk") or "") for item in report["open_risks"]]

    assert not any("another code task" in risk for risk in risks)
