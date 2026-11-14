"""One conversation the restart survey cannot read is skipped; it does not stop every other project carrying on.

On 2026-11-04 one old project's conversation file raised PermissionError for the caged account, ``survey`` raised,
and ``restart_pass`` retried every 30 seconds with no interrupted project ever carried on.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from pathlib import Path

import pytest

from tests.restart_test_isolation import immediate_restart_retries, tmp_path_factory  # noqa: F401
from tests.test_a_restart_does_not_stop_a_thomas_project import (  # noqa: F401
    _app,
    _restart,
    _stopped_run,
    isolated,
)
from thomas.forge.anvil import forge_code_conversations, forge_code_store
from thomas.server import thomas_project

BAD = "fc_20260727T164835_3ff078"


def _register_bad(p, tmp_path: Path, how: str) -> Path:
    """A second conversation in the same catalog whose file cannot be read: ``how`` says why."""
    root = tmp_path / "old-project"
    path = thomas_project._live_file(root, BAD)
    path.parent.mkdir(parents=True)
    if how == "folder":
        path.mkdir()  # a folder where the file should be: reading it raises an OSError
    elif how == "corrupt":
        path.write_text('{"turns": [', encoding="utf-8")
    elif how == "bytes":
        path.write_bytes(b"\xff\xfe\x00bad")
    else:
        path.write_text("{}", encoding="utf-8")
    registry = forge_code_conversations._load_registry(p.catalog)
    registry[BAD] = {"project_root": str(root), "settings": {}}
    forge_code_conversations._write_registry(p.catalog, registry)
    return path


def _survey(p) -> list:
    """Survey as ``restart_pass`` does: a failed read raises and the survey is tried again, until it is skipped."""
    for _ in range(_restart().READ_ATTEMPTS):
        try:
            return _restart().survey(p.catalog, p.booted)
        except (OSError, ValueError):
            continue
    raise AssertionError("the unreadable conversation was never skipped")


def _deny(monkeypatch: pytest.MonkeyPatch, bad: Path) -> None:
    real = Path.open  # the survey streams the file: it opens it, it does not read it whole

    def open_file(self: Path, *args, **kwargs):
        if self == bad:
            raise PermissionError(13, "Access is denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["denied", "folder", "corrupt", "bytes"])
async def test_an_unreadable_conversation_does_not_stop_the_others_carrying_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    bad = _register_bad(p, tmp_path, "denied" if how == "denied" else how)
    if how == "denied":
        _deny(monkeypatch, bad)
    app = _app(p.catalog, starts := [])
    _survey(p)  # the pass retries it first; once it has stayed unreadable it is skipped

    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)

    assert report["resumed"] == [p.cid] and len(starts) == 1, report
    assert set(report["unreadable"]) == {BAD}, "the skipped conversation is listed, with its reason"
    assert BAD not in report["not_resumed"] and str(tmp_path) not in report["unreadable"][BAD]
    assert forge_code_store.load_conversation(p.root, p.cid)["turns"], "the readable one was started"


def test_the_warning_for_an_unreadable_conversation_is_logged_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    _deny(monkeypatch, _register_bad(p, tmp_path, "denied"))
    with caplog.at_level(logging.WARNING, logger="thomas.server.autopilot_restart"):
        _survey(p)
        for _ in range(3):
            _restart().survey(p.catalog, p.booted)
    named = [r for r in caplog.records if BAD in r.getMessage()]
    assert len(named) == 1 and "PermissionError" in named[0].getMessage()
    assert str(tmp_path) not in named[0].getMessage()


def test_a_corrupt_conversation_is_skipped_and_the_readable_one_is_found(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    _register_bad(p, tmp_path, "corrupt")
    found = _survey(p)
    assert [item.cid for item in found] == [p.cid]
    assert list(_restart().report()["unreadable"]) == [BAD]


@pytest.mark.asyncio
async def test_many_unreadable_records_cost_three_surveys_and_parse_unchanged_records_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from thomas.server.routes import self_project_listing_cache

    p = _stopped_run(tmp_path, kind="repair")
    registry = forge_code_conversations._load_registry(p.catalog)
    denied = set()
    for index in range(126):
        cid = f"fc_unreadable_{index}"
        path = thomas_project._live_file(p.root, cid)
        path.write_text("{}", encoding="utf-8")
        registry[cid] = {"project_root": str(p.root), "settings": {}}
        denied.add(path)
    forge_code_conversations._write_registry(p.catalog, registry)
    parse = self_project_listing_cache.read_conversation
    parsed = Counter()

    def read(path):
        parsed[path] += 1
        if path in denied:
            raise PermissionError(13, "Access is denied")
        return parse(path)

    monkeypatch.setattr(self_project_listing_cache, "read_conversation", read)
    restart = _restart()
    survey = restart.survey
    surveys = []

    def counted_survey(*args):
        surveys.append(None)
        assert len(surveys) <= 3, "unreadable records must fail together, not one per survey"
        return survey(*args)

    monkeypatch.setattr(restart, "survey", counted_survey)
    with caplog.at_level(logging.WARNING, logger=restart.__name__):
        for _ in range(2):
            with pytest.raises(PermissionError):
                restart.survey(p.catalog, p.booted)
        report = await restart.resume_interrupted(_app(p.catalog, starts := []), p.catalog, booted=p.booted)
    assert len(surveys) == 3
    assert report["resumed"] == [p.cid] and len(starts) == 1
    assert len(report["unreadable"]) == 126
    assert parsed[thomas_project._live_file(p.root, p.cid)] == 1
    assert all(parsed[path] == 3 for path in denied)
    for path in denied:
        assert any(path.stem in record.getMessage() and "skipped" in record.getMessage() for record in caplog.records)
    assert restart._pass.read_cache == {}, "release cached records when the survey succeeds"


@pytest.mark.parametrize("change", ["mtime", "size"])
def test_a_retry_reparses_a_record_when_its_stamp_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from thomas.server.routes import self_project_listing_cache

    p = _stopped_run(tmp_path, kind="repair")
    _deny(monkeypatch, _register_bad(p, tmp_path, "denied"))
    mine = thomas_project._live_file(p.root, p.cid)
    parse = self_project_listing_cache.read_conversation
    parsed = []

    def read(path):
        if path == mine:
            parsed.append(path)
        return parse(path)

    monkeypatch.setattr(self_project_listing_cache, "read_conversation", read)
    with pytest.raises(PermissionError):
        _restart().survey(p.catalog, p.booted)
    before = mine.stat()
    if change == "size":
        mine.write_bytes(mine.read_bytes() + b" ")
        os.utime(mine, ns=(before.st_atime_ns, before.st_mtime_ns))
    else:
        os.utime(mine, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
    with pytest.raises(PermissionError):
        _restart().survey(p.catalog, p.booted)
    assert len(parsed) == 2
    assert [item.cid for item in _restart().survey(p.catalog, p.booted)] == [p.cid]
    assert len(parsed) == 2


def test_stat_permission_failures_are_all_retried_and_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    _register_many_bad(p, tmp_path, 126)
    denied = {
        thomas_project._live_file(Path(row["project_root"]), cid)
        for cid, row in forge_code_conversations._load_registry(p.catalog).items()
        if cid != p.cid
    }
    stat = Path.stat
    attempts = Counter()

    def denied_stat(self, *args, **kwargs):
        if self in denied:
            attempts[self] += 1
            raise PermissionError(13, "cannot stat this conversation", str(self))
        return stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied_stat)
    with caplog.at_level(logging.WARNING, logger="thomas.server.autopilot_restart"):
        for _ in range(_restart().READ_ATTEMPTS - 1):
            with pytest.raises(PermissionError):
                _restart().survey(p.catalog, p.booted)
        found = _restart().survey(p.catalog, p.booted)
    assert [item.cid for item in found] == [p.cid]
    assert set(attempts.values()) == {_restart().READ_ATTEMPTS}
    skipped = _restart().report()["unreadable"]
    assert len(skipped) == 126
    assert all(any(cid in record.message for record in caplog.records) for cid in skipped)


def test_successful_settled_stat_breaks_consecutive_read_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    mine = _register_bad(p, tmp_path, "settled")
    row = {"project_root": str(tmp_path / "old-project"), "settings": {}}
    stat = Path.stat
    denied = False

    def sometimes_denied(self, *args, **kwargs):
        if self == mine and denied:
            raise PermissionError(13, "temporarily denied")
        return stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", sometimes_denied)
    for _ in range(4):
        denied = False
        assert _restart()._unfinished(p.catalog, BAD, row, p.booted) is None
        assert BAD not in _restart()._pass.read_failures
        denied = True
        assert _restart()._unfinished(p.catalog, BAD, row, p.booted) is None
        assert _restart()._pass.read_failures[BAD] == 1
    assert _restart().report()["unreadable"] == {}


@pytest.mark.parametrize("settled", [False, True])
def test_stat_failure_invalidates_cached_reads_before_access_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settled: bool
) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    if settled:
        mine = _register_bad(p, tmp_path, "settled")
        cid = BAD
        row = {"project_root": str(tmp_path / "old-project"), "settings": {}}
    else:
        cid = p.cid
        row = forge_code_conversations._load_registry(p.catalog)[cid]
        mine = thomas_project._live_file(Path(row["project_root"]), cid)
    restart = _restart()
    restart._unfinished(p.catalog, cid, row, p.booted)
    stat = Path.stat

    def denied_stat(self, *args, **kwargs):
        if self == mine:
            raise PermissionError(13, "metadata temporarily inaccessible")
        return stat(self, *args, **kwargs)

    with monkeypatch.context() as metadata:
        metadata.setattr(Path, "stat", denied_stat)
        restart._unfinished(p.catalog, cid, row, p.booted)
    _deny(monkeypatch, mine)
    for _ in range(restart.READ_ATTEMPTS - 1):
        assert restart._unfinished(p.catalog, cid, row, p.booted) is None
    assert restart._pass.read_failures[cid] == restart.READ_ATTEMPTS
    assert cid in restart.report()["unreadable"]


def test_a_successful_read_clears_an_earlier_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    mine = _register_bad(p, tmp_path, "recovered")
    row = {"project_root": str(tmp_path / "old-project"), "settings": {}}
    with monkeypatch.context() as denied:
        _deny(denied, mine)
        for _ in range(_restart().READ_ATTEMPTS):
            _restart()._unfinished(p.catalog, BAD, row, p.booted)
    assert BAD in _restart().report()["unreadable"]
    assert _restart()._unfinished(p.catalog, BAD, row, p.booted) is None
    assert BAD not in _restart().report()["unreadable"]


def test_a_missing_file_does_not_clear_an_unreadable_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    mine = _register_bad(p, tmp_path, "denied")
    row = {"project_root": str(tmp_path / "old-project"), "settings": {}}
    with monkeypatch.context() as denied:
        _deny(denied, mine)
        for _ in range(_restart().READ_ATTEMPTS):
            _restart()._unfinished(p.catalog, BAD, row, p.booted)
    mine.unlink()
    assert _restart()._unfinished(p.catalog, BAD, row, p.booted) is None
    assert BAD in _restart().report()["unreadable"]


def test_when_everything_is_readable_nothing_is_listed_unreadable(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    _register_bad(p, tmp_path, "empty")  # readable, and not interrupted
    found = _restart().survey(p.catalog, p.booted)
    assert [item.cid for item in found] == [p.cid]
    assert _restart().report()["unreadable"] == {}


@pytest.mark.asyncio
async def test_a_transient_read_failure_is_retried_and_the_conversation_still_carries_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    real, failed = Path.open, []
    mine = thomas_project._live_file(p.root, p.cid)

    def open_file(self: Path, *args, **kwargs):
        if self == mine and not failed:
            failed.append(self)
            raise PermissionError(13, "the file is being replaced")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    with pytest.raises(PermissionError):
        _restart().survey(p.catalog, p.booted)  # as before: the survey fails, the pass tries it again
    app = _app(p.catalog, starts := [])
    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert report["resumed"] == [p.cid] and len(starts) == 1
    assert report["unreadable"] == {}, "one failed read is not a skipped conversation"


def _register_many_bad(p, tmp_path: Path, count: int) -> None:
    registry = forge_code_conversations._load_registry(p.catalog)
    for n in range(count):
        cid = f"fc_20260727T164835_{n:06x}"
        path = thomas_project._live_file(tmp_path / f"old-{n}", cid)
        path.parent.mkdir(parents=True)
        path.mkdir()  # a folder where the file should be: every read of it fails
        registry[cid] = {"project_root": str(tmp_path / f"old-{n}"), "settings": {}}
    forge_code_conversations._write_registry(p.catalog, registry)


def test_many_unreadable_conversations_cost_no_more_surveys_than_one(tmp_path: Path) -> None:
    """On 2026-11-13 a server that could not open 126 records ran the survey 2168 times in one morning: each failed
    read stopped the survey at that record, so every unreadable record cost ``READ_ATTEMPTS`` whole surveys."""
    p = _stopped_run(tmp_path, kind="repair")
    _register_many_bad(p, tmp_path, 12)
    surveys, found = 0, None
    while found is None:
        surveys += 1
        assert surveys <= _restart().READ_ATTEMPTS, "each unreadable record cost surveys of its own"
        try:
            found = _restart().survey(p.catalog, p.booted)
        except (OSError, ValueError):
            continue
    assert [item.cid for item in found] == [p.cid]
    assert len(_restart().report()["unreadable"]) == 12


def test_a_retried_survey_does_not_parse_again_a_record_that_needs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server.routes import self_project_listing_cache as cache

    p = _stopped_run(tmp_path, kind="repair")
    settled = _register_bad(p, tmp_path, "empty")  # readable, and not interrupted
    _register_many_bad(p, tmp_path, 1)  # what makes the pass survey again
    real, parsed = cache.read_conversation, []

    def read(path: Path):
        parsed.append(Path(path))
        return real(path)

    monkeypatch.setattr(cache, "read_conversation", read)
    _survey(p)
    assert parsed.count(settled) == 1, "an unchanged record that needed nothing was parsed on every retry"
    settled.write_text('{"turns": []}', encoding="utf-8")  # it changed: the next survey reads it again
    _restart().survey(p.catalog, p.booted)
    assert parsed.count(settled) == 2
