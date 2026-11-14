"""A change the check cannot apply to dev is sent back naming what did not apply (2026-10-26).

git says "Falling back to direct application..." once for every file whose blob it does not have. A change of a few
hundred files filled the 2,000 characters the team is shown with that line alone, so c23dd7 was told its change would
not apply to dev and not which file or line refused. The errors now come first.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from thomas.server import green_checkout
from thomas.server.precard import scratch

FILES = 300


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _patch() -> str:
    """Every file's preimage names a blob the copy does not have; only ``refuses.txt`` differs from what it expects."""
    parts = []
    for name, old, new in [(f"f{i:03d}.txt", f"same {i}", f"new {i}") for i in range(FILES)] + [
        ("refuses.txt", "what the change expected", "the change")
    ]:
        parts.append(
            f"diff --git a/{name} b/{name}\nindex 1111111..2222222 100644\n--- a/{name}\n+++ b/{name}\n"
            f"@@ -1 +1 @@\n-{old}\n+{new}\n"
        )
    return "".join(parts)


def test_the_files_that_did_not_apply_reach_the_team(tmp_path: Path) -> None:
    repo = tmp_path / "dev"
    repo.mkdir()
    _git(repo, "init", "-q")
    for i in range(FILES):
        (repo / f"f{i:03d}.txt").write_text(f"same {i}\n", encoding="utf-8", newline="\n")
    (repo / "refuses.txt").write_text("what dev has now\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "dev")
    green = green_checkout.Green(execution_id="x", work=repo, git_dir=repo / ".git", base="HEAD", blue=repo)

    said = scratch.apply_change(green, _patch())

    assert "refuses.txt" in said, said[:400]
    assert said.startswith("error:"), said[:200]
    assert "Falling back to direct application" not in said
    assert "applied them directly" in said and len(said) <= 2000


def test_a_file_named_for_conflicts_is_not_taken_for_one(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """2026-10-27: 'Applied patch to tests/test_a_conflict_the_check_finds_starts_merged.py cleanly.' was put first
    because its name holds the word, ahead of the files that really conflicted."""
    said = "\n".join(
        [
            "Applied patch to 'tests/test_a_conflict_the_check_finds_starts_merged.py' cleanly.",
            "Applied patch to 'thomas/server/precard/review.py' with conflicts.",
            "U thomas/server/precard/review.py",
        ]
    )
    monkeypatch.setattr(
        green_checkout, "git", lambda *_args: subprocess.CompletedProcess([], 1, stdout="", stderr=said)
    )
    green = green_checkout.Green(execution_id="x", work=tmp_path, git_dir=tmp_path, base="HEAD", blue=tmp_path)
    lines = scratch.apply_change(green, "diff --git a/x b/x\n").splitlines()
    assert lines[:2] == [
        "Applied patch to 'thomas/server/precard/review.py' with conflicts.",
        "U thomas/server/precard/review.py",
    ]
    assert lines[2].endswith("cleanly.")
