"""A deliberate deletion must leave a record a gate can read -- and a missing
record file must never be confused with an empty one that lied.

Five contracts are pinned here:

1. record + load round-trip for both kinds (branch, file).
2. append-only: recording a new death never mutates a prior record, and ids
   stay unique even when the same name/path dies twice.
3. a resurrection-approved record flips ``is_resurrection_approved`` for its
   own death id and ONLY that id -- an unrelated death stays unapproved.
4. ``dead_file_paths`` returns the newest record per path. A resurrection
   approval does not replace the death record it references (it is a
   different record, ``kind="resurrection-approved"``), so a path that was
   approved and then deleted AGAIN goes back to reporting as dead -- the
   newest ``kind="file"`` record wins, not the newest record of any kind.
5. This repo's documented disease is absence-reads-as-clean: a MISSING
   graveyard.json is legitimately "nothing recorded yet" (empty Graveyard,
   NOTE printed); a graveyard.json that exists but fails to parse -- or
   parses but has a record missing a required key -- is NEVER treated the
   same way -- ``load`` raises SystemExit naming the file.

Two more, added after review flagged a lost-update race in the write path
(plain read-modify-write with no lock, no atomic replace -- two writers
racing could silently clobber each other's record):

6. a crash between the temp-file write and the atomic replace leaves the
   original graveyard.json byte-for-byte intact, and does not leave a
   dangling temp file behind.
7. lock contention -- another process already holding the write lock --
   is a bounded wait followed by a loud SystemExit naming the lock file,
   never a silent skip of the record.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from scripts.forge import graveyard

# ---------------------------------------------------------------------------
# 1. round trip
# ---------------------------------------------------------------------------


def test_a_recorded_branch_death_round_trips_through_load(tmp_path: Path) -> None:
    record_id = graveyard.record_death(tmp_path, "branch", "old-experiment", "abc123", "superseded by dev", "test-user")

    gy = graveyard.load(tmp_path)

    assert "old-experiment" in gy.dead_ref_names()
    assert record_id.startswith(graveyard._today())


def test_a_recorded_file_death_round_trips_through_load(tmp_path: Path) -> None:
    record_id = graveyard.record_death(tmp_path, "file", "thomas/dead/module.py", "def456", "dead code", "test-user")

    gy = graveyard.load(tmp_path)
    paths = gy.dead_file_paths()

    assert "thomas/dead/module.py" in paths
    assert paths["thomas/dead/module.py"]["id"] == record_id
    assert paths["thomas/dead/module.py"]["dead_sha"] == "def456"


# ---------------------------------------------------------------------------
# 2. append-only, unique + stable ids
# ---------------------------------------------------------------------------


def test_recording_a_second_death_does_not_mutate_the_first(tmp_path: Path) -> None:
    first_id = graveyard.record_death(tmp_path, "file", "a.py", "sha1", "r1", "test-user")
    first_record_before = dict(graveyard.load(tmp_path).dead_file_paths()["a.py"])

    second_id = graveyard.record_death(tmp_path, "file", "b.py", "sha2", "r2", "test-user")

    gy = graveyard.load(tmp_path)
    assert gy.dead_file_paths()["a.py"] == first_record_before
    assert first_id != second_id
    assert len(gy.records) == 2


def test_two_deaths_of_the_same_path_get_different_stable_ids(tmp_path: Path) -> None:
    id1 = graveyard.record_death(tmp_path, "file", "a.py", "sha1", "r1", "test-user")
    id2 = graveyard.record_death(tmp_path, "file", "a.py", "sha2", "r2", "test-user")

    assert id1 != id2
    gy = graveyard.load(tmp_path)
    ids = {r["id"] for r in gy.records}
    assert {id1, id2} <= ids
    # stable: loading again does not renumber anything already on disk.
    gy_again = graveyard.load(tmp_path)
    assert {r["id"] for r in gy_again.records} == ids


# ---------------------------------------------------------------------------
# 3. resurrection approval flips only its own id
# ---------------------------------------------------------------------------


def test_a_resurrection_approval_flips_only_its_own_death_id(tmp_path: Path) -> None:
    id1 = graveyard.record_death(tmp_path, "branch", "feature-x", "sha1", "r1", "test-user")
    id2 = graveyard.record_death(tmp_path, "branch", "feature-y", "sha2", "r2", "test-user")

    graveyard.record_resurrection_approval(tmp_path, id1, "approved for reuse", "test-user")

    gy = graveyard.load(tmp_path)
    assert gy.is_resurrection_approved(id1) is True
    assert gy.is_resurrection_approved(id2) is False


# ---------------------------------------------------------------------------
# 4. newest-per-path, re-death after approval stays dead
# ---------------------------------------------------------------------------


def test_dead_file_paths_returns_the_newest_record_and_redeath_after_approval_stays_dead(
    tmp_path: Path,
) -> None:
    death1 = graveyard.record_death(tmp_path, "file", "thomas/old.py", "sha1", "first death", "test-user")
    graveyard.record_resurrection_approval(tmp_path, death1, "bring it back", "test-user")

    gy = graveyard.load(tmp_path)
    # the approval is a SEPARATE record; the newest kind="file" record for
    # the path is still the original death.
    assert gy.dead_file_paths()["thomas/old.py"]["id"] == death1
    assert gy.is_resurrection_approved(death1) is True

    death2 = graveyard.record_death(tmp_path, "file", "thomas/old.py", "sha2", "deleted again", "test-user")

    gy2 = graveyard.load(tmp_path)
    newest = gy2.dead_file_paths()["thomas/old.py"]
    assert newest["id"] == death2
    assert gy2.is_resurrection_approved(newest["id"]) is False


# ---------------------------------------------------------------------------
# 5. missing vs malformed
# ---------------------------------------------------------------------------


def test_a_missing_graveyard_file_loads_empty_with_a_printed_note(tmp_path: Path, capsys) -> None:
    gy = graveyard.load(tmp_path)

    assert gy.records == ()
    # I5 (graveyard-with-teeth fix-wave, 2026-08-25): this NOTE prints to
    # stderr, not stdout -- see test_list_json_on_a_repo_with_no_graveyard_file
    # below for why stdout must stay clean.
    err = capsys.readouterr().err
    assert "NOTE" in err
    assert "graveyard.json" in err


def test_malformed_json_is_a_loud_systemexit_not_a_silent_empty_graveyard(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "ops" / "graveyard.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        graveyard.load(tmp_path)

    assert "graveyard.json" in str(exc_info.value)


def test_a_records_list_that_is_not_a_list_is_also_a_loud_systemexit(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "ops" / "graveyard.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "records": "nope"}), encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        graveyard.load(tmp_path)

    assert "graveyard.json" in str(exc_info.value)


def test_the_committed_graveyard_file_parses_and_every_record_is_well_formed() -> None:
    """The committed ``docs/ops/graveyard.json`` started empty (Task 1) and
    is now seeded from history (Task 2, ``graveyard_seed.py``) -- this test
    no longer pins emptiness, which the seed deliberately ends. What must
    hold in both states, and every state after: ``load`` succeeds (the
    honesty contract -- a real file must never be malformed) and every
    record it returns has a valid ``kind``."""
    repo_root = Path(__file__).resolve().parents[1]

    gy = graveyard.load(repo_root)

    assert isinstance(gy.records, tuple)
    for record in gy.records:
        assert record["kind"] in ("branch", "file", "resurrection-approved")


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_the_cli_records_a_file_death_and_lists_it_as_json(tmp_path: Path, capsys) -> None:
    rc = graveyard.main(
        [
            "--repo-root",
            str(tmp_path),
            "record-file",
            "thomas/dead.py",
            "shaabc",
            "--reason",
            "unused",
            "--by",
            "test-user",
        ]
    )
    assert rc == 0
    capsys.readouterr()

    rc = graveyard.main(["--repo-root", str(tmp_path), "list", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert payload["records"][0]["name"] == "thomas/dead.py"
    assert payload["records"][0]["kind"] == "file"


def test_list_json_on_a_repo_with_no_graveyard_file_is_parseable_json_only_on_stdout(
    tmp_path: Path, capsys
) -> None:
    """I5 regression: ``graveyard.py list --json`` is a machine-readable
    surface other tooling parses with ``json.loads()`` -- the janitor's
    ``graveyard_dead_branch_ids()`` (janitor.py) shells out to exactly this
    command. When no graveyard.json exists yet, ``load()`` used to print its
    honesty-contract NOTE to stdout, ahead of the JSON payload -- a caller
    doing ``json.loads(stdout)`` would fail to parse and misreport a
    perfectly empty graveyard as an unparseable/corrupt one. The NOTE must
    still be printed (the honesty contract: absence is stated, not silent)
    but only to stderr, leaving stdout as JSON and nothing else."""
    rc = graveyard.main(["--repo-root", str(tmp_path), "list", "--json"])
    assert rc == 0

    captured = capsys.readouterr()
    assert "NOTE" in captured.err
    payload = json.loads(captured.out)
    assert payload == {"version": 1, "records": []}


# ---------------------------------------------------------------------------
# 5 (cont'd). a record missing a required key is also malformed
# ---------------------------------------------------------------------------


def test_a_record_missing_a_required_key_is_also_a_loud_systemexit(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "ops" / "graveyard.json"
    path.parent.mkdir(parents=True)
    bad_record = {
        # "kind" deliberately omitted
        "id": "2026-01-01-x-1",
        "name": "x",
        "dead_sha": "s",
        "deleted_on": "2026-01-01",
        "reason": "r",
        "by": "test-user",
        "refs": None,
    }
    path.write_text(json.dumps({"version": 1, "records": [bad_record]}), encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        graveyard.load(tmp_path)

    assert "graveyard.json" in str(exc_info.value)
    assert "kind" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 6. a crash between the temp write and the atomic replace loses nothing
# ---------------------------------------------------------------------------


def test_a_crash_between_the_temp_write_and_the_replace_leaves_the_original_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graveyard.record_death(tmp_path, "file", "a.py", "sha1", "first death", "test-user")
    path = tmp_path / "docs" / "ops" / "graveyard.json"
    original_bytes = path.read_bytes()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated crash between temp write and replace")

    monkeypatch.setattr(graveyard.os, "replace", _boom)

    with pytest.raises(OSError):
        graveyard.record_death(tmp_path, "file", "b.py", "sha2", "second death", "test-user")

    assert path.read_bytes() == original_bytes, "original file must survive a failed replace untouched"
    leftover_tmp = list(path.parent.glob(f".{path.name}.*.tmp"))
    assert leftover_tmp == [], "a failed replace must not leave a dangling temp file behind"


# ---------------------------------------------------------------------------
# 7. lock contention is a bounded wait then a loud SystemExit
# ---------------------------------------------------------------------------


def test_lock_contention_is_a_bounded_wait_then_a_loud_systemexit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Shrink the retry knobs so the test doesn't actually wait out a real
    # timeout, and push the stale-lock threshold out of reach so the held
    # lock below is never treated as abandoned mid-test.
    monkeypatch.setattr(graveyard, "_LOCK_MAX_RETRIES", 2)
    monkeypatch.setattr(graveyard, "_LOCK_RETRY_INTERVAL", 0.01)
    monkeypatch.setattr(graveyard, "_LOCK_STALE_SECONDS", 9999.0)

    lock_path = graveyard._lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with pytest.raises(SystemExit) as exc_info:
            graveyard.record_death(tmp_path, "file", "a.py", "sha1", "r1", "test-user")
        assert str(lock_path) in str(exc_info.value)
    finally:
        os.close(held_fd)
        lock_path.unlink()

    # The lock file the losing caller left behind (if any) must not wedge a
    # later, uncontended caller shut.
    if lock_path.exists():
        lock_path.unlink()
    record_id = graveyard.record_death(tmp_path, "file", "c.py", "sha3", "uncontended", "test-user")
    assert record_id
