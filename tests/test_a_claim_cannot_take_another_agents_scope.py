"""A claim is ownership, so taking one from another agent has to be deliberate.

On 2026-09-02 the phase 2 overlay scope moved from one agent to another and the
work was committed under the new owner while the previous owner was still
working in it. Nothing in the tooling refused: `claim` only ever looked for the
CALLING agent's own row, so a scope another agent held could be claimed without
a word. The board gate catches two overlapping rows afterwards, which is too
late to stop the edit and says nothing about who took what.

Claiming into another agent's scope is now refused by name. It stays possible -
an agent really does have to take over sometimes - but only on purpose, with a
reason, and it lands in the override audit log.
"""

from __future__ import annotations

import json
from pathlib import Path

import scripts.crew.workboard.claim as mod

HELD_SCOPE = "thomas/server/overlay,tests/web_node"
HELD = f"- agent=other-agent; name=Other; role=solo; parent=none; scope={HELD_SCOPE}; task=PHASE-2"
ACTIVE = "- task_id=PHASE-2; agent=other-agent; scope=thomas/server/overlay,tests/web_node; summary=overlay; status=active"


def _write_workboard(tmp_path: Path, claims_block: str, active_tasks_block: str) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\n"
            "## Current Priorities\n\n"
            "- Placeholder\n\n"
            "## Agent Claims (Active)\n\n"
            "Use this section to announce active ownership and prevent conflicting edits.\n"
            "Claim format:\n"
            "`- \\`agent=<id>; name=<callsign>; role=<solo|parent|worker>; parent=<id|none>; scope=<path[,path...]>; task=<short text>\\``\n\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; agent=<id>; scope=<path[,path...]>; summary=<short text>; status=<active|blocked>\\``\n\n"
            f"{active_tasks_block}\n\n"
            "## Issues / Blockers\n\n"
            "Issue format:\n"
            "`- \\`issue_id=<id>; task_id=<task_id>; reporter=<id>; owner=<id|unassigned>; state=<open|triaged|resolved>; summary=<short text>\\``\n\n"
            "- none\n\n"
            "## Up For Grabs\n\n"
            "Task format:\n"
            "`- \\`task_id=<id>; scope=<path[,path...]>; summary=<short text>; reported_by=<id>\\``\n\n"
            "- none\n\n"
            "## Supporting Docs (Not Plan Sources)\n\n"
            "- docs/PROJECT_SCOPE.md\n"
        ),
        encoding="utf-8",
    )
    return path


def _claim(workboard: Path, scope: str, *extra: str) -> int:
    return mod.run(["--workboard", str(workboard), "--claim", "--agent", "taker",
                    "--scope", scope, "--task", "TAKEOVER", *extra])


def test_claiming_into_another_agents_scope_is_refused_by_name(tmp_path: Path, capsys) -> None:
    workboard = _write_workboard(tmp_path, HELD, ACTIVE)
    before = workboard.read_text(encoding="utf-8")

    assert _claim(workboard, "thomas/server/overlay/manifest.py") == 1
    out = capsys.readouterr().out
    assert "other-agent" in out, "the refusal names who holds it"
    assert "thomas/server/overlay" in out, "and which of their paths it collides with"
    assert workboard.read_text(encoding="utf-8") == before, "a refused claim changes nothing"

    # The other direction too: a scope that contains what they hold.
    assert _claim(workboard, "tests") == 1
    assert "other-agent" in capsys.readouterr().out
    assert workboard.read_text(encoding="utf-8") == before


def test_a_scope_nobody_else_holds_is_claimed_as_before(tmp_path: Path) -> None:
    workboard = _write_workboard(tmp_path, HELD, ACTIVE)
    assert _claim(workboard, "thomas/server/routes/ui_overlay_routes.py") == 0
    text = workboard.read_text(encoding="utf-8")
    assert "agent=taker" in text and "agent=other-agent" in text


def test_a_takeover_is_possible_on_purpose_with_a_reason_and_an_audit_line(tmp_path: Path, monkeypatch, capsys) -> None:
    workboard = _write_workboard(tmp_path, HELD, ACTIVE)
    audit = tmp_path / "claim_overrides.jsonl"
    monkeypatch.setattr(mod, "CLAIM_OVERRIDE_AUDIT_LOG", audit, raising=False)

    assert _claim(workboard, "thomas/server/overlay", "--allow-scope-takeover") == 1
    assert "takeover-reason" in capsys.readouterr().out, "a takeover without a reason is still refused"

    # Ask for exactly what the other agent holds, not a slice of it. Taking part
    # of a claim leaves a remainder nobody has said who owns, so the request a
    # handover should model is the whole claim changing hands. This test used to
    # ask for one path out of the two and relied on the remainder being implicit.
    assert _claim(workboard, HELD_SCOPE, "--allow-scope-takeover",
                  "--takeover-reason", "other-agent handed the overlay work over on the board") == 0
    text = workboard.read_text(encoding="utf-8")
    assert "agent=taker" in text
    events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]
    taken = [e for e in events if e.get("takeover_from")]
    assert taken and taken[-1]["takeover_from"] == ["other-agent"]
    assert "handed the overlay work over" in taken[-1]["reason"]
