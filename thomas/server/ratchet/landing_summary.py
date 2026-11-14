"""Describe the proven candidate and any repair-only files for the card."""

from __future__ import annotations

from thomas.server.ratchet.context import Attempt
from thomas.server.ratchet.results import Verdict


def landing_summary(att: Attempt, verdict: Verdict, files: list[str]) -> str:
    """The promoter uses the first line as the commit subject; the rest stays in the submission."""
    cand = att.candidate
    name = cand.ref.removeprefix("refs/").removeprefix("heads/")
    shown = ", ".join(sorted(files)[:20]) + (f" and {len(files) - 20} more" if len(files) > 20 else "")
    lines = [
        f"ratchet: land {name} ({cand.sha[:12]})"[:120],
        "",
        f"Candidate {cand.ref} at {cand.sha}, proven on dev {att.dev_sha}.",
        f"Proof: {verdict.files} test file(s); failing on dev {verdict.base_failing}, with it "
        f"{verdict.with_failing}; {verdict.reason}.",
        f"Files: {shown}",
    ]
    if att.extra:
        lines.append(f"Beyond the candidate's own files, its repair also changed: {', '.join(att.extra[:10])}")
    if att.screen.dropped:
        lines.append("Left out (coordination files): " + ", ".join(att.screen.dropped[:10]))
    return "\n".join(lines)
