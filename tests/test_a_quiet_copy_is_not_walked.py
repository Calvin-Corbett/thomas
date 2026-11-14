"""A copy no run has worked in lately is not walked again for every listing and every project start.

On 2026-11-13 Thomas had 228 copies of his source and 211 of them had not been touched for three days. The list of
projects and every project start read "what the other projects are changing" by walking every file of every copy.
The server spent a whole processor on it all day, and a new project's team began 6 to 10 minutes after it was asked
for (``bind_s`` 375 to 592 s in the step log).
"""

from __future__ import annotations

import os
import time
from collections import Counter
from pathlib import Path

import pytest

from thomas.server import green_checkout, green_handoff

THREE_DAYS_S = 3 * 86400.0


def _copy(root: Path, name: str, *, record_age_s: float | None) -> green_checkout.Green:
    """One copy; with *record_age_s*, a conversation record last written that long ago (a run began or ended then)."""
    git_dir, work = root / "git" / name, root / "work" / name
    (git_dir / "refs" / "heads").mkdir(parents=True)
    work.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/dev\n", encoding="ascii")
    (git_dir / "refs" / "heads" / "dev").write_text("0" * 40 + "\n", encoding="ascii")
    (git_dir / "index").write_bytes(b"index")
    (work / "tracked.txt").write_text("before", encoding="ascii")
    if record_age_s is not None:
        _write_record(work, record_age_s)
    return green_checkout.Green(name, work, git_dir, "base", root)


def _write_record(work: Path, age_s: float, text: str = "{}") -> None:
    record = work / green_handoff._RECORDS / "fc_1.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(text, encoding="ascii")
    then = time.time() - age_s
    os.utime(record, (then, then))


@pytest.fixture
def copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "green"
    made = {
        "quiet": _copy(root, "quiet", record_age_s=THREE_DAYS_S),
        "a-quiet-one": _copy(root, "a-quiet-one", record_age_s=THREE_DAYS_S),
        "lately": _copy(root, "lately", record_age_s=60.0),
        "no-record": _copy(root, "no-record", record_age_s=None),
    }
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    monkeypatch.setattr(green_handoff, "_found", made.get)
    monkeypatch.setattr(green_handoff, "_read_state", lambda _dir: {})
    monkeypatch.setattr(green_handoff, "_sibling_cache", {})
    monkeypatch.setattr(green_handoff, "_at_work", frozenset())
    moment = [1000.0]
    monkeypatch.setattr(green_handoff, "_sibling_clock", lambda: moment[0])
    walks: Counter[str] = Counter()
    real_stamp = green_handoff._worktree_stamp

    def stamp(work: Path) -> bytes:
        walks[work.name] += 1
        return real_stamp(work)

    monkeypatch.setattr(green_handoff, "_worktree_stamp", stamp)
    asked: Counter[str] = Counter()
    answer = {"diff": "changed.txt\0"}

    def git(green: green_checkout.Green, *args: str) -> str:
        asked[green.execution_id] += args[0] == "diff"
        return answer["diff"] if args[0] == "diff" else ""

    monkeypatch.setattr(green_handoff, "_green_git", git)
    return made, walks, asked, moment, answer


def test_a_copy_no_run_has_been_in_lately_is_not_walked(copies) -> None:
    made, walks, asked, _moment, _answer = copies
    for _ in range(3):
        found = green_handoff.sibling_changes("")
        assert found == {name: ["changed.txt"] for name in made}, "every copy's change is still reported"
    assert walks["quiet"] == 0, "a copy untouched for three days was walked file by file"
    assert asked["quiet"] == 1, "git was asked about it once, then its answer was kept"
    assert walks["lately"] == 3 and walks["no-record"] == 3, "a copy a run may be in is walked at every listing"


def test_a_run_that_came_and_went_in_a_quiet_copy_is_seen_at_the_next_listing(copies) -> None:
    made, walks, asked, _moment, answer = copies
    assert green_handoff.sibling_changes("")["quiet"] == ["changed.txt"]
    # A run began and ended between two listings: both wrote the record, and it edited a file.
    _write_record(made["quiet"].work, THREE_DAYS_S - 3600.0, text='{"turns": [1, 2]}')
    answer["diff"] = "changed.txt\0edited-by-the-run.txt\0"
    assert green_handoff.sibling_changes("")["quiet"] == ["changed.txt", "edited-by-the-run.txt"]
    assert asked["quiet"] == 2 and walks["quiet"] == 0, "its records said a run had been in it; no walk was needed"


def test_a_copy_whose_record_was_just_written_is_walked_again(copies) -> None:
    made, walks, _asked, _moment, _answer = copies
    green_handoff.sibling_changes("")
    assert walks["quiet"] == 0
    _write_record(made["quiet"].work, 5.0)  # a run began in it five seconds ago
    green_handoff.sibling_changes("")
    green_handoff.sibling_changes("")
    assert walks["quiet"] == 2, "a copy a run began in is walked at every listing, as before"


def test_a_copy_a_run_of_this_server_is_in_is_walked_however_old_its_record(copies) -> None:
    _made, walks, _asked, _moment, _answer = copies
    green_handoff.runs_are_in(["quiet"])
    green_handoff.sibling_changes("")
    green_handoff.sibling_changes("")
    assert walks["quiet"] == 2
    green_handoff.runs_are_in([])
    green_handoff.sibling_changes("")
    green_handoff.sibling_changes("")
    assert walks["quiet"] == 2, "once no run is in it, it is quiet again"


def test_git_is_asked_about_a_quiet_copy_again_once_its_answer_is_old(copies) -> None:
    _made, walks, asked, moment, answer = copies
    green_handoff.sibling_changes("")
    moment[0] += green_handoff._QUIET_FRESH_S - 1
    green_handoff.sibling_changes("")
    assert asked["quiet"] == 1
    moment[0] += green_handoff._QUIET_FRESH_S + 2  # past twice the quiet time: every copy has come due
    answer["diff"] = "changed.txt\0found-late.txt\0"
    assert green_handoff.sibling_changes("")["quiet"] == ["changed.txt", "found-late.txt"]
    assert asked["quiet"] == 2 and walks["quiet"] == 0


def test_the_project_list_says_which_copies_a_run_is_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server.routes import self_project_routes as routes

    catalog = tmp_path / "catalog"
    (catalog / routes._CONVERSATIONS).mkdir(parents=True)
    work = tmp_path / "green" / "work"
    greens = [
        (work / "thomas-running", {"id": "fc_running", "updated_at": "2026-11-13T10:00:00+00:00"}),
        (work / "thomas-idle", {"id": "fc_idle", "updated_at": "2026-11-10T10:00:00+00:00"}),
    ]
    said: list[frozenset[str]] = []
    monkeypatch.setattr(routes, "_in_greens", lambda warnings: greens)
    monkeypatch.setattr(routes.green_handoff, "runs_are_in", lambda names: said.append(frozenset(names)))
    monkeypatch.setattr(routes.green_handoff, "sibling_changes", lambda _id: {})
    monkeypatch.setattr(routes, "read_registry", lambda _catalog, _unread: {})
    monkeypatch.setattr(routes, "add_timings", lambda *args, **kwargs: {})
    monkeypatch.setattr(routes, "_in_green", lambda _work, _catalog, conversation, *_a, **_k: conversation)
    monkeypatch.setattr(routes.hand_in_hold_store, "rows", lambda _catalog: [])

    routes.read_projects(catalog, running={"fc_running"})

    assert said == [frozenset({"thomas-running"})]
    routes.read_projects(catalog)  # a caller with no registry of runs: the chat tool that lists projects
    assert said == [frozenset({"thomas-running"})], "it does not say that no copy has a run in it"


def test_the_copies_being_worked_in_are_reported_before_the_quiet_ones(copies) -> None:
    """A note to a new team names the first eight copies. Quiet ones, kept for an hour, came first by name and
    filled every place, so the note named no copy a team was working in (review, 2026-11-13)."""
    for _ in range(2):
        assert list(green_handoff.sibling_changes("")) == ["lately", "no-record", "a-quiet-one", "quiet"]
