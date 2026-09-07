"""Per-commit scoping, per-commit approval, and landed-history waivers for
`scripts/forge/gates/bulk_commit_guard.py`.

Two defects this module locks down (fixed 2026-08-12):

  1. MIS-SCOPING. The guard's limit is a PER COMMIT limit, but diff-range mode
     diffed only the two ENDPOINTS of base..head and compared that single
     number against it. Over a 597-commit range it reported the two-month
     total (1923 files) as if one commit had done it; the largest real commit
     was 539.

  2. APPROVAL SCOPE. The approval helper scanned EVERY message in the range
     and returned True on the FIRST trailer found anywhere, so one trailer
     approved every oversized commit in the range.

The guard's own regression tests live in tests/test_enforcement_bypass_resistance.py
alongside the other enforcement gates; this module holds the scoping/waiver
coverage so it stays readable.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

bulk_commit_guard = importlib.import_module("forge.gates.bulk_commit_guard")

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
TODAY = date(2026, 8, 12)


def _fake_range(monkeypatch, commits, *, endpoint=None) -> None:
    """Fake an ordered diff range: {sha: (changed_files, commit_message)}."""
    monkeypatch.setattr(bulk_commit_guard, "_range_commits", lambda repo_root, base, head: list(commits))
    monkeypatch.setattr(bulk_commit_guard, "_commit_changed_files", lambda repo_root, sha: list(commits[sha][0]))
    monkeypatch.setattr(bulk_commit_guard, "_commit_message", lambda repo_root, sha: commits[sha][1])
    # The endpoint diff is informational in range mode (it is the OLD metric),
    # except on an empty commit list, where it separates "nothing to measure"
    # from "only merge commits changed files".
    monkeypatch.setattr(
        bulk_commit_guard,
        "_git_lines",
        lambda repo_root, args, *, what="": list(endpoint or []),
    )


def _files(n: int, prefix: str = "f") -> list[str]:
    return [f"thomas/{prefix}{i}.py" for i in range(n)]


def _waiver(sha: str, *, expires: str, guard: str = "thomas-bulk-commit-guard", **overrides) -> dict:
    row = {
        "id": "2026-08-12-landed-history-bulk",
        "commit": sha,
        "guard": guard,
        "approved_by": "core-platform",
        "approved_on": "2026-08-12",
        "expires_on": expires,
        "reason": "Commit already merged before the guard measured per commit; it cannot be given a trailer now.",
    }
    row.update(overrides)
    return row


def _write_waivers(tmp_path: Path, rows) -> Path:
    path = tmp_path / "landed_history_waivers.json"
    path.write_text(json.dumps({"version": 1, "waivers": list(rows)}, indent=2), encoding="utf-8")
    return path


def _run(monkeypatch, capsys, **kwargs):
    rc = bulk_commit_guard.run(Path("."), json_output=True, base="base", head="head", today=TODAY, **kwargs)
    return rc, json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------------------
# (a) An oversized, unapproved SINGLE commit must still FAIL.
# ---------------------------------------------------------------------------


def test_oversized_unapproved_single_commit_still_fails(monkeypatch, capsys) -> None:
    _fake_range(monkeypatch, {SHA_A: (_files(60), "chore: snapshot dump\n")})

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["max_files"] == bulk_commit_guard.DEFAULT_MAX_FILES == 50
    assert payload["commits_scanned"] == 1
    assert payload["max_commit_files"] == 60
    assert [row["sha"] for row in payload["violations"]] == [SHA_A]
    assert payload["violations"][0]["files"] == 60
    assert payload["approved_commits"] == []
    assert payload["waived_commits"] == []


def test_oversized_single_commit_fails_in_text_mode(monkeypatch, capsys) -> None:
    _fake_range(monkeypatch, {SHA_A: (_files(539), "chore: the big one\n")})

    rc = bulk_commit_guard.run(Path("."), base="base", head="head", today=TODAY)
    out = capsys.readouterr().out

    assert rc == 1
    assert "FAIL" in out
    assert "539 file(s)" in out
    assert SHA_A[:12] in out


def test_commit_exactly_at_the_limit_passes(monkeypatch, capsys) -> None:
    _fake_range(monkeypatch, {SHA_A: (_files(50), "chore: right at the line\n")})

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["max_commit_files"] == 50
    assert payload["violations"] == []


# ---------------------------------------------------------------------------
# MIS-SCOPING: the metric is per commit, not the range total.
# ---------------------------------------------------------------------------


def test_range_total_is_not_the_metric(monkeypatch, capsys) -> None:
    # 3 x 20 distinct files = 60 across the range, but no single commit is
    # over 50. The old endpoint diff reported 60 and failed the whole range.
    commits = {
        SHA_A: (_files(20, "a"), "feat: part one\n"),
        SHA_B: (_files(20, "b"), "feat: part two\n"),
        SHA_C: (_files(20, "c"), "feat: part three\n"),
    }
    _fake_range(monkeypatch, commits, endpoint=_files(20, "a") + _files(20, "b") + _files(20, "c"))

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["commits_scanned"] == 3
    assert payload["max_commit_files"] == 20
    assert payload["endpoint_changed_files"] == 60  # the old, wrong metric, informational only
    assert payload["violations"] == []


def test_one_oversized_commit_among_small_ones_is_caught(monkeypatch, capsys) -> None:
    commits = {
        SHA_A: (_files(3, "a"), "chore: small\n"),
        SHA_B: (_files(200, "b"), "chore: dump\n"),
        SHA_C: (_files(3, "c"), "chore: small again\n"),
    }
    _fake_range(monkeypatch, commits)

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert [row["sha"] for row in payload["violations"]] == [SHA_B]
    assert payload["violations"][0]["files"] == 200
    assert payload["max_commit_files"] == 200


def test_every_oversized_commit_is_reported(monkeypatch, capsys) -> None:
    commits = {f"{i}" * 40: (_files(60, f"x{i}"), f"chore: dump {i}\n") for i in range(4)}
    _fake_range(monkeypatch, commits)

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 1
    assert len(payload["violations"]) == 4
    assert {row["sha"] for row in payload["violations"]} == set(commits)


# ---------------------------------------------------------------------------
# (b) A trailer approves ONLY the commit whose own message carries it.
# ---------------------------------------------------------------------------


def test_trailer_in_commit_a_does_not_approve_commit_b(monkeypatch, capsys) -> None:
    commits = {
        SHA_A: (_files(60, "a"), "chore: approved migration\n\nThomas-Bulk-Change-Approved: reviewed by Calvin\n"),
        SHA_B: (_files(60, "b"), "chore: unrelated dump\n"),
    }
    _fake_range(monkeypatch, commits)

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 1
    assert payload["ok"] is False
    # A carried the trailer and is cleared; B never did and is still a violation.
    assert [row["sha"] for row in payload["approved_commits"]] == [SHA_A]
    assert [row["sha"] for row in payload["violations"]] == [SHA_B]
    # The legacy "this range was approved" flag must not be set while B stands.
    assert payload["approved_bulk_change"] is False


def test_one_trailer_does_not_approve_a_whole_range(monkeypatch, capsys) -> None:
    # The regression that let one trailer approve 1923 files across 597 commits.
    commits = {SHA_A: (_files(60, "a"), "chore: approved\n\nThomas-Bulk-Change-Approved: reviewed\n")}
    for i in range(5):
        commits[f"{i}" * 40] = (_files(60, f"x{i}"), f"chore: dump {i}\n")
    _fake_range(monkeypatch, commits)

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 1
    assert len(payload["violations"]) == 5
    assert SHA_A not in {row["sha"] for row in payload["violations"]}


def test_trailer_on_a_small_commit_does_not_cover_a_later_big_one(monkeypatch, capsys) -> None:
    commits = {
        SHA_A: (_files(2, "a"), "chore: tiny\n\nThomas-Bulk-Change-Approved: signed off\n"),
        SHA_B: (_files(400, "b"), "chore: the dump that followed\n"),
    }
    _fake_range(monkeypatch, commits)

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 1
    assert [row["sha"] for row in payload["violations"]] == [SHA_B]
    assert payload["approved_commits"] == []  # A was never oversized, so nothing to approve


def test_bulk_approval_rejects_a_list_of_messages() -> None:
    # The old helper took the whole range's messages. Passing a list must be a
    # loud error, never a silent range-wide approval.
    with pytest.raises(TypeError):
        bulk_commit_guard._bulk_approval(["Thomas-Bulk-Change-Approved: anywhere in the range"])


def test_bulk_approval_reads_only_the_message_it_is_given() -> None:
    approved, trailer, reason = bulk_commit_guard._bulk_approval(
        "chore: x\n\nThomas-Bulk-Change-Approved: migration reviewed\n"
    )
    assert (approved, trailer, reason) == (True, "thomas-bulk-change-approved", "migration reviewed")
    assert bulk_commit_guard._bulk_approval("chore: x\n") == (False, "", "")
    # An empty reason is not an approval.
    assert bulk_commit_guard._bulk_approval("chore: x\n\nThomas-Bulk-Change-Approved:\n") == (False, "", "")


# ---------------------------------------------------------------------------
# (c)/(d) Landed-history waivers.
# ---------------------------------------------------------------------------


def test_valid_waiver_passes_and_is_reported(monkeypatch, capsys, tmp_path) -> None:
    _fake_range(monkeypatch, {SHA_A: (_files(539), "chore: the big landed commit\n")})
    waivers = _write_waivers(tmp_path, [_waiver(SHA_A, expires="2026-12-31")])

    rc, payload = _run(monkeypatch, capsys, waivers_path=waivers)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["violations"] == []
    assert [row["sha"] for row in payload["waived_commits"]] == [SHA_A]
    waived = payload["waived_commits"][0]
    assert waived["waiver_id"] == "2026-08-12-landed-history-bulk"
    assert waived["waiver_approved_by"] == "core-platform"
    assert waived["waiver_expires_on"] == "2026-12-31"
    assert waived["files"] == 539


def test_waived_pass_does_not_look_clean_in_text_output(monkeypatch, capsys, tmp_path) -> None:
    _fake_range(monkeypatch, {SHA_A: (_files(539), "chore: the big landed commit\n")})
    waivers = _write_waivers(tmp_path, [_waiver(SHA_A, expires="2026-12-31")])

    rc = bulk_commit_guard.run(Path("."), base="base", head="head", waivers_path=waivers, today=TODAY)
    out = capsys.readouterr().out

    assert rc == 0
    assert "WAIVED" in out
    assert "PASS WITH EXCEPTIONS" in out
    assert "2026-08-12-landed-history-bulk" in out
    assert SHA_A[:12] in out


def test_expired_waiver_does_not_pass(monkeypatch, capsys, tmp_path) -> None:
    _fake_range(monkeypatch, {SHA_A: (_files(539), "chore: the big landed commit\n")})
    waivers = _write_waivers(tmp_path, [_waiver(SHA_A, expires="2026-07-01")])

    rc, payload = _run(monkeypatch, capsys, waivers_path=waivers)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["waived_commits"] == []
    assert [row["sha"] for row in payload["violations"]] == [SHA_A]


def test_waiver_expiring_today_is_expired(monkeypatch, capsys, tmp_path) -> None:
    _fake_range(monkeypatch, {SHA_A: (_files(60), "chore: dump\n")})
    waivers = _write_waivers(tmp_path, [_waiver(SHA_A, expires=TODAY.isoformat())])

    rc, payload = _run(monkeypatch, capsys, waivers_path=waivers)

    assert rc == 1
    assert payload["waived_commits"] == []


def test_waiver_binds_to_one_exact_commit_one_guard_and_needs_every_field(monkeypatch, capsys, tmp_path) -> None:
    future = (TODAY + timedelta(days=90)).isoformat()
    rows = [
        _waiver(SHA_B, expires=future),  # a different commit
        _waiver("*", expires=future),  # no wildcard form
        _waiver("all", expires=future),
        _waiver(SHA_A[:12], expires=future),  # no prefix form
        _waiver(SHA_A.upper(), expires=future, commit=SHA_A[:39] + "*"),  # no glob suffix
        _waiver(SHA_A, expires=future, guard="thomas-commit-growth-guard"),  # another guard
        _waiver(SHA_A, expires=future, guard=""),
        _waiver(SHA_A, expires=future, approved_by=""),  # missing fields
        _waiver(SHA_A, expires=future, reason=""),
        _waiver(SHA_A, expires=future, id=""),
        _waiver(SHA_A, expires=""),  # missing/invalid dates
        _waiver(SHA_A, expires="not-a-date"),
        _waiver(SHA_A, expires=future, approved_on="not-a-date"),
    ]
    _fake_range(monkeypatch, {SHA_A: (_files(60), "chore: dump\n")})
    waivers = _write_waivers(tmp_path, rows)

    rc, payload = _run(monkeypatch, capsys, waivers_path=waivers)

    assert rc == 1
    assert payload["waived_commits"] == []
    assert [row["sha"] for row in payload["violations"]] == [SHA_A]

    # ...and the one well-formed entry for this commit does apply.
    assert bulk_commit_guard.waiver_for_commit([_waiver(SHA_A, expires=future)], sha=SHA_A, today=TODAY) is not None


def test_waiver_for_commit_rejects_non_sha_targets() -> None:
    future = (TODAY + timedelta(days=90)).isoformat()
    rows = [_waiver(SHA_A, expires=future)]
    assert bulk_commit_guard.waiver_for_commit(rows, sha="*", today=TODAY) is None
    assert bulk_commit_guard.waiver_for_commit(rows, sha=SHA_A[:7], today=TODAY) is None
    assert bulk_commit_guard.waiver_for_commit(rows, sha="", today=TODAY) is None
    assert bulk_commit_guard.waiver_for_commit(rows, sha=SHA_A, guard="other-guard", today=TODAY) is None


def test_waivers_do_not_apply_to_local_staged_mode(monkeypatch, capsys, tmp_path) -> None:
    future = (TODAY + timedelta(days=90)).isoformat()
    _write_waivers(tmp_path, [_waiver(SHA_A, expires=future)])
    monkeypatch.setattr(
        bulk_commit_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: _files(60),
    )

    rc = bulk_commit_guard.run(Path("."), max_files=50, json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["staged_count"] == 60


def test_unreadable_waiver_registry_fails_closed(monkeypatch, capsys, tmp_path) -> None:
    _fake_range(monkeypatch, {SHA_A: (_files(60), "chore: dump\n")})
    bad = tmp_path / "landed_history_waivers.json"
    bad.write_text("{not json", encoding="utf-8")

    rc, payload = _run(monkeypatch, capsys, waivers_path=bad)

    assert rc == 1
    assert payload["ok"] is False
    assert "waiver registry" in payload["error"]


def test_missing_waiver_registry_is_not_an_approval(monkeypatch, capsys, tmp_path) -> None:
    _fake_range(monkeypatch, {SHA_A: (_files(60), "chore: dump\n")})

    rc, payload = _run(monkeypatch, capsys, waivers_path=tmp_path / "does-not-exist.json")

    assert rc == 1
    assert payload["violations"][0]["sha"] == SHA_A


def test_shipped_waiver_registry_is_well_formed() -> None:
    path = Path(__file__).resolve().parent.parent / "docs" / "ops" / "landed_history_waivers.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["version"] == 1
    assert isinstance(doc["waivers"], list)
    for row in doc["waivers"]:
        for field in bulk_commit_guard.WAIVER_REQUIRED_FIELDS:
            assert str(row.get(field) or "").strip(), f"waiver {row.get('id')} is missing {field}"
        assert bulk_commit_guard._FULL_SHA_RE.match(str(row["commit"]).lower()), "waiver commit must be a full sha"


# ---------------------------------------------------------------------------
# Empty range, merge-only range, unmeasurable range.
# ---------------------------------------------------------------------------


def test_empty_range_is_explicit_and_does_not_crash(monkeypatch, capsys) -> None:
    """base == head: no max() over an empty sequence, and no silent pass."""
    monkeypatch.setattr(bulk_commit_guard, "_git_lines", lambda repo_root, args, *, what="": [])

    rc = bulk_commit_guard.run(Path("."), json_output=True, base="same", head="same", today=TODAY)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["no_commits"] is True
    assert payload["commits_scanned"] == 0
    assert payload["max_commit_files"] == 0
    assert payload["endpoint_changed_files"] == 0


def test_empty_range_text_output_says_no_commits(monkeypatch, capsys) -> None:
    monkeypatch.setattr(bulk_commit_guard, "_git_lines", lambda repo_root, args, *, what="": [])

    rc = bulk_commit_guard.run(Path("."), base="same", head="same", today=TODAY)
    out = capsys.readouterr().out

    assert rc == 0
    assert "no non-merge commits" in out


def test_merge_only_range_fails_closed(monkeypatch, capsys) -> None:
    """--no-merges cannot attribute a merge commit's own edits, so don't pass."""
    _fake_range(monkeypatch, {}, endpoint=_files(80))

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["no_commits"] is True
    assert "only merge commits" in payload["error"]


def test_unresolvable_range_fails_closed(monkeypatch, capsys) -> None:
    def _boom(repo_root, base, head):
        raise bulk_commit_guard.GitRangeError("unknown revision")

    monkeypatch.setattr(bulk_commit_guard, "_range_commits", _boom)

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert "range could not be resolved" in payload["error"]


def test_unmeasurable_commit_fails_closed(monkeypatch, capsys) -> None:
    monkeypatch.setattr(bulk_commit_guard, "_range_commits", lambda repo_root, base, head: [SHA_A])
    monkeypatch.setattr(bulk_commit_guard, "_git_lines", lambda repo_root, args, *, what="": [])

    def _boom(repo_root, sha):
        raise bulk_commit_guard.GitRangeError("bad object")

    monkeypatch.setattr(bulk_commit_guard, "_commit_changed_files", _boom)

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert "could not be measured" in payload["error"]


def test_unreadable_commit_message_fails_closed(monkeypatch, capsys) -> None:
    monkeypatch.setattr(bulk_commit_guard, "_range_commits", lambda repo_root, base, head: [SHA_A])
    monkeypatch.setattr(bulk_commit_guard, "_git_lines", lambda repo_root, args, *, what="": [])
    monkeypatch.setattr(bulk_commit_guard, "_commit_changed_files", lambda repo_root, sha: _files(60))

    def _boom(repo_root, sha):
        raise bulk_commit_guard.GitRangeError("bad object")

    monkeypatch.setattr(bulk_commit_guard, "_commit_message", _boom)

    rc, payload = _run(monkeypatch, capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert "message could not be read" in payload["error"]


# ---------------------------------------------------------------------------
# Real git: the per-commit measurement against an actual repository.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture()
def tiny_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "guard@test")
    _git(repo, "config", "user.name", "guard test")
    return repo


def _commit_files(repo: Path, names: list[str], message: str) -> str:
    import subprocess

    for name in names:
        (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_real_repo_measures_per_commit_not_the_range_total(tiny_repo: Path, capsys) -> None:
    base = _commit_files(tiny_repo, ["seed.txt"], "chore: seed")
    _commit_files(tiny_repo, [f"a{i}.txt" for i in range(4)], "feat: four")
    _commit_files(tiny_repo, [f"b{i}.txt" for i in range(4)], "feat: four more")
    head = _commit_files(tiny_repo, [f"c{i}.txt" for i in range(4)], "feat: four again")

    # 12 files across the range, 4 per commit. Limit 5: per-commit PASSES,
    # while the old endpoint-total metric (12) would have failed.
    rc = bulk_commit_guard.run(tiny_repo, max_files=5, json_output=True, base=base, head=head, today=TODAY)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["commits_scanned"] == 3
    assert payload["max_commit_files"] == 4
    assert payload["endpoint_changed_files"] == 12

    # Limit 3: every commit is over, and all three are reported.
    rc = bulk_commit_guard.run(tiny_repo, max_files=3, json_output=True, base=base, head=head, today=TODAY)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert len(payload["violations"]) == 3


def test_real_repo_trailer_only_covers_its_own_commit(tiny_repo: Path, capsys) -> None:
    base = _commit_files(tiny_repo, ["seed.txt"], "chore: seed")
    _commit_files(
        tiny_repo,
        [f"a{i}.txt" for i in range(4)],
        "feat: approved\n\nThomas-Bulk-Change-Approved: reviewed by Calvin",
    )
    head = _commit_files(tiny_repo, [f"b{i}.txt" for i in range(4)], "feat: not approved")

    rc = bulk_commit_guard.run(tiny_repo, max_files=3, json_output=True, base=base, head=head, today=TODAY)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert len(payload["approved_commits"]) == 1
    assert len(payload["violations"]) == 1
    assert payload["violations"][0]["subject"] == "feat: not approved"


def test_real_repo_waiver_needs_the_exact_sha(tiny_repo: Path, capsys, tmp_path) -> None:
    base = _commit_files(tiny_repo, ["seed.txt"], "chore: seed")
    head = _commit_files(tiny_repo, [f"a{i}.txt" for i in range(4)], "feat: landed too big")
    future = (TODAY + timedelta(days=90)).isoformat()

    waivers = _write_waivers(tmp_path, [_waiver(head, expires=future)])
    rc = bulk_commit_guard.run(
        tiny_repo, max_files=3, json_output=True, base=base, head=head, waivers_path=waivers, today=TODAY
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert [row["sha"] for row in payload["waived_commits"]] == [head]

    # The same waiver text with a one-character-different sha waives nothing.
    wrong = ("0" if head[0] != "0" else "1") + head[1:]
    waivers = _write_waivers(tmp_path, [_waiver(wrong, expires=future)])
    rc = bulk_commit_guard.run(
        tiny_repo, max_files=3, json_output=True, base=base, head=head, waivers_path=waivers, today=TODAY
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["waived_commits"] == []


def test_real_repo_root_commit_is_measured(tiny_repo: Path, capsys) -> None:
    """`<sha>^` does not resolve for a root commit; it must not read as 0 files."""
    root = _commit_files(tiny_repo, [f"r{i}.txt" for i in range(6)], "chore: root")

    assert len(bulk_commit_guard._commit_changed_files(tiny_repo, root)) == 6
