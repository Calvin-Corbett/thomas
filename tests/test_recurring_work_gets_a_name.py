"""Recurring work gets a name -- standing incidents never masquerade as
neglect, and the closure gate needs no change to leave them alone.

Pins phase 2 repairs batch 1, Task 1 (recon #10; scripts/crew/brief/
incident_surfacing.py's ``_recurring_cadence``/RECURRING vocabulary;
scripts/forge/gates/problem_closure_gate.py, untouched by design):

  * a ``- recurring: <cadence>`` PROBLEM.md header line routes that
    incident into a new ``RECURRING: N standing`` line -- excluded from
    the ``INCIDENTS: N open without closure`` count (standing work is not
    neglected work) but never hidden: it surfaces regardless of status or
    closure state, including a recurring record that has ALSO resolved on
    a real closure;
  * ``--json`` gains matching ``recurring_count``/``recurring`` keys;
  * the closure gate needs NO change for this: a recurring-header-only
    edit (no status transition) never becomes a resolving candidate for
    ``problem_closure_gate.run_check`` -- proven by running the REAL gate
    over a REAL git repo, not a reimplementation of its scope logic.

Every fixture here lives under ``tmp_path`` -- this suite never reads or
writes ``plans/thomas/problems/`` in the real repo tree.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.crew.brief import incident_surfacing
from scripts.forge.gates import problem_closure_gate


def _write_problem(
    root: Path,
    task_id: str,
    *,
    status: str,
    closures: list[str] | None = None,
    recurring: str | None = None,
) -> Path:
    path = root / "plans" / "thomas" / "problems" / task_id / "PROBLEM.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    closure_block = "".join(f"- closure: {c}\n" for c in (closures or []))
    recurring_line = f"- Recurring: {recurring}\n" if recurring else ""
    path.write_text(
        f"# PROBLEM for {task_id}\n\n"
        f"task_id: `{task_id}`\n\n"
        "- Owner: unassigned\n"
        f"- Status: {status}\n"
        "- Updated At: 2026-01-01T00:00:00+00:00\n"
        "- Scope: thomas\n"
        f"{recurring_line}\n"
        f"{closure_block}"
        "\n## Current Problem\n\ntest incident\n",
        encoding="utf-8",
    )
    return path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def test_a_recurring_incident_is_excluded_from_open_and_shown_in_recurring(tmp_path: Path) -> None:
    """ELECTRON-BUMP-RECURRING's real shape: non-resolved, no closure line,
    but carrying a `- Recurring:` header. Without the marker this would land
    in `open` -- with it, it must be excluded from the open-without-closure
    count and surfaced in its own `recurring` bucket instead, never hidden."""
    _write_problem(
        tmp_path,
        "TASK-RECUR",
        status="up_for_grabs",
        recurring="on every new Electron stable major",
    )

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert [row["task_id"] for row in result["recurring"]] == ["TASK-RECUR"]
    assert result["recurring"][0]["cadence"] == "on every new Electron stable major"

    summary = incident_surfacing.summarize(tmp_path)
    assert summary["count"] == 0
    assert summary["recurring_count"] == 1
    text = incident_surfacing.render_text(summary)
    assert "RECURRING: 1 standing" in text
    assert "TASK-RECUR" in text


def test_a_recurring_incident_that_is_also_resolved_with_a_valid_closure_still_shows_in_recurring(
    tmp_path: Path,
) -> None:
    """The other half of the contract: a recurring record that has ALSO been
    resolved on a real closure (one cycle done, waiting for the next major)
    must still surface in `recurring` -- "never excluded from existence" --
    while staying out of both `open` and `reopen_due`."""
    _write_problem(
        tmp_path,
        "TASK-RECUR-RESOLVED",
        status="resolved",
        closures=["gate:monolith_guard.py"],
        recurring="on every new Electron stable major",
    )

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert result["reopen_due"] == []
    assert [row["task_id"] for row in result["recurring"]] == ["TASK-RECUR-RESOLVED"]


def test_the_cli_json_mode_includes_the_recurring_category(tmp_path: Path, capsys) -> None:
    _write_problem(tmp_path, "TASK-RECUR-JSON", status="up_for_grabs", recurring="cadence text")

    exit_code = incident_surfacing.main(["--repo-root", str(tmp_path), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recurring_count"] == 1
    assert payload["recurring"][0]["task_id"] == "TASK-RECUR-JSON"


def test_a_fenced_recurring_line_is_not_recognized_and_the_record_stays_open(tmp_path: Path) -> None:
    """Final-review fix wave, Important-1 -- the reviewer's exact repro: a
    genuinely open incident whose ONLY `- recurring:` line sits inside a
    fenced ``` block, labelled as documentation/example, must stay `open`
    and must NOT appear in `recurring`. Before the fix this silently
    concealed the incident (open: 0, recurring: 1) -- the dangerous
    direction, per the module's own fence-awareness precedent for closure
    lines."""
    path = tmp_path / "plans" / "thomas" / "problems" / "fenced-recurring-demo" / "PROBLEM.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# PROBLEM for fenced-recurring-demo\n\n"
        "task_id: `fenced-recurring-demo`\n\n"
        "- Owner: unassigned\n"
        "- Status: up_for_grabs\n"
        "- Updated At: 2026-01-01T00:00:00+00:00\n"
        "- Scope: thomas\n\n"
        "## Current Problem\n\nreal open problem, not recurring\n\n"
        "```\n- recurring: example only, not real\n```\n",
        encoding="utf-8",
    )

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert [row["task_id"] for row in result["open"]] == ["fenced-recurring-demo"]
    assert result["recurring"] == []

    summary = incident_surfacing.summarize(tmp_path)
    assert summary["count"] == 1
    assert summary["recurring_count"] == 0


def test_an_unfenced_recurring_line_in_body_prose_is_still_recognized(tmp_path: Path) -> None:
    """Pins the header-bound decision: `_recurring_cadence` is fence-aware
    but deliberately NOT bounded to a "header region", for consistency with
    `_header_status` (its sibling field-reader), which has no such bound
    either. An UNFENCED `- recurring:` line below the header, in body prose,
    is still recognized -- this is the accepted, pre-existing tradeoff
    every header-field reader in this module already carries, not new scope
    creep from the fence fix."""
    path = tmp_path / "plans" / "thomas" / "problems" / "prose-recurring-demo" / "PROBLEM.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# PROBLEM for prose-recurring-demo\n\n"
        "task_id: `prose-recurring-demo`\n\n"
        "- Owner: unassigned\n"
        "- Status: up_for_grabs\n"
        "- Updated At: 2026-01-01T00:00:00+00:00\n"
        "- Scope: thomas\n\n"
        "## Current Problem\n\n"
        "- recurring: stated in body prose, not fenced, not in the header block\n",
        encoding="utf-8",
    )

    result = incident_surfacing.open_incidents_without_closure(tmp_path)

    assert result["open"] == []
    assert [row["task_id"] for row in result["recurring"]] == ["prose-recurring-demo"]
    assert result["recurring"][0]["cadence"] == "stated in body prose, not fenced, not in the header block"


def test_a_recurring_header_edit_does_not_trip_the_closure_gate(tmp_path: Path) -> None:
    """The closure gate needs NO change for recurring vocabulary: adding a
    `- Recurring: ...` header line to an already-open, non-transitioning
    incident must never make problem_closure_gate.run_check treat it as a
    resolving incident. Proven by running the REAL gate over a REAL git
    repo (the same fixture shape test_an_incident_ends_in_a_practice_or_an_
    owned_risk.py uses), not a reimplementation of its scope logic."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", "repo")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")

    task_id = "recur-gate-check"
    path = repo / "plans" / "thomas" / "problems" / task_id / "PROBLEM.md"
    path.parent.mkdir(parents=True)
    body_without_recurring = (
        f"# PROBLEM for {task_id}\n\ntask_id: `{task_id}`\n\n"
        "- Owner: unassigned\n- Status: up_for_grabs\n"
        "- Updated At: 2026-01-01T00:00:00+00:00\n- Scope: thomas\n\n"
        "## Current Problem\n\ntest incident\n"
    )
    path.write_text(body_without_recurring, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "old state")

    # Add ONLY the recurring header -- status stays up_for_grabs, no closure
    # line, no status transition at all.
    body_with_recurring = (
        f"# PROBLEM for {task_id}\n\ntask_id: `{task_id}`\n\n"
        "- Owner: unassigned\n- Status: up_for_grabs\n"
        "- Updated At: 2026-01-01T00:00:00+00:00\n- Scope: thomas\n"
        "- Recurring: on every new Electron stable major\n\n"
        "## Current Problem\n\ntest incident\n"
    )
    path.write_text(body_with_recurring, encoding="utf-8")
    _git(repo, "add", "-A")

    result = problem_closure_gate.run_check(repo)

    assert result["ok"] is True
    assert result["incidents_checked"] == 0
    assert result["violations"] == []
