"""The outside hand-in command refuses what the promoter or you would refuse, in plain words, and only prints by default.

Proves scripts.crew.hand_in_outside, scripts.crew.hand_in_outside_build and scripts.crew.hand_in_outside_checks on a
throwaway checkout and clone. Every inbox is a folder under tmp_path; the real cage is never touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as promoter
from scripts.crew import hand_in_outside as cli

from tests.hand_in_outside_support import Repos, commit, git, make_repos, write


def _clean(change) -> tuple[bool, str, list[str]]:
    return True, "", []


def _unused_import(change) -> tuple[bool, str, list[str]]:
    return True, "", ["pkg/tool.py: F401 unused import"]


@pytest.fixture
def repos(tmp_path):
    return make_repos(tmp_path / "repos")


def _run(
    repos: Repos, tmp_path: Path, tip: str, *extra: str, lint=_clean, sleep=lambda s: None, accept: bool = True
) -> int:
    argv = ["--clone", str(repos.clone), "--base", repos.base, "--tip", tip, "--checkout", str(repos.checkout)]
    agreed = ["--accept-card-wording"] if accept else []
    return cli.main([*argv, "--inbox", str(tmp_path / "cage" / "inbox"), *agreed, *extra], lint=lint, sleep=sleep)


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.relative_to(root).parts}


def test_without_drop_it_only_prints_and_writes_nothing(repos, tmp_path, capsys):
    before = _files(tmp_path)
    assert _run(repos, tmp_path, repos.plain) == 0
    out = capsys.readouterr().out
    assert "Dry run: nothing was written" in out and "feat: tool answers" in out and "applies to" in out
    assert _files(tmp_path) == before and not (tmp_path / "cage").exists()


def test_a_drop_writes_only_into_the_inbox_and_names_the_outbox_files_to_watch(repos, tmp_path, capsys):
    before = _files(tmp_path)
    assert _run(repos, tmp_path, repos.plain, "--drop", "--agent", "codex", "--title", "Add the tool") == 0
    out = capsys.readouterr().out
    added = _files(tmp_path) - before
    (sid,) = {Path(name).parts[2] for name in added if len(Path(name).parts) > 2}
    assert added == {"cage", "cage/inbox", f"cage/inbox/{sid}", f"cage/inbox/{sid}/change.patch"} | {
        f"cage/inbox/{sid}/submission.json"
    }
    assert f"{sid}.pending.json" in out and f"{sid}.verdict.json" in out
    meta, _ = promoter.read_submission(tmp_path / "cage" / "inbox" / sid)
    assert meta["agent"] == "codex" and meta["message"] == "Add the tool"
    assert meta["base"] == git(repos.checkout, "rev-parse", "dev")
    assert "ruff and the growth rule found nothing" in meta["checked"]


def test_a_drop_without_an_inbox_in_a_test_never_reaches_the_real_one(repos, capsys):
    argv = ["--clone", str(repos.clone), "--base", repos.base, "--tip", repos.plain, "--checkout", str(repos.checkout)]
    assert cli.main([*argv, "--drop", "--accept-card-wording"], lint=_clean) == 2
    assert "must pass --inbox" in capsys.readouterr().out


def test_a_guarded_file_is_refused_with_the_card_it_would_need(repos, tmp_path, capsys):
    assert _run(repos, tmp_path, repos.guarded, "--drop") == 2
    out = capsys.readouterr().out
    assert "agent_safety.toml" in out and "own card" in out and "--allow-protected" in out
    assert not (tmp_path / "cage").exists()


def test_allowing_a_guarded_file_hands_it_in_and_says_a_card_will_be_needed(repos, tmp_path, capsys):
    assert _run(repos, tmp_path, repos.guarded, "--drop", "--allow-protected") == 0
    assert "A card will be needed for: agent_safety.toml" in capsys.readouterr().out
    assert len(list((tmp_path / "cage" / "inbox").iterdir())) == 1


def test_a_change_that_no_longer_applies_to_dev_is_refused_naming_the_file(repos, tmp_path, capsys):
    write(repos.checkout, "pkg/tool.py", "VALUE = 99\n")
    commit(repos.checkout, "dev moved")
    assert _run(repos, tmp_path, repos.plain, "--drop") == 2
    out = capsys.readouterr().out
    assert "does not apply to dev" in out and "pkg/tool.py" in out and "Rebase" in out
    assert not (tmp_path / "cage").exists()


def test_a_patch_the_promoter_would_refuse_is_refused_before_a_card(repos, tmp_path, capsys):
    git(repos.clone, "checkout", "-q", "-b", "odd", repos.base)
    write(repos.clone, "runtime/state.json", "{}\n")
    tip = commit(repos.clone, "touch runtime")
    assert _run(repos, tmp_path, tip, "--drop") == 2
    assert "promoter would refuse" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("base", "tip", "words"),
    [("tip", "tip", "no commits"), ("tip", "base", "not an ancestor"), ("base", "nothere", "not a commit")],
)
def test_a_bad_range_is_refused_in_plain_words(repos, tmp_path, capsys, base, tip, words):
    pick = {"base": repos.base, "tip": repos.plain, "nothere": "nothere"}
    argv = ["--clone", str(repos.clone), "--base", pick[base], "--tip", pick[tip], "--checkout", str(repos.checkout)]
    assert cli.main([*argv, "--inbox", str(tmp_path / "inbox"), "--drop", "--accept-card-wording"], lint=_clean) == 2
    assert words in capsys.readouterr().out and not (tmp_path / "inbox").exists()


def test_findings_refuse_unless_they_are_allowed_and_then_are_handed_in_with_the_change(repos, tmp_path, capsys):
    assert _run(repos, tmp_path, repos.plain, "--drop", lint=_unused_import) == 2
    assert "F401" in capsys.readouterr().out and not (tmp_path / "cage").exists()
    assert _run(repos, tmp_path, repos.plain, "--drop", "--allow-findings", lint=_unused_import) == 0
    (sub,) = (tmp_path / "cage" / "inbox").iterdir()
    assert "F401" in promoter.read_submission(sub)[0]["checked"]


def test_a_change_that_grows_a_file_past_the_limit_is_refused(repos, tmp_path, capsys):
    git(repos.clone, "checkout", "-q", "-b", "big", repos.base)
    write(repos.clone, "pkg/big.py", "".join(f"X{i} = {i}\n" for i in range(301)))
    tip = commit(repos.clone, "big")
    assert _run(repos, tmp_path, tip, "--drop") == 2
    assert "pkg/big.py grows by 301 lines" in capsys.readouterr().out


def test_ruff_passes_a_clean_change_and_finds_an_unused_import_the_change_adds(repos, tmp_path, capsys):
    assert _run(repos, tmp_path, repos.plain, lint=cli.checks.ruff_findings) == 0
    git(repos.clone, "checkout", "-q", "-b", "dirty", repos.base)
    write(repos.clone, "pkg/dirty.py", "import os\n")
    tip = commit(repos.clone, "dirty")
    capsys.readouterr()
    assert _run(repos, tmp_path, tip, lint=cli.checks.ruff_findings) == 2
    assert "F401" in capsys.readouterr().out


def test_ruff_reads_a_change_in_a_package_the_way_the_repo_does(repos, tmp_path, capsys):
    git(repos.clone, "checkout", "-q", "-b", "uses", repos.base)
    write(repos.clone, "pkg/uses.py", "import json\n\nfrom pkg import tool\n\nprint(json, tool)\n")
    tip = commit(repos.clone, "uses the package")
    assert _run(repos, tmp_path, tip, lint=cli.checks.ruff_findings) == 0, capsys.readouterr().out


def test_watching_prints_the_verdict_the_promoter_writes_and_exits_by_its_status(repos, tmp_path, capsys):
    outbox = tmp_path / "cage" / "outbox"

    def promoter_answers(seconds: float) -> None:
        sid = next((tmp_path / "cage" / "inbox").iterdir()).name
        outbox.mkdir(exist_ok=True)
        verdict = {"status": "landed", "commit_sha": "abc"}
        (outbox / f"{sid}.verdict.json").write_text(json.dumps(verdict), encoding="utf-8")

    assert _run(repos, tmp_path, repos.plain, "--drop", "--watch", sleep=promoter_answers) == 0
    assert '"status": "landed"' in capsys.readouterr().out


def test_watching_gives_up_only_when_told_to_and_says_which_file_to_keep_watching(repos, tmp_path, capsys):
    assert _run(repos, tmp_path, repos.plain, "--drop", "--watch", "--give-up-after", "0") == 3
    assert ".verdict.json" in capsys.readouterr().out.splitlines()[-1]
    assert _run(repos, tmp_path, repos.plain, "--watch") == 2  # watch follows a drop


def test_ruff_knows_the_changes_own_package_is_first_party_so_a_blank_line_before_it_is_right(repos, tmp_path, capsys):
    """Only a package-aware lint folder (an __init__.py in every folder above a changed file) calls pkg first-party."""
    git(repos.clone, "checkout", "-q", "-b", "firstparty", repos.base)
    write(
        repos.clone,
        "pkg/uses.py",
        "import json\n\nimport requests\n\nfrom pkg import tool\n\nprint(json, requests, tool)\n",
    )
    tip = commit(repos.clone, "uses the package and a third-party one")
    assert _run(repos, tmp_path, tip, lint=cli.checks.ruff_findings) == 0, capsys.readouterr().out


def test_without_the_package_files_that_same_change_is_wrongly_called_unsorted(repos, tmp_path, capsys, monkeypatch):
    """The other half: the same change fails when the lint folder has no packages, so the test above can fail."""
    monkeypatch.setattr(cli.checks, "_parents", lambda name: [])
    git(repos.clone, "checkout", "-q", "-b", "firstparty2", repos.base)
    write(
        repos.clone,
        "pkg/uses.py",
        "import json\n\nimport requests\n\nfrom pkg import tool\n\nprint(json, requests, tool)\n",
    )
    tip = commit(repos.clone, "uses the package and a third-party one")
    assert _run(repos, tmp_path, tip, lint=cli.checks.ruff_findings) == 2
    assert "I001" in capsys.readouterr().out
