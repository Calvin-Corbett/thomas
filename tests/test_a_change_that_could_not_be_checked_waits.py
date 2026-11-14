"""A change whose check, or second look, could not run waits on a durable record, never on your card unchecked.

The record and the settle that books it (thomas/server/hand_in_hold.py, thomas_project.settle_if_finished). Its
retries are tests/test_a_held_hand_in_is_tried_again.py; the check's causes are
tests/test_an_unavailable_check_names_its_cause.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests import hand_in_hold_support as support
from thomas.forge.anvil import forge_code_store
from thomas.server import capacity_ledger, hand_in_hold, precard, thomas_project


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> support.Project:
    return support.make_project(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The second-look pause a held row's words read lives in this test's own ledger folder, never the real one."""
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))


def _unsettled(project: support.Project) -> bool:
    work, _catalog, cid = project
    return forge_code_store.load_conversation(work, cid)["thomas_project"].get("settled_at") is None


def _settle_with(monkeypatch: pytest.MonkeyPatch, checked: precard.Checked) -> None:
    monkeypatch.setattr(thomas_project.green_handoff, "size_problems", lambda _eid: [])
    monkeypatch.setattr(precard.review, "held_check", lambda _eid: None)
    monkeypatch.setattr(precard, "check_for_hand_in", lambda _eid: checked)


def test_booking_survives_reload_without_a_process_task(project: support.Project) -> None:
    work, catalog, cid = project
    assert support.row(project) is None
    booked = support.book(project)
    saved = json.loads((catalog / ".thomas" / "evolve" / "agent" / hand_in_hold.NAME).read_text(encoding="utf-8"))
    assert saved == [booked]
    assert booked["project_root"] == str(work) and booked["cid"] == cid
    assert booked["gen"] == hand_in_hold.generation(forge_code_store.load_conversation(work, cid))
    assert (booked["state"], booked["tries"], booked["strikes"]) == ("checking", 1, 0)
    assert (booked["port"], booked["boot"], booked["chat"]) == (8899, "server-1", "chat-1")
    assert hand_in_hold.phase(work, catalog, cid)[0] == "waiting"
    assert _unsettled(project)


@pytest.mark.parametrize("step", ["check", "second look"])
def test_unavailable_step_is_paused_with_reason_and_not_settled(project: support.Project, step: str) -> None:
    work, catalog, cid = project
    support.book(project)
    held = hand_in_hold.hold(work, catalog, cid, step, "checker unavailable", costly=False)
    assert held is not None and support.row(project) == held
    assert (held["state"], held["step"], held["why"]) == ("held", step, "checker unavailable")
    assert (held["tries"], held["strikes"]) == (1, 0) and held["next_at"] > 0
    phase, words = hand_in_hold.phase(work, catalog, cid)
    assert phase == "paused" and "could not run" in words and "try 1" in words
    assert ("of 96" in words) == (step == "second look")
    assert _unsettled(project)


def test_duplicate_booking_and_duplicate_hold_cannot_reset_a_wait(project: support.Project) -> None:
    work, catalog, cid = project
    support.book(project)
    held = hand_in_hold.hold(work, catalog, cid, "check", "missing interpreter", costly=False)
    assert held is not None
    assert support.book(project, gen=held["gen"]) == held
    assert hand_in_hold.hold(work, catalog, cid, "second look", "different reason") is None
    assert support.row(project) == held and len(hand_in_hold.rows(catalog)) == 1


def test_costly_refusal_is_bounded_and_spent_is_not_silently_approved(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server import issue_ledger

    work, catalog, cid = project
    issues: list[dict[str, Any]] = []
    monkeypatch.setattr(issue_ledger, "record_issue", lambda **kwargs: issues.append(kwargs))
    monkeypatch.setattr(hand_in_hold, "MAX_STRIKES", 1)
    support.book(project)
    spent = hand_in_hold.hold(work, catalog, cid, "second look", "review could not finish", costly=True)
    assert spent is not None and spent["state"] == "spent" and spent["strikes"] == 1
    assert spent["next_at"] == 0 and support.row(project) == spent
    phase, words = hand_in_hold.phase(work, catalog, cid)
    assert phase == "ended" and words.startswith("Never handed in:")
    assert len(issues) == 1 and issues[0]["kind"] == "second_look_never_ran"
    assert issues[0]["context"]["conversation_id"] == cid
    assert support.tick(project) == [] and support.row(project) == spent
    assert _unsettled(project)


def test_low_disk_never_strikes(project: support.Project) -> None:
    work, catalog, cid = project
    support.book(project)
    held = hand_in_hold.hold(work, catalog, cid, "check", "the drive has 1 GB free", costly=False)
    assert held is not None and (held["state"], held["strikes"]) == ("held", 0)


def test_stale_turn_cannot_be_retried_or_overwrite_a_new_booking(project: support.Project) -> None:
    work, catalog, cid = project
    old = support.book(project)
    forge_code_store.append_user_turn(work, cid, "Please change it instead")
    assert hand_in_hold.hold(work, catalog, cid, "check", "checker unavailable", gen=old["gen"]) is None
    assert support.row(project) == old, "a stale check must not erase a hold before the tick handles steering"
    new = support.book(project)
    assert new["gen"] != old["gen"]
    assert hand_in_hold.drop(catalog, cid, old["gen"]) is False
    assert hand_in_hold.change(catalog, cid, old["gen"], None) is False
    assert support.row(project) == new


def test_compare_and_swap_preserves_a_more_recent_reason(project: support.Project) -> None:
    work, catalog, cid = project
    original = support.book(project)
    held = hand_in_hold.hold(work, catalog, cid, "second look", "reader unavailable", costly=False)
    assert held is not None
    assert hand_in_hold.change(catalog, cid, original["gen"], None, expected=original) is False
    assert support.row(project) == held
    assert hand_in_hold.drop(catalog, cid, held["gen"]) is True
    assert support.row(project) is None and hand_in_hold.phase(work, catalog, cid) is None


def test_retry_cannot_submit_after_its_booking_is_removed(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    booked = support.book(project)
    monkeypatch.setattr(thomas_project.green_handoff, "size_problems", lambda _eid: [])
    monkeypatch.setattr(precard, "check_for_hand_in", lambda _eid: pytest.fail("checked without booking"))
    monkeypatch.setattr(thomas_project.green_handoff, "settle", lambda *_a, **_k: pytest.fail("handed in"))
    assert hand_in_hold.drop(catalog, cid, booked["gen"])
    assert thomas_project.settle_if_finished(work, catalog, cid, expected_gen=booked["gen"]) is None


@pytest.mark.parametrize(
    ("cause", "costly"),
    [("incomplete", True), ("dev-side", True), ("unexpected", True), ("deadline", True), ("low-disk", False)],
)
def test_unavailable_check_cause_never_reaches_second_look_or_promoter(
    project: support.Project, monkeypatch: pytest.MonkeyPatch, cause: str, costly: bool
) -> None:
    work, catalog, cid = project
    support.book(project)
    _settle_with(monkeypatch, precard.Checked(precard.UNAVAILABLE, "not checked", cause=cause, costly=costly))
    monkeypatch.setattr(precard.review, "second_look", lambda *_a: pytest.fail("unchecked change reviewed"))
    monkeypatch.setattr(thomas_project.green_handoff, "settle", lambda *_a, **_k: pytest.fail("unchecked hand-in"))
    with pytest.raises(precard.CheckUnavailable) as caught:
        thomas_project.settle_if_finished(work, catalog, cid)
    assert caught.value.step == "check" and caught.value.costly is costly
    assert _unsettled(project) and support.row(project)["state"] == "checking"


@pytest.mark.parametrize("cause", ["off", "empty"])
def test_intentional_skip_does_not_raise_an_unavailable_check(
    project: support.Project, monkeypatch: pytest.MonkeyPatch, cause: str
) -> None:
    work, catalog, cid = project
    support.book(project)
    seen: list[str] = []
    _settle_with(monkeypatch, precard.Checked(precard.UNAVAILABLE, "not checked", cause=cause))

    def review(_eid: str, _goal: str, checked: Any) -> Any:
        seen.append(checked.cause)
        raise precard.ReviewUnavailable("no verdict")

    monkeypatch.setattr(precard.review, "second_look", review)
    monkeypatch.setattr(thomas_project.green_handoff, "settle", lambda *_a, **_k: pytest.fail("no verdict"))
    with pytest.raises(precard.ReviewUnavailable, match="no verdict"):
        thomas_project.settle_if_finished(work, catalog, cid)
    assert seen == [cause] and support.row(project)["state"] == "checking"


def test_unavailable_second_look_is_quiet_and_does_not_mark_settled(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    support.book(project)
    patch = "diff --git a/example.py b/example.py\n+changed\n"
    _settle_with(
        monkeypatch,
        precard.Checked(precard.PASSED, "tests passed", patch=patch, patch_sha256=precard.patch_sha256(patch)),
    )

    def offline(*_args: Any) -> Any:
        raise precard.ReviewUnavailable("reader offline")

    monkeypatch.setattr(precard.review, "second_look", offline)
    monkeypatch.setattr(thomas_project.green_handoff, "settle", lambda *_a, **_k: pytest.fail("handed in"))
    with pytest.raises(precard.ReviewUnavailable, match="reader offline"):
        thomas_project.settle_if_finished(work, catalog, cid)
    assert _unsettled(project) and support.row(project)["state"] == "checking"


def _hand_off(monkeypatch: pytest.MonkeyPatch, checked: precard.Checked) -> list[dict[str, Any]]:
    """Everything after both checks, faked so the hand-off's own arguments can be read."""
    seen: list[dict[str, Any]] = []
    _settle_with(monkeypatch, checked)
    monkeypatch.setattr(precard.review, "second_look", lambda _eid, _goal, found: found)
    monkeypatch.setattr(thomas_project, "_patch_files", lambda _eid: ["example.py"])
    monkeypatch.setattr(thomas_project.green_handoff, "await_verdict", lambda _eid: None)
    monkeypatch.setattr(thomas_project.green_handoff, "settle", lambda _eid, **kw: seen.append(kw) or None)
    monkeypatch.setattr(thomas_project.green_checkout, "find_green", lambda _eid: None)
    monkeypatch.setattr(thomas_project.green_handoff, "awaiting_verdict", lambda _eid: False)
    monkeypatch.setattr(thomas_project.forge_code_projects, "conversation_metadata", lambda *_a: {})
    monkeypatch.setattr(thomas_project.forge_code_projects, "forget_conversation", lambda *_a: None)
    return seen


def test_ratchet_summary_is_passed_through_only_after_both_checks(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    support.book(project)
    seen = _hand_off(monkeypatch, precard.Checked(precard.PASSED, "tests passed", patch="patch"))
    assert thomas_project.settle_if_finished(work, catalog, cid, summary="ratchet-proved candidate") is None
    assert len(seen) == 1 and seen[0]["summary"] == "ratchet-proved candidate"
    assert seen[0]["checked"] == "tests passed" and seen[0]["patch"] == "patch"
    stored = forge_code_store.load_conversation(catalog, cid)
    assert stored["thomas_project"]["summary"] == "ratchet-proved candidate"
    assert stored["thomas_project"].get("settled_at") is not None


def test_an_empty_change_is_handed_off_empty_and_not_read_again(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    support.book(project)
    seen = _hand_off(monkeypatch, precard.Checked(precard.UNAVAILABLE, "nothing to check", cause="empty"))
    thomas_project.settle_if_finished(work, catalog, cid)
    assert [kw["patch"] for kw in seen] == [""], "None would make the hand-off read the green again"


def test_your_stop_or_steer_during_the_check_hands_nothing_in(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    support.book(project)

    def check_then_steer(_eid: str) -> precard.Checked:
        thomas_project.hold_steer(cid, "do it the other way")  # your steer arrives while the check runs
        return precard.Checked(precard.FAILED, "a test failed", "tests/test_x.py::test_y")

    monkeypatch.setattr(thomas_project.green_handoff, "size_problems", lambda _eid: [])
    monkeypatch.setattr(precard.review, "held_check", lambda _eid: None)
    monkeypatch.setattr(precard, "check_for_hand_in", check_then_steer)
    monkeypatch.setattr(thomas_project.green_handoff, "settle", lambda *_a, **_k: pytest.fail("handed in"))
    monkeypatch.setattr(
        hand_in_hold, "still_current", lambda *_a, **_k: not thomas_project.held_steers(cid), raising=True
    )
    try:
        assert thomas_project.settle_if_finished(work, catalog, cid) is None  # no ChangeFailedCheck: no repair round
    finally:
        thomas_project.drop_steers(cid, 1)


def test_your_stop_during_the_second_look_leaves_no_copy_and_hands_nothing_in(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    support.book(project)
    _settle_with(monkeypatch, precard.Checked(precard.PASSED, "tests passed", patch="patch"))

    def look_then_stop(_eid: str, _goal: str, checked: precard.Checked) -> precard.Checked:
        thomas_project.request_stop(work, cid)  # your Stop arrives while the second model reads the change
        return checked

    monkeypatch.setattr(precard.review, "second_look", look_then_stop)
    monkeypatch.setattr(thomas_project.green_handoff, "settle", lambda *_a, **_k: pytest.fail("handed in"))
    assert thomas_project.settle_if_finished(work, catalog, cid) is None
    assert forge_code_store.load_conversation(catalog, cid) is None, "no copy that reads as handing over"
