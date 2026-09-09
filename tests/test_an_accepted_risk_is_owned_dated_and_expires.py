"""An accepted risk has an owner, a date, and an expiry -- not a shrug.

Five contracts are pinned here (spec: the internal design record
forging-loop.md, Task 1), all copied byte-for-byte from the graveyard's
established registry pattern (scripts/forge/graveyard.py):

1. record + load round-trip; append-only; ids stay unique even when the same
   reason text is recorded twice.
2. malformed ``accepted_risks.json`` (bad JSON, wrong top-level shape, a
   record missing a required key) is a loud SystemExit naming the file --
   never silently treated as an empty registry. A MISSING file is the
   opposite case: legitimately "nothing accepted yet", an empty ``Risks``
   and a printed stderr NOTE (stdout stays JSON-parseable -- the phase-1.3
   lesson pinned in graveyard's own ``list --json`` regression test).
3. ``expires_on`` is validated as a real, future-or-today date at record
   time -- garbage text and already-past dates are both a loud failure, not
   a silently accepted risk with a meaningless expiry.
4. ``Risks.is_expired`` matches ``monolith_guard.py``'s waiver-expiry
   boundary (``expires_date < date.today()``, ~monolith_guard.py:429): a
   risk expiring exactly "today" is NOT expired yet (it is still valid
   through the end of its expiry day), only strictly-past dates are. A
   missing risk id returns ``None`` from both ``get`` and ``is_expired`` --
   never a silent ``False`` that would read as "not expired" for a risk
   that was never recorded at all.
5. locking/atomicity, per the graveyard's own regression tests: a crash
   between the temp-file write and the atomic replace leaves the original
   file byte-for-byte intact and no dangling temp file behind; lock
   contention is a bounded wait followed by a loud SystemExit naming the
   lock file, never a silent skip of the record.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest
from scripts.forge import accepted_risks

# ---------------------------------------------------------------------------
# 1. round trip, append-only, unique ids
# ---------------------------------------------------------------------------


def test_a_recorded_risk_round_trips_through_load(tmp_path: Path) -> None:
    tomorrow = (dt.date.today() + dt.timedelta(days=30)).isoformat()

    record_id = accepted_risks.record_risk(
        tmp_path, "test-user", "no time to fix the flaky mock this sprint", tomorrow
    )

    risks = accepted_risks.load(tmp_path)
    record = risks.get(record_id)

    assert record is not None
    assert record["owner"] == "test-user"
    assert record["reason"] == "no time to fix the flaky mock this sprint"
    assert record["expires_on"] == tomorrow
    assert record["reviewed_on"] == accepted_risks._today()
    assert record["refs"] is None
    assert record_id.startswith(accepted_risks._today())


def test_recording_a_second_risk_does_not_mutate_the_first(tmp_path: Path) -> None:
    expires = (dt.date.today() + dt.timedelta(days=10)).isoformat()
    first_id = accepted_risks.record_risk(tmp_path, "test-user", "risk one", expires)
    first_before = dict(accepted_risks.load(tmp_path).get(first_id))

    second_id = accepted_risks.record_risk(tmp_path, "test-user", "risk two", expires, refs="issue-42")

    risks = accepted_risks.load(tmp_path)
    assert risks.get(first_id) == first_before
    assert first_id != second_id
    assert risks.get(second_id)["refs"] == "issue-42"
    assert len(risks.records) == 2


def test_two_risks_recorded_from_the_same_reason_text_get_different_stable_ids(tmp_path: Path) -> None:
    expires = (dt.date.today() + dt.timedelta(days=10)).isoformat()
    id1 = accepted_risks.record_risk(tmp_path, "test-user", "same reason", expires)
    id2 = accepted_risks.record_risk(tmp_path, "test-user", "same reason", expires)

    assert id1 != id2
    risks = accepted_risks.load(tmp_path)
    ids = {r["id"] for r in risks.records}
    assert {id1, id2} <= ids
    # stable: loading again does not renumber anything already on disk.
    risks_again = accepted_risks.load(tmp_path)
    assert {r["id"] for r in risks_again.records} == ids


# ---------------------------------------------------------------------------
# 2. missing vs malformed
# ---------------------------------------------------------------------------


def test_a_missing_registry_file_loads_empty_with_a_printed_note(tmp_path: Path, capsys) -> None:
    risks = accepted_risks.load(tmp_path)

    assert risks.records == ()
    err = capsys.readouterr().err
    assert "NOTE" in err
    assert "accepted_risks.json" in err


def test_malformed_json_is_a_loud_systemexit_not_a_silent_empty_registry(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "ops" / "accepted_risks.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        accepted_risks.load(tmp_path)

    assert "accepted_risks.json" in str(exc_info.value)


def test_a_records_list_that_is_not_a_list_is_also_a_loud_systemexit(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "ops" / "accepted_risks.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "records": "nope"}), encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        accepted_risks.load(tmp_path)

    assert "accepted_risks.json" in str(exc_info.value)


def test_a_record_missing_a_required_key_is_also_a_loud_systemexit(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "ops" / "accepted_risks.json"
    path.parent.mkdir(parents=True)
    bad_record = {
        # "expires_on" deliberately omitted
        "id": "2026-01-01-x-1",
        "owner": "test-user",
        "reason": "r",
        "reviewed_on": "2026-01-01",
        "refs": None,
    }
    path.write_text(json.dumps({"version": 1, "records": [bad_record]}), encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        accepted_risks.load(tmp_path)

    assert "accepted_risks.json" in str(exc_info.value)
    assert "expires_on" in str(exc_info.value)


def test_the_seeded_registry_file_parses_as_an_empty_registry() -> None:
    """The committed docs/ops/accepted_risks.json seeds as {"version": 1,
    "records": []} -- Task 1 only creates the empty, well-formed shell."""
    repo_root = Path(__file__).resolve().parents[1]

    risks = accepted_risks.load(repo_root)

    assert isinstance(risks.records, tuple)


# ---------------------------------------------------------------------------
# 3. expires_on validated as a real future-or-today date at record time
# ---------------------------------------------------------------------------


def test_recording_with_an_unparseable_expires_on_is_a_loud_failure(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="expires_on"):
        accepted_risks.record_risk(tmp_path, "test-user", "reason", "not-a-date")

    # nothing was written.
    assert accepted_risks.load(tmp_path).records == ()


def test_recording_with_an_already_past_expires_on_is_a_loud_failure(tmp_path: Path) -> None:
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()

    with pytest.raises(ValueError, match="expires_on"):
        accepted_risks.record_risk(tmp_path, "test-user", "reason", yesterday)

    assert accepted_risks.load(tmp_path).records == ()


def test_recording_with_expires_on_of_today_is_accepted(tmp_path: Path) -> None:
    today = dt.date.today().isoformat()

    record_id = accepted_risks.record_risk(tmp_path, "test-user", "reason", today)

    assert accepted_risks.load(tmp_path).get(record_id)["expires_on"] == today


# ---------------------------------------------------------------------------
# 4. is_expired boundary semantics match monolith_guard's precedent
# ---------------------------------------------------------------------------


def test_is_expired_is_false_on_the_exact_expiry_day_and_true_the_day_after(tmp_path: Path) -> None:
    expiry_date = dt.date.today() + dt.timedelta(days=60)
    record_id = accepted_risks.record_risk(tmp_path, "test-user", "boundary case", expiry_date.isoformat())
    risks = accepted_risks.load(tmp_path)

    assert risks.is_expired(record_id, expiry_date - dt.timedelta(days=1)) is False
    assert risks.is_expired(record_id, expiry_date) is False, "expiry day itself is still valid"
    assert risks.is_expired(record_id, expiry_date + dt.timedelta(days=1)) is True


def test_is_expired_on_a_missing_risk_id_is_none_never_a_silent_false(tmp_path: Path) -> None:
    accepted_risks.record_risk(tmp_path, "test-user", "reason", (dt.date.today() + dt.timedelta(days=1)).isoformat())
    risks = accepted_risks.load(tmp_path)

    assert risks.get("does-not-exist") is None
    assert risks.is_expired("does-not-exist", dt.date.today()) is None


# ---------------------------------------------------------------------------
# 5. locking / atomicity, per the graveyard's own tests
# ---------------------------------------------------------------------------


def test_a_crash_between_the_temp_write_and_the_replace_leaves_the_original_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expires = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    accepted_risks.record_risk(tmp_path, "test-user", "first risk", expires)
    path = tmp_path / "docs" / "ops" / "accepted_risks.json"
    original_bytes = path.read_bytes()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated crash between temp write and replace")

    monkeypatch.setattr(accepted_risks.os, "replace", _boom)

    with pytest.raises(OSError):
        accepted_risks.record_risk(tmp_path, "test-user", "second risk", expires)

    assert path.read_bytes() == original_bytes, "original file must survive a failed replace untouched"
    leftover_tmp = list(path.parent.glob(f".{path.name}.*.tmp"))
    assert leftover_tmp == [], "a failed replace must not leave a dangling temp file behind"


def test_lock_contention_is_a_bounded_wait_then_a_loud_systemexit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(accepted_risks, "_LOCK_MAX_RETRIES", 2)
    monkeypatch.setattr(accepted_risks, "_LOCK_RETRY_INTERVAL", 0.01)
    monkeypatch.setattr(accepted_risks, "_LOCK_STALE_SECONDS", 9999.0)

    lock_path = accepted_risks._lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    expires = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    try:
        with pytest.raises(SystemExit) as exc_info:
            accepted_risks.record_risk(tmp_path, "test-user", "contended", expires)
        assert str(lock_path) in str(exc_info.value)
    finally:
        os.close(held_fd)
        lock_path.unlink()

    if lock_path.exists():
        lock_path.unlink()
    record_id = accepted_risks.record_risk(tmp_path, "test-user", "uncontended", expires)
    assert record_id


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_the_cli_records_a_risk_and_lists_it_as_json(tmp_path: Path, capsys) -> None:
    expires = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    rc = accepted_risks.main(
        [
            "--repo-root",
            str(tmp_path),
            "record",
            "--owner",
            "test-user",
            "--reason",
            "cli recorded risk",
            "--expires-on",
            expires,
        ]
    )
    assert rc == 0
    capsys.readouterr()

    rc = accepted_risks.main(["--repo-root", str(tmp_path), "list", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert payload["records"][0]["owner"] == "test-user"
    assert payload["records"][0]["reason"] == "cli recorded risk"


def test_list_json_on_a_repo_with_no_registry_file_is_parseable_json_only_on_stdout(
    tmp_path: Path, capsys
) -> None:
    """Same phase-1.3 lesson the graveyard already pins: the missing-file
    NOTE must land on stderr only, so a caller doing json.loads(stdout)
    never trips over it."""
    rc = accepted_risks.main(["--repo-root", str(tmp_path), "list", "--json"])
    assert rc == 0

    captured = capsys.readouterr()
    assert "NOTE" in captured.err
    payload = json.loads(captured.out)
    assert payload == {"version": 1, "records": []}
