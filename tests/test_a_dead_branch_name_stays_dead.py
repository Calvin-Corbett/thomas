"""A dead branch name stays dead -- the pre-push side of the graveyard.

WHY THIS EXISTS: ``merge_resurrection_gate.py`` stops a dead FILE path from
riding back in on a merge; nothing stopped a dead BRANCH NAME from riding
back in on a push. git's pre-push hook sees a ref about to be created and
nothing more -- it cannot tell "never used" from "deliberately killed".
``dead_ref_gate.py`` is that distinction, made enforceable.

Five contracts pinned here (plan:
the internal design record Task 4):

1. a dead branch name refused on a create-push (remote sha1 all zeros).
2. an alive (never-recorded) branch name passes.
3. an approved resurrection of a dead name passes.
4. an UPDATE to an already-existing remote ref (non-zero remote sha1) is
   never gated, even for a dead name -- only ref CREATION is checked.
5. the ``--ref`` argv fallback (used by tests, CI, and non-hook callers)
   checks a single name directly without touching stdin.

Uses the real graveyard.py API to write every fixture's death record --
never hand-written JSON -- so this breaks the same way production would if
the record shape ever changed (same discipline as
test_every_enforcing_gate_can_fail.py's merge-resurrection fixture).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "forge" / "gates" / "dead_ref_gate.py"

sys.path.insert(0, str(REPO_ROOT))
from scripts.forge import graveyard  # noqa: E402

_ZERO_SHA = "0" * 40


def _run_gate(repo: Path, args: list[str], *, stdin_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE), "--repo-root", str(repo), *args],
        input=stdin_text,
        capture_output=True,
        text=True,
    )


def _creating_push_line(name: str) -> str:
    """A pre-push stdin line for a push that CREATES refs/heads/<name> on the
    remote: local sha is any real-looking sha, remote sha is all zeros."""
    return f"refs/heads/{name} deadbeef00000000000000000000000000000000 refs/heads/{name} {_ZERO_SHA}"


def _updating_push_line(name: str) -> str:
    """A pre-push stdin line for a push that UPDATES an already-existing
    remote ref: remote sha is non-zero."""
    return f"refs/heads/{name} deadbeef00000000000000000000000000000000 refs/heads/{name} cafef00dcafef00dcafef00dcafef00dcafef00d"


# ---------------------------------------------------------------------------
# 1. a dead name is refused on a create-push
# ---------------------------------------------------------------------------


def test_a_dead_branch_name_is_refused_on_a_create_push_via_stdin(tmp_path: Path) -> None:
    death_id = graveyard.record_death(
        tmp_path, "branch", "old-experiment", "deadsha", reason="superseded by dev", by="test-suite"
    )

    proc = _run_gate(tmp_path, [], stdin_text=_creating_push_line("old-experiment") + "\n")
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0, combined
    assert "old-experiment" in combined
    assert death_id in combined


def test_a_dead_branch_name_is_refused_via_the_ref_argv_fallback(tmp_path: Path) -> None:
    graveyard.record_death(tmp_path, "branch", "final", "deadsha", reason="seeded: generic worktree name", by="seed")

    proc = _run_gate(tmp_path, ["--ref", "final"])
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0, combined
    assert "final" in combined


# ---------------------------------------------------------------------------
# 2. an alive name passes
# ---------------------------------------------------------------------------


def test_an_alive_branch_name_passes_on_a_create_push(tmp_path: Path) -> None:
    graveyard.record_death(tmp_path, "branch", "old-experiment", "deadsha", reason="dead", by="test-suite")

    proc = _run_gate(tmp_path, [], stdin_text=_creating_push_line("brand-new-feature") + "\n")
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 0, combined
    assert "PASS" in combined


def test_an_alive_name_passes_via_ref_argv_fallback_with_no_graveyard_at_all(tmp_path: Path) -> None:
    proc = _run_gate(tmp_path, ["--ref", "whatever-nobody-has-used"])
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 0, combined
    assert "PASS" in combined
    # honesty contract: zero consulted is still stated, not silent.
    assert "consulted 0 dead branch name" in combined


def test_a_case_scrambled_branch_name_pushed_as_a_create_still_fails(tmp_path: Path) -> None:
    """Regression (I4, graveyard-with-teeth fix-wave, 2026-08-25): mirrors
    test_a_case_scrambled_reintroduction_of_a_dead_path_still_fails's shape
    in test_a_dead_file_does_not_ride_back_in.py, for branch names instead of
    file paths. core.ignorecase=true on this repo (the Windows/NTFS default)
    can treat two differently-cased ref names as the very same loose ref on
    disk. A dead branch name pushed back under a scrambled case is a
    genuine, distinct-string ref creation -- an exact-string dict lookup
    misses it. The FAIL output must name BOTH spellings, not just the
    record's original name."""
    death_id = graveyard.record_death(
        tmp_path, "branch", "old-experiment", "deadsha", reason="superseded by dev", by="test-suite"
    )

    proc = _run_gate(tmp_path, [], stdin_text=_creating_push_line("Old-Experiment") + "\n")
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0, combined
    assert "old-experiment" in combined
    assert "Old-Experiment" in combined
    assert death_id in combined


# ---------------------------------------------------------------------------
# 3. an approved resurrection passes
# ---------------------------------------------------------------------------


def test_an_approved_resurrection_of_a_dead_name_passes(tmp_path: Path) -> None:
    death_id = graveyard.record_death(
        tmp_path, "branch", "old-experiment", "deadsha", reason="superseded by dev", by="test-suite"
    )
    graveyard.record_resurrection_approval(tmp_path, death_id, "bringing it back for a real reason", "test-user")

    proc = _run_gate(tmp_path, [], stdin_text=_creating_push_line("old-experiment") + "\n")
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 0, combined
    assert "PASS" in combined


def test_a_redeath_after_approval_is_refused_again(tmp_path: Path) -> None:
    """Same rule as merge_resurrection_gate.py: an approval only clears the
    death id it names. A branch that dies AGAIN after being approved once
    is dead again -- the newest branch record is what this gate consults."""
    death_id = graveyard.record_death(tmp_path, "branch", "old-experiment", "sha1", reason="first death", by="t")
    graveyard.record_resurrection_approval(tmp_path, death_id, "brought back", "test-user")
    second_death_id = graveyard.record_death(
        tmp_path, "branch", "old-experiment", "sha2", reason="deleted again", by="t"
    )

    proc = _run_gate(tmp_path, [], stdin_text=_creating_push_line("old-experiment") + "\n")
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0, combined
    assert second_death_id in combined


# ---------------------------------------------------------------------------
# 4. only ref CREATION is gated -- an update to an existing ref always passes
# ---------------------------------------------------------------------------


def test_updating_an_existing_remote_ref_is_never_gated_even_for_a_dead_name(tmp_path: Path) -> None:
    graveyard.record_death(tmp_path, "branch", "old-experiment", "deadsha", reason="dead", by="test-suite")

    proc = _run_gate(tmp_path, [], stdin_text=_updating_push_line("old-experiment") + "\n")
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined

    proc_json = _run_gate(tmp_path, ["--json"], stdin_text=_updating_push_line("old-experiment") + "\n")
    assert '"refs_creating_checked": 0' in proc_json.stdout, proc_json.stdout


# ---------------------------------------------------------------------------
# 5. the --ref argv fallback checks a single name without reading stdin
# ---------------------------------------------------------------------------


def test_ref_argv_fallback_ignores_stdin_entirely(tmp_path: Path) -> None:
    graveyard.record_death(tmp_path, "branch", "old-experiment", "deadsha", reason="dead", by="test-suite")

    # stdin carries a DIFFERENT (alive) name; --ref names the dead one. If the
    # gate accidentally parsed stdin too, this would incorrectly pass.
    proc = _run_gate(
        tmp_path,
        ["--ref", "old-experiment"],
        stdin_text=_creating_push_line("some-other-alive-branch") + "\n",
    )
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0, combined
    assert "old-experiment" in combined
