"""Agent prompt construction and session markdown rendering for evolve mode.

Split out of ``evolve.py`` (2026-07-15) to keep the runtime under the
MONOLITH_CEILING. ``evolve.py`` re-exports these, so existing imports keep
working.
"""

from __future__ import annotations

from typing import Any

from .evolve_charter import EvolveCharter
from .evolve_verification import _normalize_acceptance_checks


def _build_agent_prompt(
    charter: EvolveCharter,
    goal: str,
    *,
    pass_index: int,
    pass_count: int,
    acceptance_checks: list[str] | None = None,
) -> str:
    active_acceptance_checks = _normalize_acceptance_checks(acceptance_checks or charter.acceptance_checks)
    lines = [
        "You are Thomas running inside evolve mode on the green doppelganger mirror of the Thomas repository.",
        "",
        f"Objective: {charter.objective}",
        f"Goal for this pass: {goal or charter.default_goal}",
        f"Pass: {pass_index} of {pass_count}",
        "",
        "Rules:",
        "- Work only inside the current cwd, which is the green mirror of Thomas.",
        "- The green mirror intentionally has no .git metadata. Do not rely on git commands.",
        "- Do not call git.status or git.diff; the blue supervisor computes all deltas after you stop.",
        "- Do not touch runtime/doppelganger, .thomas/evolve, secrets, or external machine state.",
        (
            "- Hard-stop boundary: do not modify policy, guardrail, support, supervisor-owned files, "
            "test infrastructure, or new evolve-loop files. Touching these rejects the whole session before verification."
        ),
        "- Non-Python file changes are human-held until dedicated non-Python verification exists; prefer Python-only deltas unless the goal explicitly requires otherwise.",
        (
            "- Forbidden examples: WORKTREE_RULES.md, AGENTS.md, GUARDRAILS.md, agent_safety.toml, "
            "docs/AGENT_FILE_EDITING_RULES.md, tests/*, conftest.py, pytest.ini, thomas/_architecture.py, "
            "new thomas/forge/anvil/*.py files, and supervisor-owned evolve files."
        ),
        "- Existing non-supervisor evolve-loop files may be changed for explicit evolve-loop goals; blue supervisor still requires blast-radius tests.",
        "- If a useful change seems to require one of those files, stop and report the boundary instead.",
        "- If verification fails because of environment limits or missing metadata, report that honestly instead of editing the guard.",
        "- Prefer concrete code improvements over commentary-only work.",
        "- Use `fs.search` or `code.search` to locate target symbols in large files, then read a small `fs.read_file` start_line/end_line range before editing.",
        "- To make an edit, use `diff.create` for targeted patches or `fs.write_file` for full-file rewrites; reading files is only preparation.",
        "- Shell/process tools are disabled in self-development. Do not use shell commands to edit files; do not call `shell.exec`.",
        "- A successful pass must leave at least one eligible file diff. Do not claim success after read-only work.",
        "- If no safe eligible change exists, end with `NO_ELIGIBLE_CHANGE: <reason>` and do not call it done.",
        "- Pick the smallest useful change, edit it, run the narrowest relevant test, then stop.",
        "- Keep this pass SMALL and focused: a handful of related edits, not an exhaustive sweep. The loop runs many passes, so for a large goal (e.g. dozens of call sites) fix only a few this pass and stop -- finishing cleanly and promoting beats timing out with nothing done.",
        "- Run targeted verification yourself before you stop.",
        "- End with a concise summary of files changed and verification run.",
        "",
        "Principles:",
    ]
    lines.extend(f"- {item}" for item in charter.principles)
    if active_acceptance_checks:
        lines.append("")
        lines.append("Acceptance checks the blue supervisor will run:")
        lines.extend(f"- {check}" for check in active_acceptance_checks)
    if charter.verify_commands:
        lines.append("")
        lines.append("Post-run verification ladder:")
        lines.extend(f"- {cmd}" for cmd in charter.verify_commands)
    return "\n".join(lines).strip()


def _build_no_change_retry_goal(goal: str) -> str:
    return (
        "The previous evolve attempt exited successfully but produced no eligible file diff. "
        "Retry once with a write-or-refuse approach: use at most one targeted `code.search` call to locate "
        "the symbol or file slice, then at most one bounded `fs.read_file` call, then your next substantive "
        "tool call must be `diff.create` or `fs.write_file` against an eligible path. "
        "This retry instruction overrides the general search guidance: do not call `fs.search`, `git.status`, "
        "`shell.exec`, or any inspection tool except the single optional `code.search` call and the single "
        "optional bounded `fs.read_file` call. "
        "When calling `diff.create`, copy `old_str` exactly from the `fs.read_file` output; do not infer code "
        "syntax from the original goal text. "
        "`shell.exec` is unavailable; if `diff.create` fails, immediately use `fs.write_file` with the complete "
        "corrected file content, or return `NO_ELIGIBLE_CHANGE: <specific reason>`. "
        "Only run verification after a write tool succeeds. "
        "Make exactly one safe allowed diff for the original goal, run the narrowest relevant verification, "
        "and stop. If no safe eligible diff exists, return "
        "`NO_ELIGIBLE_CHANGE: <specific reason>` without claiming success. Original goal: "
        f"{goal}"
    )


def _render_session_markdown(session: dict[str, Any]) -> str:
    lines = [
        f"# Evolve Session {session['session_id']}",
        "",
        f"- Status: `{session['status']}`",
        f"- Goal: {session['goal']}",
        f"- Changed files: {session['delta']['changed_count']}",
        f"- Promotable: `{str(session['promotable']).lower()}`",
        f"- Promoted: `{str(session['promoted']).lower()}`",
    ]
    if session.get("policy_violations"):
        lines.append(f"- Policy violations: {len(session['policy_violations'])}")
    lines.extend(
        [
            "",
            "## Verification",
        ]
    )
    if session.get("verification"):
        for item in session["verification"]:
            lines.append(f"- `{item['command']}` -> `{item['returncode']}`")
    else:
        lines.append("- No verification commands recorded.")
    if session.get("policy_violations"):
        lines.append("")
        lines.append("## Policy Violations")
        lines.extend(f"- `{rel}`" for rel in session["policy_violations"])
    lines.append("")
    lines.append("## Files")
    if session["delta"]["changed_files"]:
        lines.extend(f"- `{rel}`" for rel in session["delta"]["changed_files"])
    else:
        lines.append("- No tracked file changes.")
    return "\n".join(lines).strip() + "\n"
