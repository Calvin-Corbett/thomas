"""An outside hand-in does not slip a false claim into the commit the promoter writes.

Proves scripts.crew.hand_in_outside and scripts.crew.hand_in_outside_build against the promoter's own commit wording
(scripts.cage.self_change_promoter). The wording is the promoter's and is pinned, so --drop refuses until it is accepted.
"""

from __future__ import annotations

import pytest
from scripts.crew import hand_in_outside as cli
from scripts.crew import hand_in_outside_build as build

from tests.hand_in_outside_support import Repos, make_repos


@pytest.fixture
def repos(tmp_path):
    return make_repos(tmp_path / "repos")


def _argv(repos: Repos, tmp_path, *extra: str) -> list[str]:
    return [
        *("--clone", str(repos.clone), "--base", repos.base, "--tip", repos.plain),
        *("--checkout", str(repos.checkout), "--inbox", str(tmp_path / "cage" / "inbox")),
        *("--agent", "codex", "--title", "Add the tool"),
        *extra,
    ]


def _clean(change):
    return True, "", []


def test_the_dry_run_prints_the_exact_commit_text_you_would_get(repos, tmp_path, capsys):
    assert cli.main(_argv(repos, tmp_path), lint=_clean) == 0
    out = capsys.readouterr().out
    assert "self-fix: Outside agent codex: Add the tool" in out
    assert "Made in green (execution none-outside-agent)" in out and "(execution )" not in out
    assert "passed by the checker and a second look" in out  # the window wording, shown so you can see it


def test_a_drop_is_refused_until_the_wording_is_accepted_and_names_the_wording_and_the_file(repos, tmp_path, capsys):
    assert cli.main(_argv(repos, tmp_path, "--drop"), lint=_clean) == 2
    out = capsys.readouterr().out
    assert "Made in green" in out and "passed by the checker and a second look" in out
    assert "scripts/cage/self_change_promoter.py" in out and "--accept-card-wording" in out
    assert not (tmp_path / "cage").exists()
    assert cli.main(_argv(repos, tmp_path, "--drop", "--accept-card-wording"), lint=_clean) == 0
    assert len(list((tmp_path / "cage" / "inbox").iterdir())) == 1


def test_the_flags_help_quotes_the_wording(capsys):
    text = cli._parser().format_help()
    assert "Made in green" in text and "second look" in text and "scripts/cage/self_change_promoter.py" in text


def test_the_manifest_carries_a_real_execution_id_and_an_honest_first_line(repos):
    change = build.read_change(repos.clone, repos.base, repos.plain)
    manifest = build.manifest_for(
        change, sid="self-outside-x-1", dev_tip="a" * 40, checkout=repos.checkout,
        title="T", agent="codex", checked="n", now=1.0,
    )  # fmt: skip
    assert manifest["execution_id"] and str(manifest["summary"]).startswith("Outside agent codex: T")
    approved, window = build.card_text(manifest)
    assert approved.startswith("self-fix: Outside agent codex: T") and window
