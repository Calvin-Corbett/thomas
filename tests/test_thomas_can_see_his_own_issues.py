"""Thomas records his own failures and could not read them back.

Five modules call ``issue_ledger.record_issue`` and a route renders it for a
person, but nothing ever put it in front of the model. Thomas has been writing
down what goes wrong with him for months and had no way to look at it, so he
could never pick one and fix it.

Owner direction: "he gets an issue -- at least the ones he can see -- and fixes
it." This is the seeing half.

A raw tail of the log is the wrong shape for that. The same failure repeats
hundreds of times, so a chronological list is mostly the same line over and
over and the newest thing is rarely the worst thing. What a fixer needs is a
work queue: one row per distinct failure, how often it happened, and the
loudest first.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from thomas.server import issue_ledger
from thomas.tools.self_issues import SelfIssuesTool


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    return tmp_path


def _record(repo: Path, message: str, *, kind: str = "worker_failed", surface: str = "chat", times: int = 1) -> None:
    for _ in range(times):
        issue_ledger.record_issue(surface=surface, kind=kind, message=message, repo_root=repo)


@pytest.mark.asyncio
async def test_thomas_can_read_back_a_failure_he_recorded(repo: Path) -> None:
    _record(repo, "browser.open refused a file:// url")

    result = await SelfIssuesTool(issue_ledger.recent_issues, repo_root=repo).execute({})

    assert result.ok
    assert "browser.open refused a file:// url" in str(result.data)


@pytest.mark.asyncio
async def test_the_same_failure_many_times_is_one_row_with_a_count(repo: Path) -> None:
    """A work queue, not a log. Otherwise the list is one line repeated."""
    _record(repo, "worker crashed on startup", times=12)

    text = str((await SelfIssuesTool(issue_ledger.recent_issues, repo_root=repo).execute({})).data)

    assert text.count("worker crashed on startup") == 1, "the same failure was listed more than once"
    assert "12" in text, "how often it happened is what makes it worth fixing first"


@pytest.mark.asyncio
async def test_the_loudest_problem_is_listed_first(repo: Path) -> None:
    """Fix what hurts most, not what happened most recently."""
    _record(repo, "rare hiccup", times=1)
    _record(repo, "constant grinding failure", times=20)

    text = str((await SelfIssuesTool(issue_ledger.recent_issues, repo_root=repo).execute({})).data)

    assert text.index("constant grinding failure") < text.index("rare hiccup")


@pytest.mark.asyncio
async def test_an_empty_ledger_says_so_instead_of_failing(repo: Path) -> None:
    """Nothing wrong is a real answer, and not an error."""
    result = await SelfIssuesTool(issue_ledger.recent_issues, repo_root=repo).execute({})

    assert result.ok
    assert "no issues" in str(result.data).casefold()


@pytest.mark.asyncio
async def test_old_noise_falls_out_of_the_window(repo: Path) -> None:
    """Something that stopped happening a week ago is not today's work."""
    old = (datetime.now(timezone.utc) - timedelta(days=7)).replace(microsecond=0).isoformat()
    path = repo / "runtime" / "logs" / "issues.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'{{"ts": "{old}", "surface": "chat", "kind": "worker_failed",'
        ' "message": "ancient history", "context": {}}\n',
        encoding="utf-8",
    )
    _record(repo, "happening right now")

    text = str((await SelfIssuesTool(issue_ledger.recent_issues, repo_root=repo).execute({"hours": 24})).data)

    assert "happening right now" in text
    assert "ancient history" not in text


@pytest.mark.asyncio
async def test_the_surface_is_named_so_he_knows_where_to_look(repo: Path) -> None:
    _record(repo, "canvas worker died", surface="canvas", kind="worker_failed")

    text = str((await SelfIssuesTool(issue_ledger.recent_issues, repo_root=repo).execute({})).data)

    assert "canvas" in text
