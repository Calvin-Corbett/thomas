"""A landing that changes Python must not retire the server while a hand-in check is still running.

On 2026-11-06 the server retired itself within a minute of each landing that changed Python (13:51, 14:38, 15:20). Each
time it ended the checks that were running, 40 and 45 minutes into their work with nine shards still going, and a
hand-in check takes longer than the gap between those landings, so none finished all afternoon. The capacity ledger
lists every admitted check with its owner; the reload now waits for them.
"""

import pytest

from tests.test_background_thomas_reloads_landed_code_when_idle import scenario


def _check(id_: str = "check:thomas-abc", state: str = "admitted") -> dict:
    return {"key": id_, "id": id_, "kind": "check", "state": state, "owner": "owner-1-aa"}


def _shard(state: str = "admitted") -> dict:
    return {"key": "s1", "id": "shard:0123", "kind": "shard", "state": state, "owner": "owner-1-aa"}


def test_only_checks_and_shards_holding_a_place_count(monkeypatch, tmp_path):
    reload, _app, _event, _answers = scenario(monkeypatch, tmp_path)
    pool = {"key": "pool_size:o", "id": "pool_size:o", "kind": "pool_size", "state": "recorded", "owner": "o"}

    assert reload._admitted_checks([]) == 0
    assert reload._admitted_checks([pool, _check(state="waiting"), _shard(state="waiting")]) == 0
    assert reload._admitted_checks([pool, _check(), _shard()]) == 2


@pytest.mark.asyncio
async def test_a_running_check_is_work_the_reload_waits_for(monkeypatch, tmp_path):
    reload, app, _event, answers = scenario(monkeypatch, tmp_path)
    answers["work"] = ("Build run",)
    monkeypatch.setattr(reload.capacity_ledger, "rows", lambda: [_check(), _shard()])

    assert await reload.waiting_work(app) == ("Build run", reload.CHECK_WORKERS)

    monkeypatch.setattr(reload.capacity_ledger, "rows", lambda: [])
    assert await reload.waiting_work(app) == ("Build run",)


@pytest.mark.asyncio
async def test_a_ledger_that_cannot_be_read_holds_the_reload(monkeypatch, tmp_path):
    """Windows refuses a read while another process replaces the file; an unread ledger may hide a running check."""
    reload, app, _event, answers = scenario(monkeypatch, tmp_path)
    answers["work"] = ()

    def busy():
        raise OSError("the ledger is locked")

    monkeypatch.setattr(reload.capacity_ledger, "rows", busy)

    assert await reload.waiting_work(app) == (reload.CHECK_WORKERS,)


@pytest.mark.asyncio
async def test_a_landing_does_not_retire_the_server_while_a_check_runs(monkeypatch, tmp_path):
    reload, app, event, _answers = scenario(monkeypatch, tmp_path)
    monkeypatch.setattr(reload.capacity_ledger, "rows", lambda: [_check(), _shard()])
    quiet = None
    for at in (0, 31, 62, 93, 124):
        quiet = await reload.check_once(app, quiet, at, work=await reload.waiting_work(app))

    assert not event.is_set(), "the server retired itself with a check still running"

    monkeypatch.setattr(reload.capacity_ledger, "rows", lambda: [])
    for at in (155, 186, 217):
        quiet = await reload.check_once(app, quiet, at, work=await reload.waiting_work(app))

    assert event.is_set(), "with no check left the reload must go ahead"
