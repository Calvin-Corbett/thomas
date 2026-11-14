"""A Build start records which agent runs it, and the Praxis journal takes that record.

bc982119 (the Agent choice, approved at your sign-in on 2026-09-25) made every Build launch write an ``agent`` key into
the Praxis launch journal, and ``PraxisRunJournal.record_launch`` refused any key it did not know: once the server
restarted on that code, every Build start -- from Build, a Chat hand-off, Autopilot or a Thomas project round -- would
have answered HTTP 500 "invalid Praxis launch context". The restart scan read the same list, so a run recorded with an
agent could not be recovered either.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.server.praxis import startup
from thomas.server.praxis.recovery import PraxisRunJournal


def _context(project: Path, **extra: str) -> dict[str, str]:
    base = {
        "project_root": str(project),
        "family": "claude",
        "model_id": "opus",
        "reviewer_model": "",
        "dispatch_model": "claude:opus",
        "praxis_reviewer_profile": "",
        "praxis_reviewer_model": "",
    }
    return {**base, **extra}


def test_the_journal_takes_a_launch_that_names_its_agent(tmp_path: Path) -> None:
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    journal.record_launch("run-1", _context(tmp_path, agent="claude_code", conversation_id="fc_1"))
    saved = journal.load("run-1")
    assert saved is not None and saved["launch_context"]["agent"] == "claude_code"


def test_a_launch_recorded_before_the_agent_choice_still_restores(tmp_path: Path) -> None:
    project, settings, conversation = startup._restore_settings(_context(tmp_path, conversation_id="fc_1"))
    assert project == tmp_path.resolve() and conversation == "fc_1"
    assert getattr(settings, "agent", "") == ""


def test_a_launch_that_names_its_agent_restores_with_it(tmp_path: Path) -> None:
    _, settings, _ = startup._restore_settings(_context(tmp_path, agent="thomas"))
    assert settings.agent == "thomas"


def test_an_unknown_key_is_still_refused(tmp_path: Path) -> None:
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    with pytest.raises(ValueError, match="invalid Praxis launch context"):
        journal.record_launch("run-2", _context(tmp_path, token="not-a-launch-field"))
    with pytest.raises(ValueError):
        startup._restore_settings(_context(tmp_path, token="x"))


def test_a_secret_store_that_cannot_answer_never_fails_a_build_start() -> None:
    # 34c84745 reads a saved Anthropic key from the app's secret store while settling Build's settings. A store
    # without get (or one that raises) made every /api/evolve/agent/send answer 500; it means "no saved key".
    from types import SimpleNamespace

    from thomas.server.app_keys import APP_SECRETS
    from thomas.server.routes.evolve_agent_agents_routes import saved_anthropic_key

    class _Raising:
        def get(self, _profile: str) -> str:
            raise OSError("the secret store is unavailable")

    for store in (object(), _Raising()):
        app = {APP_SECRETS: store, "config": SimpleNamespace(models={})}
        assert isinstance(saved_anthropic_key(app), str)
