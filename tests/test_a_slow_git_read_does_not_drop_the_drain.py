"""A git read that fails or runs out of time is not read as "nothing landed".

The reload watcher asks git three things each look, each with four seconds to answer. Any of them failing gave the
same answer as "there is no landed change", so the watcher cleared its notice, ended the drain and resumed the Builds
it had asked to stop; half a minute later git answered, the drain began again and the Builds were stopped again. On
2026-11-09, with the PC at 100%, one landing's drain began nine times in nineteen minutes and eight Builds were
stopped after about two minutes of work each.
"""

from __future__ import annotations

import pytest

from tests.test_background_thomas_reloads_landed_code_when_idle import scenario


@pytest.fixture
def draining(monkeypatch, tmp_path):
    reload, app, event, answers = scenario(monkeypatch, tmp_path)
    answers["work"] = ("Build run",)
    resumed: list[str] = []
    finished: list[str] = []

    async def resume(_app):
        resumed.append("resumed")

    async def finish_drain(_app):
        finished.append("finished")

    monkeypatch.setattr(reload.landed_code_resume, "resume", resume)
    monkeypatch.setattr(reload.landed_code_resume, "finish_drain", finish_drain)
    monkeypatch.setattr(reload.landed_code_resume, "remember", lambda _app: None)
    return reload, app, event, answers, resumed


def _git_that_fails_on(monkeypatch, reload, word):
    real = reload._git

    def git(*args):
        return None if word in args else real(*args)

    monkeypatch.setattr(reload, "_git", git)


@pytest.mark.asyncio
@pytest.mark.parametrize("word", ["rev-parse", "old", "HEAD"])  # the head, what changed, what is uncommitted
async def test_a_read_that_fails_leaves_the_drain_and_the_builds_as_they_are(draining, monkeypatch, word) -> None:
    reload, app, event, answers, resumed = draining
    await reload.check_once(app, None, 100.0)
    drain = app[reload.APP_LANDED_CODE_DRAIN]
    notice = app.get(reload.APP_LANDED_CODE_NOTICE)
    assert drain["head"] == "new" and resumed == []

    _git_that_fails_on(monkeypatch, reload, word)
    await reload.check_once(app, None, 130.0)

    assert app.get(reload.APP_LANDED_CODE_DRAIN) is drain, "the drain is the same one, not ended and begun again"
    assert app.get(reload.APP_LANDED_CODE_NOTICE) == notice
    assert resumed == [], "no Build is resumed only to be stopped again"
    assert not event.is_set()


@pytest.mark.asyncio
async def test_a_change_that_really_went_away_still_ends_the_drain(draining) -> None:
    reload, app, event, answers, resumed = draining
    await reload.check_once(app, None, 100.0)
    assert reload.APP_LANDED_CODE_DRAIN in app
    answers["head"] = "old"  # dev is back where this server started
    await reload.check_once(app, None, 130.0)
    assert reload.APP_LANDED_CODE_DRAIN not in app and resumed == ["resumed"]
