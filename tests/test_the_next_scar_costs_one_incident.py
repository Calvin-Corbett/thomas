"""The next scar costs one incident -- capture teaches closure, session start
counts the open ones.

Pins phase 1.5 Task 3 (spec: the internal design record
Task 3; scripts/crew/tasks/plans.py's `## Closure` template stub;
scripts/crew/brief/incident_surfacing.py):

  * the generated PROBLEM.md template documents the three closure forms
    (`gate:<filename>`, `tombstone:<id>`, `accepted-risk:<id>`) inside a
    fenced code block -- run through the REAL closure-gate parser, the
    template must never itself read as a real closure line (the collision
    test that survives future template edits, per the Task 2 review's hard
    constraint);
  * `incident_surfacing.open_incidents_without_closure` counts every
    `plans/thomas/problems/*/PROBLEM.md` whose header status is not
    `resolved` AND carries no (unfenced) closure line, reusing the closure
    gate's own fence-aware parser rather than reimplementing it;
  * a closure line written ONLY inside a fenced block still counts as
    missing -- the same fence-awareness the gate itself relies on;
  * an unreadable/malformed PROBLEM.md -- including invalid UTF-8 -- is
    counted separately as `unreadable`, never crashes, and NEVER silences
    the count of every other incident in the scan (fix round 1, Important-1);
  * closure means RESOLVING closure: a dangling tombstone/accepted-risk
    reference or an EXPIRED accepted risk counts as open-without-closure,
    same as a missing line, by reusing the gate's own
    `_evaluate_incident`/`_resolve_closure` against the real registries
    (fix round 1, Important-2); a malformed registry degrades to a
    disclosed `unverifiable` note, never a false "has closure" and never a
    scan-wide failure;
  * `summarize()` never raises and prints an honest zero, plus the oldest
    three by the record's `- Updated At:` date;
  * `startup_router.py` surfaces the count at session start without
    changing its own text-output contract, and the move-only split that
    made room for the wiring left its existing behavior untouched.

Every fixture here lives under `tmp_path` -- this suite never reads or
writes `plans/thomas/problems/` in the real repo tree.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from scripts.crew.brief import incident_surfacing
from scripts.crew.tasks.plans import _build_problem_template
from scripts.forge.gates.problem_closure_gate import _closure_lines


def _write_problem(
    root: Path,
    task_id: str,
    *,
    status: str,
    closures: list[str] | None = None,
    updated_at: str = "2026-01-01T00:00:00+00:00",
    fence_closures: bool = False,
) -> Path:
    path = root / "plans" / "thomas" / "problems" / task_id / "PROBLEM.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if fence_closures:
        closure_block = "```\n" + "".join(f"- closure: {c}\n" for c in (closures or [])) + "```\n"
    else:
        closure_block = "".join(f"- closure: {c}\n" for c in (closures or []))
    path.write_text(
        f"# PROBLEM for {task_id}\n\n"
        f"task_id: `{task_id}`\n\n"
        "- Owner: unassigned\n"
        f"- Status: {status}\n"
        f"- Updated At: {updated_at}\n"
        "- Scope: thomas\n\n"
        f"{closure_block}"
        "\n## Current Problem\n\ntest incident\n",
        encoding="utf-8",
    )
    return path


def _write_graveyard(root: Path, records: list[dict[str, str]]) -> None:
    path = root / "docs" / "ops" / "graveyard.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "records": records}), encoding="utf-8")


def _write_accepted_risks(root: Path, records: list[dict[str, str]]) -> None:
    path = root / "docs" / "ops" / "accepted_risks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "records": records}), encoding="utf-8")


def _tombstone_record(record_id: str) -> dict[str, str]:
    return {
        "id": record_id,
        "kind": "file",
        "name": "some/removed/file.py",
        "dead_sha": "deadbeef",
        "deleted_on": "2026-01-01",
        "reason": "test fixture",
        "by": "test",
        "refs": None,
    }


def _accepted_risk_record(record_id: str, *, expires_on: str) -> dict[str, str]:
    return {
        "id": record_id,
        "owner": "test-owner",
        "reason": "test fixture",
        "reviewed_on": "2026-01-01",
        "expires_on": expires_on,
        "refs": None,
    }


# --- A: the template never produces a real closure line -------------------


def test_the_generated_problem_template_documents_closure_without_triggering_it() -> None:
    template = _build_problem_template(
        task_id="EXAMPLE-1",
        owner="unassigned",
        summary="test",
        scope="thomas",
        status="open",
        now_iso="2026-01-01T00:00:00+00:00",
    )

    assert "## Closure" in template
    assert "gate:" in template
    assert "tombstone:" in template
    assert "accepted-risk:" in template
    # The collision test: run the ACTUAL gate parser over the ACTUAL
    # generated template. Zero closure lines must ever be extracted, no
    # matter how the template's prose around the fenced example changes.
    assert _closure_lines(template) == []


def test_the_template_examples_live_inside_a_fenced_block_not_an_indented_one() -> None:
    template = _build_problem_template(
        task_id="EXAMPLE-2",
        owner="unassigned",
        summary="test",
        scope="thomas",
        status="open",
        now_iso="2026-01-01T00:00:00+00:00",
    )
    lines = template.splitlines()
    fence_lines = [line for line in lines if line.strip() in {"```", "~~~"}]
    assert len(fence_lines) >= 2, "the closure examples must be wrapped in a real fence"
    # No closure example may sit at 4+ leading spaces (an indented code block
    # the gate's fence-aware parser does NOT mask) or as a bare bullet.
    for line in lines:
        if "closure:" in line.lower() and not line.strip().startswith("`"):
            assert not line.startswith("    "), f"indented (unmasked) closure example: {line!r}"


# --- B: open_incidents_without_closure --------------------------------------


def test_an_open_incident_with_no_closure_line_is_counted(tmp_path: Path) -> None:
    _write_problem(tmp_path, "TASK-A", status="open")

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["TASK-A"]
    assert result["unreadable"] == []


def test_an_open_incident_with_a_real_closure_line_is_not_counted(tmp_path: Path) -> None:
    # monolith_guard.py is a real, permanent RED_PATH_CASES entry (pinned by
    # tests/test_every_enforcing_gate_can_fail.py itself) -- a genuinely
    # resolving gate: closure, not a bogus filename.
    _write_problem(tmp_path, "TASK-B", status="open", closures=["gate:monolith_guard.py"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert result["unverifiable"] == []


def test_a_resolved_incident_is_never_counted_even_without_closure(tmp_path: Path) -> None:
    _write_problem(tmp_path, "TASK-C", status="resolved")

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []


def test_a_closure_line_written_only_inside_a_fence_still_counts_as_missing(tmp_path: Path) -> None:
    _write_problem(tmp_path, "TASK-D", status="open", closures=["gate:example.py"], fence_closures=True)

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["TASK-D"]


def test_an_unreadable_problem_file_is_noted_not_crashed(tmp_path: Path) -> None:
    # A directory named PROBLEM.md is unreadable as text -- read_text() raises
    # OSError (IsADirectoryError on POSIX, PermissionError on Windows).
    bad = tmp_path / "plans" / "thomas" / "problems" / "TASK-E" / "PROBLEM.md"
    bad.mkdir(parents=True)

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert len(result["unreadable"]) == 1
    assert "TASK-E" in result["unreadable"][0]["problem_path"]


def test_no_problems_directory_at_all_is_an_honest_empty_result(tmp_path: Path) -> None:
    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result == {"open": [], "reopen_due": [], "unreadable": [], "unverifiable": [], "recurring": []}


def test_a_binary_problem_file_does_not_silence_the_rest_of_the_scan(tmp_path: Path) -> None:
    """Important-1 repro: an invalid-UTF-8 PROBLEM.md must not degrade the
    whole scan. UnicodeDecodeError is a ValueError, not an OSError -- a
    per-file catch that only covers OSError misses it entirely."""
    _write_problem(tmp_path, "TASK-OK", status="open")
    bad = tmp_path / "plans" / "thomas" / "problems" / "TASK-BINARY" / "PROBLEM.md"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"\xff\xfe\x80not valid utf-8")

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["TASK-OK"]
    assert len(result["unreadable"]) == 1
    assert "TASK-BINARY" in result["unreadable"][0]["problem_path"]

    summary = incident_surfacing.summarize(tmp_path)
    assert summary["ok"] is True
    assert summary["count"] == 1
    assert summary["unreadable_count"] == 1


# --- B2: closure means RESOLVING closure (fix round 1, Important-2) --------


def test_a_dangling_tombstone_reference_is_counted_as_open(tmp_path: Path) -> None:
    _write_graveyard(tmp_path, [])  # registry present, but no matching record
    _write_problem(tmp_path, "TASK-DANGLE-TOMB", status="open", closures=["tombstone:does-not-exist-1"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["TASK-DANGLE-TOMB"]
    assert result["unverifiable"] == []


def test_a_valid_tombstone_reference_is_not_counted(tmp_path: Path) -> None:
    _write_graveyard(tmp_path, [_tombstone_record("2026-01-01-removed-file-1")])
    _write_problem(tmp_path, "TASK-REAL-TOMB", status="open", closures=["tombstone:2026-01-01-removed-file-1"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []


def test_an_expired_accepted_risk_is_counted_as_open(tmp_path: Path) -> None:
    _write_accepted_risks(tmp_path, [_accepted_risk_record("2020-01-01-old-risk-1", expires_on="2020-06-01")])
    _write_problem(tmp_path, "TASK-EXPIRED-RISK", status="open", closures=["accepted-risk:2020-01-01-old-risk-1"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["TASK-EXPIRED-RISK"]


def test_an_unexpired_accepted_risk_is_not_counted(tmp_path: Path) -> None:
    _write_accepted_risks(tmp_path, [_accepted_risk_record("2099-01-01-future-risk-1", expires_on="2099-12-31")])
    _write_problem(tmp_path, "TASK-LIVE-RISK", status="open", closures=["accepted-risk:2099-01-01-future-risk-1"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []


def test_a_dangling_accepted_risk_reference_is_counted_as_open(tmp_path: Path) -> None:
    _write_accepted_risks(tmp_path, [])
    _write_problem(tmp_path, "TASK-DANGLE-RISK", status="open", closures=["accepted-risk:does-not-exist"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["TASK-DANGLE-RISK"]


def test_an_unregistered_gate_reference_is_counted_as_open(tmp_path: Path) -> None:
    # A gate: closure naming a filename that is not a RED_PATH_CASES key --
    # the chosen gate: behavior (fix round 1, Important-2) resolves it
    # through the same import the gate itself uses, and a name that isn't
    # registered is a genuine dangling reference, not a free pass.
    _write_problem(tmp_path, "TASK-FAKE-GATE", status="open", closures=["gate:not_a_real_gate_at_all.py"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["TASK-FAKE-GATE"]


def test_a_malformed_accepted_risks_registry_is_noted_not_crashed(tmp_path: Path) -> None:
    """A broken registry is an infrastructure problem, not evidence the
    closure is bad -- the incident is neither falsely closed nor falsely
    flagged open; it is reported separately as unverifiable, and the scan
    continues (a healthy incident elsewhere is still counted)."""
    path = tmp_path / "docs" / "ops" / "accepted_risks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    _write_problem(tmp_path, "TASK-UNVERIFIABLE", status="open", closures=["accepted-risk:whatever-1"])
    _write_problem(tmp_path, "TASK-HEALTHY", status="open")

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == [
        row for row in result["open"] if row["task_id"] == "TASK-HEALTHY"
    ]  # TASK-UNVERIFIABLE never counted as open
    assert [row["task_id"] for row in result["open"]] == ["TASK-HEALTHY"]
    assert len(result["unverifiable"]) == 1
    assert result["unverifiable"][0]["task_id"] == "TASK-UNVERIFIABLE"

    summary = incident_surfacing.summarize(tmp_path)
    assert summary["ok"] is True
    assert summary["count"] == 1
    assert summary["unverifiable_count"] == 1
    text = incident_surfacing.render_text(summary)
    assert "unverifiable=1" in text


def test_a_record_level_garbage_expires_on_is_counted_as_open_not_unreadable(tmp_path: Path) -> None:
    """Fix round 2 (closure gate): a record that LOADS fine (the whole
    registry file is well-formed JSON with every required key) but whose
    `expires_on` value is not a real date is a RECORD-level defect, not
    file-level infrastructure absence. Before the gate's fix,
    `problem_closure_gate._resolve_closure` let `risks.is_expired`'s
    `ValueError` raise straight through `_evaluate_incident`; this module's
    own wide per-file exception net (`_PER_FILE_EXCEPTIONS` includes
    `ValueError`) then caught it and silently demoted the incident to
    `unreadable` -- a DIFFERENT bucket than the gate's own classification.
    Now that the gate classifies this as `failed` (never raising), it falls
    through here to the plain open-without-closure path, same as any other
    dangling/expired reference -- the two readers agree on ONE answer."""
    _write_accepted_risks(tmp_path, [_accepted_risk_record("garbage-risk-1", expires_on="not-a-real-date")])
    _write_problem(tmp_path, "TASK-GARBAGE-EXPIRY", status="open", closures=["accepted-risk:garbage-risk-1"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["TASK-GARBAGE-EXPIRY"]
    assert result["unreadable"] == []
    assert result["unverifiable"] == []


def test_a_null_expires_on_is_counted_as_open_not_unreadable(tmp_path: Path) -> None:
    """Fix round 3: expires_on = null is the other reader's own pinned
    proof of the same fix -- the gate now classifies this `failed` instead
    of raising TypeError, so it falls through here to `open`, same as the
    round-2 garbage-string case."""
    _write_accepted_risks(tmp_path, [_accepted_risk_record("null-risk-1", expires_on=None)])
    _write_problem(tmp_path, "TASK-NULL-EXPIRY", status="open", closures=["accepted-risk:null-risk-1"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["TASK-NULL-EXPIRY"]
    assert result["unreadable"] == []
    assert result["unverifiable"] == []


def test_an_int_expires_on_is_counted_as_open_not_unreadable(tmp_path: Path) -> None:
    """Same class: a bare JSON integer expires_on (e.g. 20261231) is also
    hand-edit-reachable and also now classifies as open, not unreadable."""
    _write_accepted_risks(tmp_path, [_accepted_risk_record("int-risk-1", expires_on=20261231)])
    _write_problem(tmp_path, "TASK-INT-EXPIRY", status="open", closures=["accepted-risk:int-risk-1"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["TASK-INT-EXPIRY"]
    assert result["unreadable"] == []
    assert result["unverifiable"] == []


# --- E: expiry re-opens a resolved incident (final-review Critical-1) -----


def test_a_resolved_incident_with_an_expired_accepted_risk_needs_reopening(tmp_path: Path) -> None:
    """The reviewer's exact repro shape: a RESOLVED incident closed on an
    accepted risk that has since expired must surface as REOPEN DUE, not
    vanish silently -- the gate cannot catch this (it runs on diffs), so
    surfacing is the only process that re-checks a standing resolved
    incident, every session start."""
    _write_accepted_risks(tmp_path, [_accepted_risk_record("2026-01-01-lapsed-risk-1", expires_on="2020-06-01")])
    _write_problem(tmp_path, "TASK-LAPSED", status="resolved", closures=["accepted-risk:2026-01-01-lapsed-risk-1"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []  # never inflates the open count
    assert [row["task_id"] for row in result["reopen_due"]] == ["TASK-LAPSED"]
    assert "expired" in result["reopen_due"][0]["reason"]
    assert "2020-06-01" in result["reopen_due"][0]["reason"]

    summary = incident_surfacing.summarize(tmp_path)
    assert summary["count"] == 0
    assert summary["reopen_due_count"] == 1
    text = incident_surfacing.render_text(summary)
    assert "REOPEN DUE: 1 resolved incidents whose closure no longer holds" in text
    assert "TASK-LAPSED" in text


def test_a_resolved_incident_with_a_still_valid_closure_stays_invisible(tmp_path: Path) -> None:
    _write_accepted_risks(tmp_path, [_accepted_risk_record("2099-01-01-live-risk-1", expires_on="2099-12-31")])
    _write_problem(tmp_path, "TASK-STILL-CLOSED", status="resolved", closures=["accepted-risk:2099-01-01-live-risk-1"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert result["reopen_due"] == []


def test_a_resolved_incident_with_a_dangling_tombstone_needs_reopening(tmp_path: Path) -> None:
    _write_graveyard(tmp_path, [])
    _write_problem(tmp_path, "TASK-RESOLVED-DANGLE-TOMB", status="resolved", closures=["tombstone:does-not-exist-9"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert [row["task_id"] for row in result["reopen_due"]] == ["TASK-RESOLVED-DANGLE-TOMB"]
    assert "dangling" in result["reopen_due"][0]["reason"]


def test_a_resolved_incident_whose_gate_ref_is_no_longer_in_red_path_needs_reopening(tmp_path: Path) -> None:
    _write_problem(tmp_path, "TASK-RESOLVED-STALE-GATE", status="resolved", closures=["gate:not_a_real_gate_at_all.py"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert [row["task_id"] for row in result["reopen_due"]] == ["TASK-RESOLVED-STALE-GATE"]


def test_a_resolved_incident_with_a_valid_gate_ref_stays_invisible(tmp_path: Path) -> None:
    # monolith_guard.py is a real, permanent RED_PATH_CASES entry.
    _write_problem(tmp_path, "TASK-RESOLVED-REAL-GATE", status="resolved", closures=["gate:monolith_guard.py"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert result["reopen_due"] == []


def test_a_resolved_incident_with_no_closure_line_at_all_is_the_legacy_drain_not_a_reopen(tmp_path: Path) -> None:
    """Deliberate exclusion: a resolved incident with ZERO closure lines is
    the disclosed legacy-drain population (resolved before the closure gate
    existed), not "a closure that used to hold and now fails" -- it must
    not flood REOPEN DUE with every pre-gate resolved incident."""
    _write_problem(tmp_path, "TASK-LEGACY-RESOLVED", status="resolved")

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert result["reopen_due"] == []


def test_a_resolved_incident_whose_registry_is_malformed_is_unverifiable_not_reopened(tmp_path: Path) -> None:
    """A broken registry is an infra problem, not proof the closure failed
    -- a resolved incident relying on it must not be falsely re-opened."""
    path = tmp_path / "docs" / "ops" / "accepted_risks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    _write_problem(tmp_path, "TASK-RESOLVED-UNVERIFIABLE", status="resolved", closures=["accepted-risk:whatever-2"])

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert result["reopen_due"] == []
    assert len(result["unverifiable"]) == 1
    assert result["unverifiable"][0]["task_id"] == "TASK-RESOLVED-UNVERIFIABLE"


def test_reopen_due_never_inflates_the_open_count_alongside_real_open_incidents(tmp_path: Path) -> None:
    _write_accepted_risks(tmp_path, [_accepted_risk_record("2026-01-01-lapsed-risk-2", expires_on="2020-06-01")])
    _write_problem(tmp_path, "TASK-OPEN", status="open")
    _write_problem(tmp_path, "TASK-REOPEN", status="resolved", closures=["accepted-risk:2026-01-01-lapsed-risk-2"])

    summary = incident_surfacing.summarize(tmp_path)

    assert summary["count"] == 1  # only TASK-OPEN
    assert summary["reopen_due_count"] == 1  # TASK-REOPEN, counted separately, never merged in


def test_the_cli_json_mode_includes_the_reopen_due_category(tmp_path: Path, capsys) -> None:
    _write_accepted_risks(tmp_path, [_accepted_risk_record("2026-01-01-lapsed-risk-3", expires_on="2020-06-01")])
    _write_problem(tmp_path, "TASK-JSON-REOPEN", status="resolved", closures=["accepted-risk:2026-01-01-lapsed-risk-3"])

    exit_code = incident_surfacing.main(["--repo-root", str(tmp_path), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["reopen_due_count"] == 1
    assert payload["reopen_due"][0]["task_id"] == "TASK-JSON-REOPEN"


# --- C: summarize()/render_text() never raise, honest zero, oldest-three ---


def test_an_honest_zero_is_printed_as_zero(tmp_path: Path) -> None:
    (tmp_path / "plans" / "thomas" / "problems").mkdir(parents=True)

    summary = incident_surfacing.summarize(tmp_path)

    assert summary["ok"] is True
    assert summary["count"] == 0
    assert summary["reopen_due_count"] == 0
    assert summary["recurring_count"] == 0
    assert incident_surfacing.render_text(summary) == (
        "INCIDENTS: 0 open without closure\n"
        "REOPEN DUE: 0 resolved incidents whose closure no longer holds\n"
        "RECURRING: 0 standing"
    )


def test_the_oldest_three_incidents_are_listed_in_date_order(tmp_path: Path) -> None:
    _write_problem(tmp_path, "TASK-NEW", status="open", updated_at="2026-06-01T00:00:00+00:00")
    _write_problem(tmp_path, "TASK-OLD", status="open", updated_at="2026-01-01T00:00:00+00:00")
    _write_problem(tmp_path, "TASK-MID", status="open", updated_at="2026-03-01T00:00:00+00:00")
    _write_problem(tmp_path, "TASK-OLDEST", status="open", updated_at="2025-12-01T00:00:00+00:00")

    summary = incident_surfacing.summarize(tmp_path)

    assert summary["count"] == 4
    assert [row["task_id"] for row in summary["oldest"]] == ["TASK-OLDEST", "TASK-OLD", "TASK-MID"]


def test_unreadable_files_are_reported_as_a_separate_note_in_the_summary(tmp_path: Path) -> None:
    _write_problem(tmp_path, "TASK-F", status="open")
    bad = tmp_path / "plans" / "thomas" / "problems" / "TASK-BAD" / "PROBLEM.md"
    bad.mkdir(parents=True)

    summary = incident_surfacing.summarize(tmp_path)

    assert summary["count"] == 1
    assert summary["unreadable_count"] == 1
    text = incident_surfacing.render_text(summary)
    assert "unreadable=1" in text


def test_the_summary_never_raises_even_when_the_scan_itself_blows_up(tmp_path: Path, monkeypatch) -> None:
    def _boom(_repo_root):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(incident_surfacing, "open_incidents_without_closure", _boom)

    summary = incident_surfacing.summarize(tmp_path)

    assert summary["ok"] is False
    text = incident_surfacing.render_text(summary)
    assert text.startswith("INCIDENTS: unavailable (")


def test_the_cli_json_mode_emits_parseable_json(tmp_path: Path, capsys) -> None:
    (tmp_path / "plans" / "thomas" / "problems").mkdir(parents=True)

    exit_code = incident_surfacing.main(["--repo-root", str(tmp_path), "--json"])

    assert exit_code == 0
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 0


# NOTE: recurring-vocabulary tests (recon #10) live in
# tests/test_recurring_work_gets_a_name.py, not here -- this file was
# already at 767/800 of the unbaselined monolith-guard soft limit, and the
# recurring contract is a self-contained slice (its own fixture writer,
# its own real-git-repo gate-fixture) that does not need this file's other
# helpers.


# --- D: the router split + wiring did not change behavior ------------------


def _load_router_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "crew" / "brief" / "startup_router.py"
    spec = importlib.util.spec_from_file_location("crew_brief_startup_router_incident_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_startup_router_still_classifies_after_the_signals_split(tmp_path: Path) -> None:
    mod = _load_router_module()
    board = tmp_path / "WORKBOARD.md"
    board.write_text(
        "# Thomas Workboard\n\nLast updated: 2026-03-18\n\n"
        "## Agent Claims\n\n- none\n\n## Active Tasks\n\n- none\n",
        encoding="utf-8",
    )

    payload = mod.classify_task(
        summary="Answer a repo question",
        paths=[],
        edit_intent=False,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=board,
    )

    assert payload["lane"] == "chat"


def test_the_startup_router_text_output_surfaces_the_incident_count() -> None:
    mod = _load_router_module()
    payload = {
        "lane": "chat",
        "workflow_mode": "guided",
        "edit_intent": False,
        "workboard_required": False,
        "workboard": {
            "path": "plans/thomas/WORKBOARD.md",
            "active_claims": 0,
            "matching_claims": [],
            "claim_conflict": False,
            "stale": False,
            "updated_at": "2026-06-02",
        },
        "bootstrap_command": "",
        "gate_handling": {},
        "flags": {
            "ui_proof": False,
            "benchmark_mode": False,
            "tracked_work": False,
            "multi_agent": False,
            "long_running": False,
            "risky_paths": [],
        },
        "paths": [],
        "required_reads": [],
        "required_checks": [],
        "escalation_triggers": [],
        "preflight": {},
        "incident_surfacing": {
            "ok": True,
            "count": 2,
            "unreadable_count": 0,
            "oldest": [
                {"task_id": "OLD-1", "problem_path": "plans/thomas/problems/OLD-1/PROBLEM.md", "status": "open"},
            ],
        },
    }

    text = mod._text_output(payload)

    assert "INCIDENTS: 2 open without closure" in text


def test_the_startup_router_incident_line_degrades_quietly_when_unavailable() -> None:
    mod = _load_router_module()
    payload = {
        "lane": "chat",
        "workflow_mode": "guided",
        "edit_intent": False,
        "workboard_required": False,
        "workboard": {
            "path": "plans/thomas/WORKBOARD.md",
            "active_claims": 0,
            "matching_claims": [],
            "claim_conflict": False,
            "stale": False,
            "updated_at": "2026-06-02",
        },
        "bootstrap_command": "",
        "gate_handling": {},
        "flags": {
            "ui_proof": False,
            "benchmark_mode": False,
            "tracked_work": False,
            "multi_agent": False,
            "long_running": False,
            "risky_paths": [],
        },
        "paths": [],
        "required_reads": [],
        "required_checks": [],
        "escalation_triggers": [],
        "preflight": {},
        "incident_surfacing": {"ok": False, "error": "boom", "count": 0, "oldest": [], "unreadable_count": 0},
    }

    text = mod._text_output(payload)

    assert "INCIDENTS: unavailable (boom)" in text


def test_build_startup_payload_calls_incident_surfacing_and_never_raises(monkeypatch, tmp_path: Path) -> None:
    mod = _load_router_module()
    monkeypatch.setattr(
        mod.agent_preflight,
        "evaluate_preflight",
        lambda **_: {
            "status": "ok",
            "summary": "3 ok",
            "checks": [],
            "policy": {"summary": "", "can_edit": True, "report_before_fallback": False, "stop_before_edit": False},
            "root": str(mod.ROOT),
            "cwd": str(mod.ROOT),
        },
    )
    monkeypatch.setattr(
        mod.incident_surfacing,
        "summarize",
        lambda _root: {"ok": True, "count": 3, "unreadable_count": 0, "oldest": []},
    )
    board = tmp_path / "WORKBOARD.md"
    board.write_text(
        "# Thomas Workboard\n\nLast updated: 2026-03-18\n\n"
        "## Agent Claims\n\n- none\n\n## Active Tasks\n\n- none\n",
        encoding="utf-8",
    )

    payload = mod.build_startup_payload(
        summary="Answer a repo question",
        paths=[],
        edit_intent=False,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=board,
        cwd=mod.ROOT,
    )

    assert payload["incident_surfacing"]["count"] == 3


def test_build_startup_payload_never_fails_session_start_when_incident_surfacing_blows_up(
    monkeypatch, tmp_path: Path
) -> None:
    mod = _load_router_module()
    monkeypatch.setattr(
        mod.agent_preflight,
        "evaluate_preflight",
        lambda **_: {
            "status": "ok",
            "summary": "3 ok",
            "checks": [],
            "policy": {"summary": "", "can_edit": True, "report_before_fallback": False, "stop_before_edit": False},
            "root": str(mod.ROOT),
            "cwd": str(mod.ROOT),
        },
    )

    def _boom(_root):
        raise RuntimeError("catastrophic")

    monkeypatch.setattr(mod.incident_surfacing, "summarize", _boom)
    board = tmp_path / "WORKBOARD.md"
    board.write_text(
        "# Thomas Workboard\n\nLast updated: 2026-03-18\n\n"
        "## Agent Claims\n\n- none\n\n## Active Tasks\n\n- none\n",
        encoding="utf-8",
    )

    payload = mod.build_startup_payload(
        summary="Answer a repo question",
        paths=[],
        edit_intent=False,
        benchmark_mode=False,
        tracked_work=False,
        multi_agent=False,
        long_running=False,
        workflow_mode="guided",
        workboard_path=board,
        cwd=mod.ROOT,
    )

    assert payload["incident_surfacing"]["ok"] is False
