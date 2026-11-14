"""A landed self-fix gets a name for its change, not the done check's review sentence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_store
from thomas.server import green_handoff, thomas_project

FRAGMENT = "changelog.d/the-project-listing-answers-fast.md"


def _turn(reply: str, *, changed_files: list[str] | None = None) -> dict[str, Any]:
    """Match the final-event turns used by the chat's self-fix card tests."""
    return {
        "role": "agent",
        "transcript": json.dumps({"fc": "final", "text": reply}),
        "reason": "Thomas replied without changing files",
        "changed_files": changed_files or [],
        "ok": True,
    }


def test_done_check_cannot_name_an_earlier_change_when_it_has_a_fragment() -> None:
    turns = [
        _turn("The project listing now answers quickly.", changed_files=["thomas/server/listing.py", FRAGMENT]),
        _turn("DONE: The existing change meets the goal, so I changed nothing in this pass."),
    ]
    assert thomas_project._subject(turns, ["thomas/server/listing.py", FRAGMENT]) == "The project listing answers fast"


def test_title_wins_even_when_the_patch_has_a_fragment() -> None:
    turns = [_turn("TITLE: **Composer `drafts` survive** reloads\nDONE: I checked it.")]
    assert thomas_project._subject(turns, [FRAGMENT]) == "Composer drafts survive reloads"


def test_readme_is_not_a_fragment_and_the_next_direct_fragment_is() -> None:
    turns = [_turn("DONE: I reviewed this change.")]
    assert thomas_project._subject(turns, ["changelog.d/README.md", FRAGMENT]) == "The project listing answers fast"
    assert thomas_project._subject(turns, ["changelog.d/README.md"]) == "Thomas self-change"
    assert thomas_project._subject(turns, ["changelog.d/nested/other.md", "changelog.d/clear_subject_here.md"]) == (
        "Clear subject here"
    )


def test_fragment_capitalises_only_its_first_letter() -> None:
    assert thomas_project._subject([], ["changelog.d/the-MCP-tools_load.md"]) == "The MCP tools load"


def test_title_keeps_snake_case_but_removes_emphasis_underscores() -> None:
    turns = [_turn("TITLE: Keep tool_calls in the _transcript_ and __drafts__")]
    assert thomas_project._subject(turns, [FRAGMENT]) == "Keep tool_calls in the transcript and drafts"


def test_without_a_fragment_skips_the_done_checks_first_person_sentence() -> None:
    turns = [_turn("The patch applied as given. Details follow."), _turn("DONE: I changed nothing. It was checked.")]
    assert thomas_project._subject(turns, ["thomas/server/listing.py"]) == "The patch applied as given"


def test_without_a_fragment_or_a_reply_not_about_the_team_uses_default() -> None:
    turns = [_turn("We checked the patch."), _turn("DONE: Our review passed. I changed nothing.")]
    assert thomas_project._subject(turns, []) == "Thomas self-change"


def test_done_sentence_loses_markdown_emphasis_without_a_fragment() -> None:
    turns = [_turn("DONE: The patch applied **exactly as given**. A second sentence.")]
    assert thomas_project._subject(turns) == "The patch applied exactly as given"


def test_subject_still_removes_paths_and_cuts_at_72_characters() -> None:
    turns = [_turn("TITLE: **The `project` list** at /server/web/index.html renders correctly")]
    assert thomas_project._subject(turns) == "The project list at renders correctly"
    long_title = [_turn("TITLE: " + "A" * 80)]
    assert thomas_project._subject(long_title) == "A" * 72 + "…"


def test_settle_uses_the_same_patch_files_for_subject_and_change_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, catalog_root = tmp_path / "green-work", tmp_path / "catalog"
    conv = forge_code_store.new_conversation(
        root, title="project listing", thomas_project={"execution_id": "thomas-subject"}
    )
    cid = conv["id"]
    for reply, files in [
        ("The project listing now answers quickly.", ["thomas/server/listing.py", FRAGMENT]),
        ("DONE: I reviewed the existing change without changing files.", []),
    ]:
        forge_code_store.append_agent_turn(
            root,
            cid,
            model="claude-cli",
            transcript=json.dumps({"fc": "final", "text": reply}),
            changed_files=files,
            returncode=0,
            ok=True,
            noop=not files,
            reason="files changed" if files else "Thomas replied without changing files",
            outcome="completed",
        )

    patch_files = ["thomas/server/listing.py", FRAGMENT, "tests/test_listing.py"]
    reads: list[str] = []
    monkeypatch.setattr(thomas_project, "_patch_files", lambda execution_id: reads.append(execution_id) or patch_files)
    calls: list[str] = []

    def _settle(execution_id: str, *, promote: bool, summary: str, chat: str, **kwargs: Any) -> Path:
        assert (execution_id, promote, chat) == ("thomas-subject", True, cid)
        calls.append(summary)
        return tmp_path / "inbox" / f"self-{execution_id}"

    monkeypatch.setattr(green_handoff, "settle", _settle)
    assert thomas_project.settle_if_finished(root, catalog_root, cid) == tmp_path / "inbox" / "self-thomas-subject"
    assert reads == ["thomas-subject"]
    assert calls == [
        "The project listing answers fast -- 3 file(s) changed: "
        "thomas/server/listing.py, changelog.d/the-project-listing-answers-fast.md, tests/test_listing.py"
    ]


def test_caller_supplied_summary_still_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, catalog_root = tmp_path / "green-work", tmp_path / "catalog"
    conv = forge_code_store.new_conversation(root, title="repair", thomas_project={"execution_id": "thomas-ratchet"})
    cid = conv["id"]
    forge_code_store.append_agent_turn(
        root,
        cid,
        model="claude-cli",
        transcript=json.dumps({"fc": "final", "text": "DONE: I reviewed it."}),
        changed_files=[FRAGMENT],
        returncode=0,
        ok=True,
        noop=False,
        reason="1 file(s) changed",
        outcome="completed",
    )
    calls: list[str] = []
    monkeypatch.setattr(thomas_project, "_patch_files", lambda execution_id: [FRAGMENT])
    monkeypatch.setattr(
        green_handoff,
        "settle",
        lambda execution_id, **kwargs: calls.append(kwargs["summary"]) or tmp_path / "inbox" / execution_id,
    )
    assert thomas_project.settle_if_finished(root, catalog_root, cid, summary="Ratchet's original summary")
    assert calls == ["Ratchet's original summary"]
