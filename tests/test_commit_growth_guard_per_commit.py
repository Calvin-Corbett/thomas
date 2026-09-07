"""commit_growth_guard: per-commit scoping, per-commit approval, and waivers.

Two defects these tests pin shut (both were real; both were reproduced against
the pre-fix code on a live throwaway repository before this file was written):

  (1) MIS-SCOPING. Diff-range mode diffed only the two ENDPOINTS of base..head
      and compared that total against a per-COMMIT cap. Over a 597-commit range
      it reported the two-month aggregate as though one commit did it (1923
      files; the largest real commit touched 539).

  (2) APPROVAL-SCOPE HOLE. `_growth_approval` was handed every message in the
      range and returned True on the FIRST trailer found anywhere, so one
      trailer approved every other commit's violations.

The guard now walks `git rev-list --reverse --no-merges base..head` and
measures each commit against its own parent, and a trailer approves only the
commit whose own message carries it.  Landed history that can no longer be
re-trailered goes through docs/ops/landed_history_waivers.json instead.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

commit_growth_guard = importlib.import_module("forge.gates.commit_growth_guard")

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
PARENT_A = "1" * 40
PARENT_B = "2" * 40
PARENT_C = "3" * 40
MERGE_SHA = "d" * 40
TODAY = date(2026, 8, 12)


def _wire_range(monkeypatch, spec, *, merges=(), waivers=None) -> None:
    """Wire the guard's diff-range seams to a fake commit walk.

    `spec` is an ordered list (oldest commit first) of:
        {"sha", "parent", "files": {rel: (parent_lines, commit_lines)}, "message"}
    so each commit is measured against ITS OWN parent, exactly as the real
    `git diff <sha>^ <sha>` path does.
    """
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.delenv("THOMAS_COMMIT_GROWTH_GUARD_DISABLE", raising=False)

    shas = [row["sha"] for row in spec]
    by_sha = {row["sha"]: row for row in spec}

    monkeypatch.setattr(commit_growth_guard, "_range_commits", lambda repo_root, base, head: list(shas))
    monkeypatch.setattr(
        commit_growth_guard,
        "_range_all_commits",
        lambda repo_root, base, head: list(shas) + list(merges),
    )
    monkeypatch.setattr(commit_growth_guard, "_commit_parent", lambda repo_root, sha: by_sha[sha]["parent"])
    monkeypatch.setattr(
        commit_growth_guard,
        "_changed_files",
        lambda repo_root, *, base=None, head=None: list(by_sha[head]["files"]),
    )

    line_counts: dict[tuple[str, str], int] = {}
    for row in spec:
        for rel, (prior, current) in row["files"].items():
            line_counts[(row["parent"], rel)] = prior
            line_counts[(row["sha"], rel)] = current

    monkeypatch.setattr(
        commit_growth_guard,
        "_rev_lines",
        lambda repo_root, rev, rel: line_counts.get((rev, rel), 0),
    )
    monkeypatch.setattr(commit_growth_guard, "_commit_message", lambda repo_root, sha: by_sha[sha]["message"])
    monkeypatch.setattr(commit_growth_guard, "_load_waivers", lambda repo_root: list(waivers or []))


def _waiver(sha: str, **overrides) -> dict:
    row = {
        "id": "2026-08-12-landed-history-growth",
        "commit": sha,
        "guard": "commit-growth-guard",
        "approved_by": "core-platform",
        "approved_on": "2026-08-12",
        "expires_on": "2026-11-12",
        "reason": "Already-landed history predating per-commit scoping; cannot be re-trailered.",
    }
    row.update(overrides)
    return row


def _oversized(sha: str, parent: str, *, message: str, path: str = "thomas/landed.py") -> dict:
    return {"sha": sha, "parent": parent, "files": {path: (10, 900)}, "message": message}


def _run(**kwargs):
    defaults = {"max_growth": 300, "json_output": True, "base": "base", "head": "head"}
    defaults.update(kwargs)
    return commit_growth_guard.run(Path("."), **defaults)


# ---------------------------------------------------------------------------
# (a) an oversized, unapproved SINGLE commit still FAILS
# ---------------------------------------------------------------------------


def test_oversized_unapproved_single_commit_fails(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        [
            {
                "sha": SHA_A,
                "parent": PARENT_A,
                "files": {"thomas/new.py": (0, 400)},
                "message": "feat: dump a file in one shot",
            }
        ],
    )

    rc = _run()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["violations"][0]["path"] == "thomas/new.py"
    assert payload["violations"][0]["commit"] == SHA_A
    assert payload["violations"][0]["growth"] == 400
    assert payload["approved_growth"] is False
    assert payload["unapproved_commits"] == [SHA_A]


def test_oversized_commit_buried_in_a_long_range_still_fails(monkeypatch, capsys) -> None:
    # The guard must find the one bad commit and attribute the growth to THAT
    # commit rather than to the range as a whole.
    _wire_range(
        monkeypatch,
        [
            {"sha": SHA_A, "parent": PARENT_A, "files": {"thomas/a.py": (100, 150)}, "message": "chore: small"},
            {"sha": SHA_B, "parent": PARENT_B, "files": {"thomas/b.py": (10, 900)}, "message": "feat: dump"},
            {"sha": SHA_C, "parent": PARENT_C, "files": {"thomas/c.py": (5, 20)}, "message": "chore: small"},
        ],
    )

    rc = _run()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["commits_scanned"] == 3
    assert payload["unapproved_commits"] == [SHA_B]
    assert len(payload["violations"]) == 1
    assert payload["violations"][0]["commit"] == SHA_B
    assert payload["violations"][0]["path"] == "thomas/b.py"
    assert payload["violations"][0]["growth"] == 890


def test_metric_is_per_commit_not_the_range_endpoints(monkeypatch, capsys) -> None:
    # thomas/wide.py goes 0 -> 200 in A and 200 -> 400 in B. The ENDPOINT diff
    # is +400 (over the 300 cap); neither COMMIT is. The cap is per commit.
    _wire_range(
        monkeypatch,
        [
            {"sha": SHA_A, "parent": PARENT_A, "files": {"thomas/wide.py": (0, 200)}, "message": "feat: part 1"},
            {"sha": SHA_B, "parent": PARENT_B, "files": {"thomas/wide.py": (200, 400)}, "message": "feat: part 2"},
        ],
    )

    rc = _run()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["violations"] == []
    assert payload["commits_scanned"] == 2


# ---------------------------------------------------------------------------
# (b) a trailer approves ONLY its own commit
# ---------------------------------------------------------------------------


def test_own_trailer_approves_its_own_commit(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        [
            {
                "sha": SHA_A,
                "parent": PARENT_A,
                "files": {"thomas/large.py": (10, 400)},
                "message": "fix: takeover\n\nThomas-Commit-Growth-Approved: Calvin-approved safety-arc replay\n",
            }
        ],
    )

    rc = _run()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["approved_growth"] is True
    assert "Calvin-approved" in payload["approval_reason"]


def test_trailer_in_commit_a_does_not_approve_commit_b(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        [
            {
                "sha": SHA_A,
                "parent": PARENT_A,
                "files": {"thomas/a.py": (10, 400)},
                "message": "feat: slice A\n\nThomas-Commit-Growth-Approved: Calvin-approved slice A only\n",
            },
            {
                "sha": SHA_B,
                "parent": PARENT_B,
                "files": {"thomas/b.py": (10, 900)},
                "message": "feat: slice B with no approval of its own",
            },
        ],
    )

    rc = _run()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["approved_growth"] is False
    assert [row["commit"] for row in payload["approved_commits"]] == [SHA_A]
    assert payload["unapproved_commits"] == [SHA_B]
    assert any(v["commit"] == SHA_B and v["path"] == "thomas/b.py" for v in payload["violations"])


def test_trailer_in_a_later_commit_does_not_reach_backwards(monkeypatch, capsys) -> None:
    # Order matters too: the approved commit coming last must not retroactively
    # cover the earlier violation.
    _wire_range(
        monkeypatch,
        [
            _oversized(SHA_A, PARENT_A, message="feat: unapproved dump", path="thomas/a.py"),
            {
                "sha": SHA_B,
                "parent": PARENT_B,
                "files": {"thomas/b.py": (10, 900)},
                "message": "feat: later\n\nThomas-Commit-Growth-Approved: approved for the OTHER file\n",
            },
        ],
    )

    rc = _run()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["unapproved_commits"] == [SHA_A]


# ---------------------------------------------------------------------------
# (c) / (d) landed-history waivers
# ---------------------------------------------------------------------------


def test_valid_waiver_passes_and_is_reported(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        [_oversized(SHA_B, PARENT_B, message="feat: landed before per-commit scoping existed")],
        waivers=[_waiver(SHA_B, expires_on="2026-11-12")],
    )

    rc = _run(today=TODAY)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["waived_growth"] is True
    # A waived pass is neither an approved pass nor a clean pass: the violation
    # is still carried in the payload.
    assert payload["approved_growth"] is False
    assert len(payload["violations"]) == 1
    assert payload["waived_commits"][0]["commit"] == SHA_B
    assert payload["waived_commits"][0]["waiver_id"] == "2026-08-12-landed-history-growth"
    assert payload["waived_commits"][0]["expires_on"] == "2026-11-12"
    assert payload["waived_commits"][0]["approved_by"] == "core-platform"


def test_waived_pass_does_not_read_as_a_clean_pass(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        [_oversized(SHA_B, PARENT_B, message="feat: landed before per-commit scoping existed")],
        waivers=[_waiver(SHA_B)],
    )

    rc = _run(json_output=False, today=TODAY)
    out = capsys.readouterr().out

    assert rc == 0
    assert "WAIVED" in out
    assert "2026-08-12-landed-history-growth" in out
    assert "no file grew by more than" not in out


def test_expired_waiver_does_not_pass(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        [_oversized(SHA_B, PARENT_B, message="feat: landed before per-commit scoping existed")],
        waivers=[_waiver(SHA_B, expires_on="2026-08-11")],
    )

    rc = _run(today=TODAY)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["waived_growth"] is False
    assert payload["waived_commits"] == []
    assert payload["unapproved_commits"] == [SHA_B]


def test_waiver_expiring_today_does_not_pass(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        [_oversized(SHA_B, PARENT_B, message="feat: landed history")],
        waivers=[_waiver(SHA_B, expires_on=TODAY.isoformat())],
    )

    rc = _run(today=TODAY)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False


def test_waiver_for_another_commit_does_not_pass(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        [_oversized(SHA_B, PARENT_B, message="feat: landed history")],
        waivers=[_waiver(SHA_A)],
    )

    rc = _run(today=TODAY)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["waived_commits"] == []


def test_waiver_covers_only_the_listed_commit() -> None:
    waiver = _waiver(SHA_A)
    assert commit_growth_guard._waiver_for_commit([waiver], SHA_A, today=TODAY) is not None
    assert commit_growth_guard._waiver_for_commit([waiver], SHA_B, today=TODAY) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"guard": "bulk-commit-guard"},  # another guard's waiver must not apply
        {"guard": "protected-files-gate"},
        {"guard": "*"},  # no wildcard guard form
        {"guard": "all"},  # no "all" guard form
        {"commit": SHA_A[:12]},  # no prefix matching
        {"commit": SHA_A[:7]},
        {"commit": "*"},  # no wildcard commit form
        {"commit": "all"},  # no "all" commit form
        {"id": ""},  # every required field must be present
        {"approved_by": ""},
        {"approved_on": ""},
        {"reason": ""},
        {"expires_on": ""},
        {"expires_on": "not-a-date"},
        {"expires_on": "2020-01-01"},  # expired
    ],
)
def test_waiver_must_be_exact_and_live(overrides) -> None:
    waiver = _waiver(SHA_A, **overrides)
    assert commit_growth_guard._waiver_for_commit([waiver], SHA_A, today=TODAY) is None


def test_waiver_lookup_rejects_a_non_sha_target() -> None:
    # Defence in depth: even if a caller hands in an abbreviated sha, no waiver
    # may match it.
    assert commit_growth_guard._waiver_for_commit([_waiver(SHA_A)], SHA_A[:12], today=TODAY) is None
    assert commit_growth_guard._waiver_for_commit([_waiver(SHA_A)], "", today=TODAY) is None


def test_load_waivers_reads_the_docs_ops_registry(tmp_path) -> None:
    ops = tmp_path / "docs" / "ops"
    ops.mkdir(parents=True)
    (ops / "landed_history_waivers.json").write_text(
        json.dumps({"version": 1, "waivers": [_waiver(SHA_A)]}),
        encoding="utf-8",
    )

    rows = commit_growth_guard._load_waivers(tmp_path)
    assert len(rows) == 1
    assert rows[0]["commit"] == SHA_A

    # A missing registry yields no waivers -- the fail-closed direction, since
    # fewer waivers can only make the guard stricter.
    assert commit_growth_guard._load_waivers(tmp_path / "does-not-exist") == []


def test_malformed_waiver_registry_cannot_grant_a_waiver(tmp_path) -> None:
    ops = tmp_path / "docs" / "ops"
    ops.mkdir(parents=True)
    registry = ops / "landed_history_waivers.json"

    for bad in ("{not json", "[]", '{"version": 1}', '{"version": 1, "waivers": {}}'):
        registry.write_text(bad, encoding="utf-8")
        assert commit_growth_guard._load_waivers(tmp_path) == [], bad


def test_landed_history_waiver_registry_is_wellformed() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    path = repo_root / commit_growth_guard.WAIVERS_REL_PATH
    assert path.exists(), f"{commit_growth_guard.WAIVERS_REL_PATH} must exist"

    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc.get("version") == 1
    assert isinstance(doc.get("waivers"), list)
    for row in doc["waivers"]:
        for field in commit_growth_guard.WAIVER_REQUIRED_FIELDS:
            assert str(row.get(field) or "").strip(), f"waiver {row.get('id')!r} is missing {field}"
        # Full 40-hex SHAs only: a prefix or wildcard entry must never sit in
        # the registry looking legitimate.
        assert commit_growth_guard._FULL_SHA_RE.match(str(row["commit"]).strip().lower()), (
            f"waiver {row.get('id')!r} does not name one exact 40-hex commit"
        )
        date.fromisoformat(str(row["expires_on"]).strip())


# ---------------------------------------------------------------------------
# empty range, merge commits, and the preserved staged mode
# ---------------------------------------------------------------------------


def test_empty_range_is_explicit_not_a_silent_pass(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(commit_growth_guard, "_range_commits", lambda repo_root, base, head: [])
    monkeypatch.setattr(commit_growth_guard, "_range_all_commits", lambda repo_root, base, head: [])

    rc = _run(base="same", head="same")
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["reason"] == "no_commits_in_range"
    assert payload["commits_scanned"] == 0
    assert payload["commits_in_range"] == 0
    assert payload["violations"] == []

    rc = _run(json_output=False, base="same", head="same")
    out = capsys.readouterr().out
    assert rc == 0
    assert "NO COMMITS IN RANGE" in out
    assert "no file grew by more than" not in out


def test_real_empty_range_does_not_raise(tmp_path) -> None:
    # The real git seam, not a monkeypatched one: base == head yields an empty
    # commit list instead of an aggregate over nothing.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert commit_growth_guard._rev_list(tmp_path, "HEAD", "HEAD", no_merges=True) == []
    assert commit_growth_guard._rev_list(tmp_path, "HEAD", "HEAD", no_merges=False) == []


def test_merges_only_range_fails_closed(monkeypatch, capsys) -> None:
    # --no-merges leaves nothing measurable, so this must not report a clean pass.
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(commit_growth_guard, "_range_commits", lambda repo_root, base, head: [])
    monkeypatch.setattr(commit_growth_guard, "_range_all_commits", lambda repo_root, base, head: [MERGE_SHA])

    rc = _run()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["reason"] == "merge_commits_only"
    assert payload["commits_scanned"] == 0
    assert payload["merge_commits_skipped"] == [MERGE_SHA]


def test_skipped_merge_commits_are_reported(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        [{"sha": SHA_A, "parent": PARENT_A, "files": {"thomas/a.py": (100, 150)}, "message": "chore: small"}],
        merges=[MERGE_SHA],
    )

    rc = _run()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["commits_scanned"] == 1
    assert payload["commits_in_range"] == 2
    assert payload["merge_commits_skipped"] == [MERGE_SHA]


def test_git_failure_fails_closed_rather_than_reading_as_empty(monkeypatch, capsys) -> None:
    def _boom(repo_root, base, head):
        raise RuntimeError("fatal: bad revision")

    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(commit_growth_guard, "_range_all_commits", _boom)
    monkeypatch.setattr(commit_growth_guard, "_range_commits", _boom)

    rc = _run()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "bad revision" in payload["error"]


def test_staged_mode_is_unchanged(monkeypatch, capsys) -> None:
    # Local/staged mode must keep working exactly as before: working tree vs
    # HEAD, no trailer self-approval, no waiver path.
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(commit_growth_guard, "_staged_files", lambda repo_root: ["thomas/big.py"])
    monkeypatch.setattr(commit_growth_guard, "_working_tree_lines", lambda repo_root, rel: 500)
    monkeypatch.setattr(commit_growth_guard, "_head_lines", lambda repo_root, rel: 100)

    rc = commit_growth_guard.run(Path("."), max_growth=300, json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["mode"] == "staged"
    assert payload["staged_count"] == 1
    assert payload["violations"][0]["growth"] == 400
    assert payload["approved_growth"] is False


def test_staged_mode_ignores_landed_history_waivers(monkeypatch, capsys) -> None:
    # Waivers cover history that already landed. A local commit can still be
    # split or trailered, so a waiver must not help it.
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(commit_growth_guard, "_staged_files", lambda repo_root: ["thomas/big.py"])
    monkeypatch.setattr(commit_growth_guard, "_working_tree_lines", lambda repo_root, rel: 900)
    monkeypatch.setattr(commit_growth_guard, "_head_lines", lambda repo_root, rel: 10)
    monkeypatch.setattr(commit_growth_guard, "_load_waivers", lambda repo_root: [_waiver(SHA_A)])

    rc = commit_growth_guard.run(Path("."), max_growth=300, json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False


def test_staged_mode_passes_a_small_change(monkeypatch, capsys) -> None:
    monkeypatch.setattr(commit_growth_guard, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(commit_growth_guard, "_staged_files", lambda repo_root: ["thomas/small.py"])
    monkeypatch.setattr(commit_growth_guard, "_working_tree_lines", lambda repo_root, rel: 120)
    monkeypatch.setattr(commit_growth_guard, "_head_lines", lambda repo_root, rel: 100)

    rc = commit_growth_guard.run(Path("."), max_growth=300, json_output=True)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["violations"] == []


def test_unmonitored_and_skipped_paths_are_ignored(monkeypatch, capsys) -> None:
    _wire_range(
        monkeypatch,
        [
            {
                "sha": SHA_A,
                "parent": PARENT_A,
                "files": {
                    "docs/huge.md": (0, 5000),
                    "node_modules/pkg/index.js": (0, 5000),
                    "thomas/ok.py": (0, 10),
                },
                "message": "chore: docs and vendored code",
            }
        ],
    )

    rc = _run()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["violations"] == []
    assert payload["files_scanned"] == 1


# ---------------------------------------------------------------------------
# real git: the seams above are all monkeypatched, so this exercises the actual
# rev-list / diff / rev-parse / log invocations end to end.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"
    return proc.stdout.strip()


def _write(repo: Path, rel: str, n: int) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text("\n".join(f"line {i}" for i in range(n)) + "\n", encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--no-verify", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def real_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "checkout", "-q", "-b", "main")
    return repo


def test_real_git_catches_the_unapproved_commit_and_scopes_the_trailer(real_repo, capsys) -> None:
    _write(real_repo, "thomas/a.py", 10)
    c0 = _commit(real_repo, "chore: seed")

    _write(real_repo, "thomas/a.py", 510)
    c1 = _commit(real_repo, "feat: dump 500 lines with no approval")

    _write(real_repo, "thomas/b.py", 500)
    c2 = _commit(
        real_repo,
        "feat: big but approved\n\nThomas-Commit-Growth-Approved: Calvin approved slice B\n",
    )

    rc = commit_growth_guard.run(real_repo, max_growth=300, json_output=True, base=c0, head=c2)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["commits_scanned"] == 2
    # c2's trailer covers c2 and nothing else.
    assert payload["unapproved_commits"] == [c1]
    assert [row["commit"] for row in payload["approved_commits"]] == [c2]
    growth = {(v["commit"], v["path"]): v["growth"] for v in payload["violations"]}
    assert growth[(c1, "thomas/a.py")] == 500


def test_real_git_two_legal_commits_are_not_summed(real_repo, capsys) -> None:
    _write(real_repo, "thomas/a.py", 10)
    c0 = _commit(real_repo, "chore: seed")
    _write(real_repo, "thomas/wide.py", 200)
    _commit(real_repo, "feat: part 1")
    _write(real_repo, "thomas/wide.py", 400)
    c2 = _commit(real_repo, "feat: part 2")

    rc = commit_growth_guard.run(real_repo, max_growth=300, json_output=True, base=c0, head=c2)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["commits_scanned"] == 2
    assert payload["violations"] == []


def test_real_git_empty_range_is_explicit(real_repo, capsys) -> None:
    _write(real_repo, "thomas/a.py", 10)
    c0 = _commit(real_repo, "chore: seed")

    rc = commit_growth_guard.run(real_repo, max_growth=300, json_output=True, base=c0, head=c0)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["reason"] == "no_commits_in_range"
    assert payload["commits_scanned"] == 0


def test_real_git_merge_is_skipped_but_its_commits_are_measured(real_repo, capsys) -> None:
    _write(real_repo, "thomas/a.py", 10)
    base = _commit(real_repo, "chore: seed")

    _git(real_repo, "checkout", "-q", "-b", "side")
    _write(real_repo, "thomas/side.py", 400)
    c_side = _commit(real_repo, "feat: 400-line side file, no approval")

    _git(real_repo, "checkout", "-q", "main")
    _write(real_repo, "thomas/main_only.py", 5)
    _commit(real_repo, "chore: main side")
    _git(
        real_repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "merge",
        "-q",
        "--no-ff",
        "--no-verify",
        "-m",
        "merge: side",
        "side",
    )
    c_merge = _git(real_repo, "rev-parse", "HEAD")

    rc = commit_growth_guard.run(real_repo, max_growth=300, json_output=True, base=base, head=c_merge)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    # The merge itself is not measured against one parent...
    assert payload["merge_commits_skipped"] == [c_merge]
    # ...but the commit that actually wrote the 400 lines is caught.
    assert c_side in payload["unapproved_commits"]


def test_real_git_waiver_file_on_disk_waives_exactly_that_commit(real_repo, capsys) -> None:
    _write(real_repo, "thomas/a.py", 10)
    c0 = _commit(real_repo, "chore: seed")
    _write(real_repo, "thomas/a.py", 910)
    c1 = _commit(real_repo, "feat: 900-line dump, landed long ago")

    ops = real_repo / "docs" / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    registry = ops / "landed_history_waivers.json"

    registry.write_text(
        json.dumps({"version": 1, "waivers": [_waiver(c1, expires_on="2099-01-01")]}),
        encoding="utf-8",
    )
    rc = commit_growth_guard.run(real_repo, max_growth=300, json_output=True, base=c0, head=c1)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["waived_commits"][0]["commit"] == c1

    # Expired: same registry, dead date.
    registry.write_text(
        json.dumps({"version": 1, "waivers": [_waiver(c1, expires_on="2020-02-01")]}),
        encoding="utf-8",
    )
    rc = commit_growth_guard.run(real_repo, max_growth=300, json_output=True, base=c0, head=c1)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["waived_commits"] == []

    # Another guard's waiver on the same commit.
    registry.write_text(
        json.dumps({"version": 1, "waivers": [_waiver(c1, guard="bulk-commit-guard", expires_on="2099-01-01")]}),
        encoding="utf-8",
    )
    rc = commit_growth_guard.run(real_repo, max_growth=300, json_output=True, base=c0, head=c1)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["waived_commits"] == []


def test_real_git_root_commit_has_no_parent_and_does_not_crash(real_repo, capsys) -> None:
    _write(real_repo, "thomas/root.py", 900)
    c0 = _commit(real_repo, "chore: root commit with 900 lines")

    assert commit_growth_guard._commit_parent(real_repo, c0) == commit_growth_guard.EMPTY_TREE_SHA

    rc = commit_growth_guard.run(
        real_repo,
        max_growth=300,
        json_output=True,
        base=commit_growth_guard.EMPTY_TREE_SHA,
        head=c0,
    )
    payload = json.loads(capsys.readouterr().out)

    # A root commit's files are all new, so the 900-line file is a violation.
    assert rc == 1
    assert payload["violations"][0]["is_new_file"] is True
    assert payload["violations"][0]["growth"] == 900
