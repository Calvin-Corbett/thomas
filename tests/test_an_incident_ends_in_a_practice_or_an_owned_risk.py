"""An incident may end in a practice or an owned risk -- never a shrug.

Pins the closure gate's contract (spec: the internal design record
forging-loop.md, Task 2; scripts/forge/gates/problem_closure_gate.py):

  * a Task Problems entry or a PROBLEM.md header reaching `status=resolved`
    requires exactly one `closure:` line in that PROBLEM.md;
  * the three closure forms (`gate:<filename>`, `tombstone:<id>`,
    `accepted-risk:<id>`) each resolve through the real registry they name --
    RED_PATH_CASES membership via import, graveyard/risks via their load();
  * an unresolvable reference is a FAIL naming the defect; an expired
    accepted risk is a FAIL naming the owner and the expiry date, with the
    re-open instruction;
  * a malformed (not missing) registry is a pass-with-note, never a FAIL --
    the registry being broken is not evidence the closure is bad;
  * zero closure lines on a resolving incident is a FAIL; more than one is
    also a FAIL naming the ambiguity;
  * an already-resolved-unchanged incident is out of scope (skipped
    entirely, even if its closure would not resolve); a closure SWAPPED on a
    standing resolved is caught (the phase-1.4 lesson).

Fixtures build real tiny git repos (never hand-parsed diffs) and call
`run_check()` directly in STAGED mode (HEAD vs the index) -- the same mode
the gate defaults to for local pre-commit use. The RED_PATH_CASES-through-
the-real-shim coverage lives in test_every_enforcing_gate_can_fail.py
(parametrized over the registry), not duplicated here.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

from scripts.forge import graveyard
from scripts.forge.gates import problem_closure_gate as gate

DEFAULT_STATUS = "in_progress"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    return repo


def _write_board(repo: Path, entries: list[str]) -> None:
    board = repo / "plans" / "thomas" / "WORKBOARD.md"
    board.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(entries) if entries else "- none"
    board.write_text(
        "# Test Workboard\n\n## Active Tasks\n\n- none\n\n"
        "## Up For Grabs\n\n- none\n\n"
        f"## Task Problems\n\n{body}\n",
        encoding="utf-8",
        newline="\n",
    )


def _board_entry(task_id: str, path: str, status: str) -> str:
    return (
        f"- task_id={task_id}; problem={path}; owner=unassigned; status={status}; "
        "updated_at=2026-01-01T00:00:00+00:00; summary=test incident"
    )


def _write_problem(
    repo: Path,
    task_id: str,
    *,
    status: str,
    closures: list[str] | None = None,
    rel_path: str | None = None,
) -> str:
    rel_path = rel_path or f"plans/thomas/problems/{task_id}/PROBLEM.md"
    abs_path = repo / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    closure_block = "".join(f"- closure: {c}\n" for c in (closures or []))
    abs_path.write_text(
        f"# PROBLEM for {task_id}\n\n"
        f"task_id: `{task_id}`\n\n"
        "- Owner: unassigned\n"
        f"- Status: {status}\n"
        "- Updated At: 2026-01-01T00:00:00+00:00\n"
        "- Scope: thomas\n"
        f"{closure_block}"
        "\n## Current Problem\n\ntest incident\n",
        encoding="utf-8",
    )
    return rel_path


def _transition(
    tmp_path: Path,
    *,
    task_id: str,
    old_status: str,
    old_closures: list[str] | None,
    new_status: str,
    new_closures: list[str] | None,
    on_board: bool = True,
    repo: Path | None = None,
) -> Path:
    """A repo whose single incident moves from (old_status, old_closures) to
    (new_status, new_closures), committed then staged so run_check(repo)
    (default staged mode) sees the transition. `on_board=False` omits the
    workboard Task Problems entry entirely -- the file-only scope path.
    Pass an already-`_init_repo`'d `repo` when the test needs to seed a
    registry (a real id from graveyard.record_death, say) into that SAME
    repo before writing the closure line that references it."""
    repo = repo if repo is not None else _init_repo(tmp_path)
    path = f"plans/thomas/problems/{task_id}/PROBLEM.md"
    old_entries = [_board_entry(task_id, path, old_status)] if on_board else []
    new_entries = [_board_entry(task_id, path, new_status)] if on_board else []

    _write_board(repo, old_entries)
    _write_problem(repo, task_id, status=old_status, closures=old_closures, rel_path=path)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "old state")

    _write_board(repo, new_entries)
    _write_problem(repo, task_id, status=new_status, closures=new_closures, rel_path=path)
    _git(repo, "add", "-A")
    return repo


# ---------------------------------------------------------------------------
# The three forms resolve when the reference is real
# ---------------------------------------------------------------------------


def test_a_gate_form_closure_resolves_when_the_gate_is_red_path_covered(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="gate-closes",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["gate:monolith_guard.py"],
    )

    result = gate.run_check(repo)

    assert result["ok"], result["violations"]
    assert result["resolved_count"] == 1


def test_a_tombstone_form_closure_resolves_when_the_id_is_in_the_graveyard(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    death_id = graveyard.record_death(repo, "file", "old/dead.py", "deadbeef", reason="replaced", by="test-suite")
    _transition(
        tmp_path,
        repo=repo,
        task_id="tombstone-closes",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=[f"tombstone:{death_id}"],
    )

    result = gate.run_check(repo)

    assert result["ok"], result["violations"]
    assert result["resolved_count"] == 1


def test_an_accepted_risk_form_closure_resolves_when_unexpired(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="risk-closes",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["accepted-risk:accepted-risk-1"],
    )
    _seed_risk(repo, "accepted-risk-1", expires_on=_future_date())

    result = gate.run_check(repo)

    assert result["ok"], result["violations"]
    assert result["resolved_count"] == 1


# ---------------------------------------------------------------------------
# Each form FAILS naming the defect when the reference does not resolve
# ---------------------------------------------------------------------------


def test_a_gate_form_closure_fails_naming_the_unregistered_filename(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="gate-fails",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["gate:not_a_real_gate.py"],
    )

    result = gate.run_check(repo)

    assert not result["ok"]
    assert "not_a_real_gate.py" in result["violations"][0]["detail"]
    assert "gate-fails" in result["violations"][0]["detail"]


def test_a_tombstone_form_closure_fails_naming_the_unresolved_id(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="tombstone-fails",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["tombstone:does-not-exist-1"],
    )

    result = gate.run_check(repo)

    assert not result["ok"]
    assert "does-not-exist-1" in result["violations"][0]["detail"]


def test_an_accepted_risk_form_closure_fails_naming_the_unresolved_id(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="risk-fails",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["accepted-risk:does-not-exist-1"],
    )

    result = gate.run_check(repo)

    assert not result["ok"]
    assert "does-not-exist-1" in result["violations"][0]["detail"]


def test_a_recognized_but_malformed_closure_form_fails_naming_the_defect(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="malformed-fails",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["just a shrug"],
    )

    result = gate.run_check(repo)

    assert not result["ok"]
    assert "just a shrug" in result["violations"][0]["detail"]


# ---------------------------------------------------------------------------
# Expired accepted-risk: FAIL with the re-open instruction naming owner + date
# ---------------------------------------------------------------------------


def _seed_risk(repo: Path, risk_id: str, *, expires_on: str, owner: str = "test-user") -> None:
    path = repo / "docs" / "ops" / "accepted_risks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "records": [
            {
                "id": risk_id,
                "owner": owner,
                "reason": "test risk",
                "reviewed_on": "2020-01-01",
                "expires_on": expires_on,
                "refs": None,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _future_date() -> str:
    return (dt.date.today() + dt.timedelta(days=30)).isoformat()


def _past_date() -> str:
    return (dt.date.today() - dt.timedelta(days=1)).isoformat()


def test_an_expired_accepted_risk_fails_with_the_reopen_instruction_naming_owner_and_expiry(tmp_path: Path) -> None:
    expired_on = _past_date()
    repo = _transition(
        tmp_path,
        task_id="risk-expired",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["accepted-risk:expired-risk-1"],
    )
    _seed_risk(repo, "expired-risk-1", expires_on=expired_on, owner="test-user")

    result = gate.run_check(repo)

    assert not result["ok"]
    detail = result["violations"][0]["detail"]
    assert "EXPIRED" in detail
    assert "test-user" in detail
    assert expired_on in detail
    assert "re-opens" in detail


def test_an_accepted_risk_expiring_exactly_today_is_not_expired(tmp_path: Path) -> None:
    today = dt.date.today().isoformat()
    repo = _transition(
        tmp_path,
        task_id="risk-boundary",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["accepted-risk:boundary-risk-1"],
    )
    _seed_risk(repo, "boundary-risk-1", expires_on=today)

    result = gate.run_check(repo)

    assert result["ok"], result["violations"]


# ---------------------------------------------------------------------------
# Fix round 2: a garbage expires_on is a RECORD-level defect -- FAILs naming
# the record id and the defect, never a note-pass. The whole-registry-
# malformed case on the other side of the same boundary still note-passes.
# ---------------------------------------------------------------------------


def test_a_garbage_expires_on_on_a_referenced_record_fails_naming_the_record_id(tmp_path: Path) -> None:
    """Reachable only by hand-editing docs/ops/accepted_risks.json directly --
    record_risk()'s own validation rejects an unparseable expires_on before
    it can ever be written normally. Before this fix, risks.is_expired's
    unguarded dt.date.fromisoformat raised ValueError straight through
    run_check, violating its "never raises" contract."""
    repo = _transition(
        tmp_path,
        task_id="garbage-expiry-fails",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["accepted-risk:garbage-risk-1"],
    )
    _seed_risk(repo, "garbage-risk-1", expires_on="not-a-real-date")

    result = gate.run_check(repo)

    assert not result["ok"]
    assert result["violations"][0]["classification"] == "failed"
    detail = result["violations"][0]["detail"]
    assert "garbage-risk-1" in detail
    assert "unparseable" in detail
    assert result["unavailable_count"] == 0


def test_a_whole_malformed_accepted_risks_registry_still_note_passes_the_boundary_from_both_sides(
    tmp_path: Path,
) -> None:
    """The other side of the same boundary, pinned in the same place: a
    registry FILE that fails to parse entirely is file-level infrastructure
    absence, still a pass-with-note -- unchanged by the record-level fix
    above. (The single-record variant of this exists already as
    test_an_unreadable_accepted_risks_registry_is_a_pass_with_a_printed_note;
    this test exists so both edges of the file-vs-record boundary are pinned
    side by side.)"""
    repo = _transition(
        tmp_path,
        task_id="whole-registry-malformed",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["accepted-risk:whatever-1"],
    )
    bad = repo / "docs" / "ops" / "accepted_risks.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("not even json at all", encoding="utf-8")

    result = gate.run_check(repo)

    assert result["ok"], result["violations"]
    assert result["unavailable_count"] == 1
    assert result["results"][0]["classification"] == "unavailable"


def test_a_null_expires_on_on_a_referenced_record_fails_classified_not_a_traceback(tmp_path: Path) -> None:
    """Fix round 3 (verifier-found): expires_on present but non-string --
    null passes accepted_risks.load()'s required-key check (the key exists,
    its value is just not a date) and is hand-edit-reachable the same way a
    garbage string is. dt.date.fromisoformat(None) raises TypeError, not
    ValueError -- the round-2 guard missed this exception class."""
    repo = _transition(
        tmp_path,
        task_id="null-expiry-fails",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["accepted-risk:null-risk-1"],
    )
    _seed_risk(repo, "null-risk-1", expires_on=None)

    result = gate.run_check(repo)

    assert not result["ok"]
    assert result["violations"][0]["classification"] == "failed"
    assert "null-risk-1" in result["violations"][0]["detail"]
    assert result["unavailable_count"] == 0


def test_an_int_expires_on_on_a_referenced_record_fails_classified_not_a_traceback(tmp_path: Path) -> None:
    """Same class, the other hand-edit-reachable non-string shape: a bare
    JSON integer for expires_on (e.g. 20261231) also passes the
    required-key check and also makes dt.date.fromisoformat raise
    TypeError."""
    repo = _transition(
        tmp_path,
        task_id="int-expiry-fails",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["accepted-risk:int-risk-1"],
    )
    _seed_risk(repo, "int-risk-1", expires_on=20261231)

    result = gate.run_check(repo)

    assert not result["ok"]
    assert result["violations"][0]["classification"] == "failed"
    assert "int-risk-1" in result["violations"][0]["detail"]
    assert result["unavailable_count"] == 0


# ---------------------------------------------------------------------------
# Unreadable (malformed, not missing) registries: pass-with-note, never FAIL
# ---------------------------------------------------------------------------


def test_an_unreadable_accepted_risks_registry_is_a_pass_with_a_printed_note(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="risk-unavailable",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["accepted-risk:whatever-1"],
    )
    bad = repo / "docs" / "ops" / "accepted_risks.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not valid json", encoding="utf-8")

    result = gate.run_check(repo)

    assert result["ok"], result["violations"]
    assert result["unavailable_count"] == 1
    assert result["results"][0]["classification"] == "unavailable"


def test_an_unreadable_graveyard_registry_is_a_pass_with_a_printed_note(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="tombstone-unavailable",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["tombstone:whatever-1"],
    )
    bad = repo / "docs" / "ops" / "graveyard.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not valid json", encoding="utf-8")

    result = gate.run_check(repo)

    assert result["ok"], result["violations"]
    assert result["unavailable_count"] == 1
    assert result["results"][0]["classification"] == "unavailable"


# ---------------------------------------------------------------------------
# Missing / multiple closure lines
# ---------------------------------------------------------------------------


def test_a_resolving_incident_with_no_closure_line_fails_naming_the_incident(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="no-closure",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=None,
    )

    result = gate.run_check(repo)

    assert not result["ok"]
    assert result["violations"][0]["classification"] == "missing_closure"
    assert "no-closure" in result["violations"][0]["detail"]


def test_a_resolving_incident_with_two_closure_lines_fails_naming_the_ambiguity(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="two-closures",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=["gate:monolith_guard.py", "tombstone:some-id"],
    )

    result = gate.run_check(repo)

    assert not result["ok"]
    assert result["violations"][0]["classification"] == "ambiguous_closure"
    assert "two-closures" in result["violations"][0]["detail"]


# ---------------------------------------------------------------------------
# Scope: already-resolved-unchanged is skipped; a closure swap is caught
# ---------------------------------------------------------------------------


def test_an_already_resolved_incident_with_an_unchanged_closure_is_out_of_scope(tmp_path: Path) -> None:
    # The closure would FAIL if it were ever evaluated -- proving this is
    # truly SKIPPED, not evaluated-and-happens-to-pass.
    repo = _transition(
        tmp_path,
        task_id="standing-resolved",
        old_status="resolved",
        old_closures=["gate:not_a_real_gate.py"],
        new_status="resolved",
        new_closures=["gate:not_a_real_gate.py"],
    )

    result = gate.run_check(repo)

    assert result["ok"], result["violations"]
    assert result["incidents_checked"] == 0


def test_a_closure_swap_on_a_standing_resolved_incident_is_caught(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _seed_risk(repo, "swap-risk-old", expires_on=_future_date())
    _transition(
        tmp_path,
        repo=repo,
        task_id="swapped-closure",
        old_status="resolved",
        old_closures=["accepted-risk:swap-risk-old"],
        new_status="resolved",
        new_closures=["accepted-risk:swap-risk-new"],  # never recorded -- unresolvable
    )

    result = gate.run_check(repo)

    assert not result["ok"], "a closure swapped on a standing resolved must be re-checked, not skipped"
    assert "swap-risk-new" in result["violations"][0]["detail"]


# ---------------------------------------------------------------------------
# Scope: a PROBLEM.md header resolving with no matching workboard entry
# ---------------------------------------------------------------------------


def test_a_problem_file_header_resolving_with_no_workboard_entry_is_still_in_scope(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="header-only",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=None,
        on_board=False,
    )

    result = gate.run_check(repo)

    assert not result["ok"]
    assert result["violations"][0]["classification"] == "missing_closure"


# ---------------------------------------------------------------------------
# Diff-range mode (the CI form) sees the identical transition
# ---------------------------------------------------------------------------


def test_diff_range_mode_sees_the_same_transition_as_staged_mode(tmp_path: Path) -> None:
    repo = _transition(
        tmp_path,
        task_id="diff-range-fails",
        old_status=DEFAULT_STATUS,
        old_closures=None,
        new_status="resolved",
        new_closures=None,
    )
    _git(repo, "commit", "-m", "new state")

    result = gate.run_check(repo, base="HEAD~1", head="HEAD")

    assert not result["ok"]
    assert result["mode"] == "diff-range"
    assert result["violations"][0]["classification"] == "missing_closure"


# ---------------------------------------------------------------------------
# Fix round 1 (Important-1): a fenced example is documentation, not a
# closure line. Task 3's planned `## Closure` template stub shows all three
# forms inside a fence for exactly this reason -- these three tests pin the
# collision that would otherwise land the moment that template ships.
# ---------------------------------------------------------------------------


def _problem_body(task_id: str, status: str, extra: str = "") -> str:
    return (
        f"# PROBLEM for {task_id}\n\n"
        f"task_id: `{task_id}`\n\n"
        "- Owner: unassigned\n"
        f"- Status: {status}\n"
        "- Updated At: 2026-01-01T00:00:00+00:00\n"
        "- Scope: thomas\n"
        f"{extra}"
        "\n## Current Problem\n\ntest incident\n"
    )


def _write_problem_raw(repo: Path, *, rel_path: str, body: str) -> None:
    abs_path = repo / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(body, encoding="utf-8")


def _fence_scenario(tmp_path: Path, *, task_id: str, new_extra: str) -> Path:
    """old state: open, no closure. new state: resolved, with `new_extra`
    appended after the header bullets -- the caller controls exactly what
    (real closure lines, fenced examples, or both) appears there."""
    repo = _init_repo(tmp_path)
    path = f"plans/thomas/problems/{task_id}/PROBLEM.md"
    _write_board(repo, [_board_entry(task_id, path, DEFAULT_STATUS)])
    _write_problem_raw(repo, rel_path=path, body=_problem_body(task_id, DEFAULT_STATUS))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "old state")

    _write_board(repo, [_board_entry(task_id, path, "resolved")])
    _write_problem_raw(repo, rel_path=path, body=_problem_body(task_id, "resolved", extra=new_extra))
    _git(repo, "add", "-A")
    return repo


def test_a_real_closure_line_plus_a_fenced_example_of_all_three_forms_passes(tmp_path: Path) -> None:
    """The exact Task 3 template collision: one real closure line, plus a
    fenced ## Closure stub documenting the three forms with example syntax
    that itself looks like closure lines."""
    extra = (
        "- closure: gate:monolith_guard.py\n"
        "\n"
        "## Closure\n"
        "\n"
        "Record exactly one closure line above. Forms:\n"
        "\n"
        "```\n"
        "- closure: gate:<filename>\n"
        "- closure: tombstone:<id>\n"
        "- closure: accepted-risk:<id>\n"
        "```\n"
    )
    repo = _fence_scenario(tmp_path, task_id="fenced-example-passes", new_extra=extra)

    result = gate.run_check(repo)

    assert result["ok"], result["violations"]
    assert result["resolved_count"] == 1


def test_a_closure_line_only_inside_a_closed_fence_fails_missing_closure(tmp_path: Path) -> None:
    extra = "\n```\n- closure: gate:monolith_guard.py\n```\n"
    repo = _fence_scenario(tmp_path, task_id="fenced-only-fails", new_extra=extra)

    result = gate.run_check(repo)

    assert not result["ok"]
    assert result["violations"][0]["classification"] == "missing_closure"


def test_a_closure_line_inside_an_unclosed_fence_does_not_count(tmp_path: Path) -> None:
    """An unclosed fence swallows to EOF -- the honest reading of broken
    markdown -- so the closure line inside it (and everything after) is
    never seen as real content."""
    extra = "\n```\n- closure: gate:monolith_guard.py\n"
    repo = _fence_scenario(tmp_path, task_id="unclosed-fence-fails", new_extra=extra)

    result = gate.run_check(repo)

    assert not result["ok"]
    assert result["violations"][0]["classification"] == "missing_closure"


# ---------------------------------------------------------------------------
# Fix round 1 (Minor-3): the runtime-protection short-circuit, pinned the
# same way the workboard_evidence_gate sibling pins its own.
# ---------------------------------------------------------------------------


def test_runtime_protection_disabled_short_circuits_before_any_git_or_board_work(monkeypatch, capsys) -> None:
    monkeypatch.setattr(gate, "_runtime_protection_disabled", lambda: True)

    rc = gate.main()

    out = capsys.readouterr().out
    assert rc == 0
    assert "runtime protection disabled" in out.lower()
