"""A dev-moved repair round starts with dev already merged into the team's copy (Task 3h).

When the promoter refused a Thomas project's hand-in because "the change no longer applies to dev", its repair round
told the team to run `git merge <dev>`. Build's Claude team has no shell. On 2026-09-25 the ratchet project
(thomas-479adbe796ab) spent its rounds checking that its files were intact without ever seeing what dev had changed,
was refused again, and stopped. Now the server merges dev into the green before the round starts, and the round's
message names the files still holding conflict markers. Real here: git repos and greens, the conversation store, and
the promoter's own tree check. Nothing is stubbed except one failure, forced on purpose.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from scripts.cage import self_change_checks

from thomas.forge.anvil import forge_code_store
from thomas.server import green_checkout, green_handoff, green_rebase, thomas_project
from thomas.server.routes import evolve_agent_autopilot as ap

ASK = "Make the Send button blue"
MOVED = "the change no longer applies to dev: Applied patch to 'a.txt' with conflicts."
# Like Thomas's own checkout: the Build conversation (.thomas/) and the runtime folder are ignored.
BASE = {".gitignore": ".thomas/\nruntime/\n", "a.txt": "one\ntwo\nthree\n", "b.txt": "b1\nb2\nb3\n", "notes.txt": "n\n"}
TEAM_A, DEV_A = "one\ntwo from the team\nthree\n", "one\ntwo from dev\nthree\n"
DEV_B = "b0 from dev\nb1\nb2\nb3\n"


def _git(cwd: Path, *args: str) -> str:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _in_green(green: green_checkout.Green, *args: str) -> str:
    return _git(green.work, f"--git-dir={green.git_dir}", f"--work-tree={green.work}", *args)


def _write(root: Path, files: dict[str, str | None]) -> None:
    for rel, text in files.items():
        if text is None:
            (root / rel).unlink()
            continue
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def blue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for Thomas's own source checkout, on a branch called dev like the real one."""
    root = tmp_path / "blue"
    _write(root, dict(BASE))
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(root, *args)
    for folder in (tmp_path / "green" / "work", tmp_path / "green" / "git"):  # a green root that exists gets no ACLs
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "green"))
    return root


def _team(blue: Path, files: dict[str, str | None], eid: str = "thomas-rebase0001") -> green_checkout.Green:
    green = green_checkout.create_green(blue=blue, execution_id=eid)
    _write(green.work, files)
    return green


def _move_dev(blue: Path, files: dict[str, str | None]) -> str:  # another change lands on dev after the green was made
    _write(blue, files)
    _git(blue, "add", "-A", "--force")
    _git(blue, "commit", "-q", "-m", "another landing")
    return _git(blue, "rev-parse", "dev")


def _text(green: green_checkout.Green, rel: str) -> str:
    return (green.work / rel).read_text(encoding="utf-8")  # universal newlines: a CRLF checkout reads the same


def _snapshot(eid: str) -> tuple[str, str, str]:
    """The green as the promoter and its team see it: the whole change, the base it is against, and HEAD."""
    green = green_checkout.find_green(eid)
    assert green is not None
    return green_checkout.green_patch(green), green.base, _in_green(green, "rev-parse", "HEAD")


def _marked(green: green_checkout.Green) -> list[str]:
    files = [p for p in green.work.rglob("*") if p.is_file() and ".git" not in p.parts]
    return sorted(p.relative_to(green.work).as_posix() for p in files if "<<<<<<<" in p.read_text(encoding="utf-8"))


def test_a_change_that_still_fits_lands_on_dev_with_no_markers(blue: Path) -> None:
    green = _team(blue, {"a.txt": TEAM_A, "send.py": "COLOUR = 'blue'\n", "notes.txt": None})
    patch = green_checkout.green_patch(green)
    dev = _move_dev(blue, {"b.txt": DEV_B, "dev.txt": "from dev\n"})

    merged = green_rebase.rebase_onto_dev(green.execution_id)

    assert (merged.ok, merged.dev, merged.conflicts, merged.failed) == (True, dev, (), ""), merged
    assert _text(green, "a.txt") == TEAM_A and _text(green, "send.py") == "COLOUR = 'blue'\n", "the team's change"
    assert not (green.work / "notes.txt").exists(), "a file the team deleted stays deleted"
    assert _text(green, "b.txt") == DEV_B and _text(green, "dev.txt") == "from dev\n", "and dev's, underneath it"
    assert _marked(green) == [] and _in_green(green, "rev-parse", "HEAD") == dev
    saved = Path(merged.saved)
    assert saved.resolve().is_relative_to(green.git_dir.resolve()), "the team's change is kept in its git folder"
    assert saved.read_bytes() == patch.encode("utf-8", errors="surrogateescape"), "exactly as it was"


def test_a_change_that_conflicts_leaves_markers_in_exactly_that_file(blue: Path) -> None:
    green = _team(blue, {"a.txt": TEAM_A, "b.txt": "b1\nb2\nb3\nb4 from the team\n"})
    _move_dev(blue, {"a.txt": DEV_A, "b.txt": DEV_B})

    merged = green_rebase.rebase_onto_dev(green.execution_id)

    assert merged.ok and merged.conflicts == ("a.txt",), merged
    assert _marked(green) == ["a.txt"]
    marked = _text(green, "a.txt")
    assert marked.startswith("one\n<<<<<<< dev\ntwo from dev\n=======\ntwo from the team\n>>>>>>> "), marked
    assert marked.endswith("\nthree\n"), "every line outside the conflict is kept"
    assert _text(green, "b.txt") == "b0 from dev\nb1\nb2\nb3\nb4 from the team\n", "a hunk that still fits applies"


def test_the_new_base_is_recorded_and_the_next_patch_is_only_the_teams_change(blue: Path, tmp_path: Path) -> None:
    green = _team(blue, {"a.txt": TEAM_A, "send.py": "COLOUR = 'blue'\n", "notes.txt": None})
    dev = _move_dev(blue, {"b.txt": DEV_B, "dev.txt": "from dev\n"})

    assert green_rebase.rebase_onto_dev(green.execution_id).ok

    moved = green_checkout.find_green(green.execution_id)
    assert moved is not None and moved.base == dev
    meta = json.loads((green.git_dir / green_checkout.METADATA_NAME).read_text(encoding="utf-8"))
    assert meta["base"] == dev and meta["execution_id"] == green.execution_id and meta["blue"] == str(blue.resolve())
    assert green_checkout.changed_paths(moved) == ["a.txt", "notes.txt", "send.py"], "never dev's own changes"
    (patch := tmp_path / "change.patch").write_bytes(
        green_checkout.green_patch(moved).encode("utf-8", "surrogateescape")
    )
    tree = self_change_checks.derive_tree(blue, dev, patch)  # the promoter's own check: it applies to dev now
    assert sorted(self_change_checks.tree_changes(blue, dev, tree)) == [("A", "send.py"), ("D", "notes.txt"),
                                                                       ("M", "a.txt")]  # fmt: skip


def test_untracked_files_and_the_greens_own_state_survive(blue: Path) -> None:
    green = _team(blue, {"a.txt": TEAM_A, "send.py": "COLOUR = 'blue'\n"})
    conversation = green.work / ".thomas" / "evolve" / "agent" / "conversations" / "fc_1.json"
    report = green.work / "runtime" / "self_development" / green.execution_id / "report.md"
    _write(green.work, {conversation.relative_to(green.work).as_posix(): '{"id": "fc_1"}\n'})
    _write(green.work, {report.relative_to(green.work).as_posix(): "the run's own notes\n"})
    green_handoff.await_verdict(green.execution_id)
    green_checkout.mark_kept(green, "awaiting your verdict")
    state = {n: (green.git_dir / n).read_bytes() for n in (green_handoff.HANDOFF_NAME, green_checkout.KEPT_NAME)}
    untouched = conversation.stat().st_mtime_ns
    _move_dev(blue, {"b.txt": DEV_B})

    assert green_rebase.rebase_onto_dev(green.execution_id).ok

    assert (
        conversation.read_text(encoding="utf-8") == '{"id": "fc_1"}\n' and conversation.stat().st_mtime_ns == untouched
    )
    assert report.read_text(encoding="utf-8") == "the run's own notes\n"
    assert {n: (green.git_dir / n).read_bytes() for n in state} == state, "the green's own state"
    assert _in_green(green, "ls-files", "--others", "--exclude-standard") == "send.py", "the team's new file, as made"


def test_a_change_that_cannot_be_applied_leaves_the_green_as_it_was(blue: Path) -> None:
    green = _team(blue, {"a.txt": TEAM_A, "notes.txt": None})  # the team deletes a file ...
    before = _snapshot(green.execution_id)
    _move_dev(blue, {"notes.txt": "n, from dev\n"})  # ... that dev changed: no three-way merge can mark that

    merged = green_rebase.rebase_onto_dev(green.execution_id)

    assert not merged.ok and "notes.txt" in merged.failed and "nothing in this copy changed" in merged.failed, merged
    assert _snapshot(green.execution_id) == before
    assert _text(green, "a.txt") == TEAM_A and not (green.work / "notes.txt").exists()
    assert Path(merged.saved).read_bytes() == before[0].encode("utf-8", errors="surrogateescape")


def test_a_failure_after_the_move_puts_the_green_back(blue: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def full_disk(green: green_checkout.Green, base: str) -> green_checkout.Green:
        raise OSError("no space left on the device")

    green = _team(blue, {"a.txt": TEAM_A, "send.py": "COLOUR = 'blue'\n", "notes.txt": None})
    before = _snapshot(green.execution_id)
    _move_dev(blue, {"b.txt": DEV_B, "dev.txt": "from dev\n"})
    monkeypatch.setattr(green_checkout, "set_base", full_disk)

    merged = green_rebase.rebase_onto_dev(green.execution_id)

    assert not merged.ok and "no space left" in merged.failed and "put back as it was" in merged.failed, merged
    assert _snapshot(green.execution_id) == before, "the old base, with the team's change on it"
    assert _text(green, "b.txt") == BASE["b.txt"] and not (green.work / "dev.txt").exists(), "nothing of dev's"
    assert _text(green, "send.py") == "COLOUR = 'blue'\n" and not (green.work / "notes.txt").exists()


def test_an_ignored_file_dev_would_overwrite_stops_the_move(blue: Path) -> None:
    green = _team(blue, {"a.txt": TEAM_A})
    _write(green.work, {"runtime/keep.log": "the run's own\n"})
    before = _snapshot(green.execution_id)
    _move_dev(blue, {"runtime/keep.log": "from dev\n"})  # dev tracks a file where the green keeps an ignored one

    merged = green_rebase.rebase_onto_dev(green.execution_id)

    assert not merged.ok and "runtime/keep.log" in merged.failed, merged
    assert _text(green, "runtime/keep.log") == "the run's own\n" and _snapshot(green.execution_id) == before


def _round(blue: Path, tmp_path: Path, team: dict[str, str | None], dev: dict[str, str | None], why: str):
    green = _team(blue, team)
    conv = forge_code_store.new_conversation(green.work, title="t", thomas_project={"execution_id": green.execution_id})
    tip = _move_dev(blue, dev)
    catalog = tmp_path / "catalog"
    assert thomas_project.prepare_repair(green.work, catalog, conv["id"], why=why, detail=MOVED) == 1
    due = thomas_project.repair_due(forge_code_store.load_conversation(green.work, conv["id"]) or {})
    assert due is not None
    return green, tip, due


def test_a_dev_moved_round_starts_merged_and_its_message_lists_the_conflicts(blue: Path, tmp_path: Path) -> None:
    team = {"a.txt": TEAM_A, "b.txt": "b1\nb2\nb3\nb4 from the team\n"}
    green, dev, due = _round(blue, tmp_path, team, {"a.txt": DEV_A, "b.txt": DEV_B}, thomas_project.DEV_MOVED)

    assert (due["merged"], due["conflicts"], due["dev"], due["merge_failed"]) == (True, ["a.txt"], dev, "")
    assert green_checkout.find_green(green.execution_id).base == dev and _marked(green) == ["a.txt"]
    message = ap.repair_message(ASK, due)
    steps = message.split("Why it came back, in full:")[0]
    assert "git merge" not in message and "merged dev into this copy" in steps and f"now stands on {dev}" in steps
    assert "a.txt" in steps and "b.txt" not in steps, "only the files that still hold markers"
    assert "<<<<<<<" in steps and ">>>>>>>" in steps and "keeping both sides' intent" in steps
    assert "changelog.d/" in steps and MOVED in message and message.startswith(ap.REPAIR_PREFIX)


def test_a_clean_merge_says_no_file_holds_a_marker(blue: Path, tmp_path: Path) -> None:
    green, dev, due = _round(blue, tmp_path, {"a.txt": TEAM_A}, {"b.txt": DEV_B}, thomas_project.DEV_MOVED)

    message = ap.repair_message(ASK, due)

    assert due["merged"] is True and due["conflicts"] == [] and "git merge" not in message
    assert "no file holds a conflict marker" in message and f"now stands on {dev}" in message


def test_a_merge_that_failed_says_so_and_keeps_the_old_steps(blue: Path, tmp_path: Path) -> None:
    team, dev = {"notes.txt": None}, {"notes.txt": "n, from dev\n"}
    green, tip, due = _round(blue, tmp_path, team, dev, thomas_project.DEV_MOVED)

    message = ap.repair_message(ASK, due)

    assert due["merged"] is False and "notes.txt" in due["merge_failed"] and due["conflicts"] == []
    assert green_checkout.find_green(green.execution_id).base != tip, "the green stayed where it was"
    assert "could not merge dev into this copy" in message and due["merge_failed"] in message
    assert f"git merge {tip}" in message, "the steps from before this change"


def test_other_repair_reasons_never_move_the_green(blue: Path, tmp_path: Path) -> None:
    green, dev, due = _round(blue, tmp_path, {"a.txt": TEAM_A}, {"b.txt": DEV_B}, thomas_project.SENT_BACK)

    assert "merged" not in due and green_checkout.find_green(green.execution_id).base == green.base != dev
    assert _in_green(green, "rev-parse", "HEAD") == green.base and _text(green, "b.txt") == BASE["b.txt"]
