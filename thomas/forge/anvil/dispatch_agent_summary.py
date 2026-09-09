"""The one-line acceptance summary a Build pass writes to its transcript.

Split out of ``dispatch_agent_loop`` (which sits at the monolith guard) on
2026-09-06; the functions are unchanged. What the contract found, what the
judge did, and what the judge's checks came to, on one line a reader can act on.
"""

from __future__ import annotations

from typing import Any


def _judge_checks_summary(checks_run: Any) -> str:
    """What the judge's checks came to: shell checks that ran (with exit codes),
    ones its gate denied (with the reason), and its playtest. Generation 9's line
    said "unchecked" while the judge's scan had been denied and its playtest had
    failed on a key name; a reader could not tell from the transcript."""
    if not isinstance(checks_run, list) or not checks_run:
        return ""
    ran: list[str] = []
    denied: list[str] = []
    plays: list[str] = []
    for row in checks_run:
        if not isinstance(row, dict):
            continue
        if row.get("playtest"):
            verdict = "ran" if row.get("ok") else f"FAILED ({str(row.get('result') or '')[-160:].strip()})"
            plays.append(f"playtest of {row.get('playtest')} {verdict}")
        elif row.get("skipped"):
            reason = str(row.get("skipped") or "").removeprefix("denied:").strip()
            denied.append(f"{str(row.get('cmd') or '')[:80]}: {reason}")
        else:
            ran.append(f"{str(row.get('cmd') or '')[:80]} -> exit {row.get('exit')}")
    parts: list[str] = []
    if ran or denied:
        shell = [f"{len(ran)} shell ran ({', '.join(ran)})"] if ran else []
        shell += [f"{len(denied)} denied ({', '.join(denied)})"] if denied else []
        parts.append("checks: " + ", ".join(shell))
    parts.extend(plays)
    return "; ".join(parts)


def _acceptance_summary(acceptance: dict[str, Any] | None) -> str:
    """One line for the transcript: what the contract found at the end of a pass."""
    if not isinstance(acceptance, dict) or not acceptance.get("active"):
        return ""
    verdict = acceptance.get("verdict")
    if not isinstance(verdict, dict):
        error = str(acceptance.get("error") or "").strip()
        return f"acceptance contract could not be settled: {error}" if error else ""
    unmet = [str(x) for x in verdict.get("unmet") or []]
    unchecked = [str(x) for x in verdict.get("unchecked") or []]
    if verdict.get("met") and not unchecked:
        line = "acceptance contract met: every item checked and satisfied"
    elif verdict.get("met"):
        line = f"acceptance contract met on checked items; {len(unchecked)} unchecked: {', '.join(unchecked)}"
    else:
        line = f"acceptance contract not met: {', '.join(unmet)} unmet" + (
            f"; {len(unchecked)} unchecked" if unchecked else ""
        )
    # What the judge did is part of the record: an unchecked requirement reads
    # very differently when the judge never ran, errored, or declined to rule.
    judge = acceptance.get("evaluator")
    if isinstance(judge, dict):
        if not judge.get("available"):
            line += f" (judge unavailable: {str(judge.get('error') or 'no error given')[:160]})"
        else:
            findings = [str(f) for f in judge.get("findings") or [] if str(f).strip()]
            line += f" (judge: {int(judge.get('calls') or 0)} call(s)"
            if findings:
                line += "; findings: " + " | ".join(f[:160] for f in findings[:4])
            checks = _judge_checks_summary(judge.get("checks_run"))
            if checks:
                line += "; " + checks
            line += ")"
    elif unchecked:
        line += " (no judge ran at this level)"
    return line

__all__ = ["_acceptance_summary", "_judge_checks_summary"]
