"""Keep a project's sent-back findings attached to later runs and reject unchanged repairs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from thomas.server import green_handoff, precard, thomas_project
from thomas.server.issue_ledger import record_issue
from thomas.server.routes.autopilot_messages import (
    REPAIR_PREFIX,
    THOMAS_NOTES_END,
    THOMAS_NOTES_START,
    repair_message,
)

log = logging.getLogger(__name__)


def sent_back_rounds(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    """Stored findings in project order, never inferred from a Build turn's text."""
    project = conversation.get("thomas_project")
    rounds = (
        (project.get("inherited_repairs") or []) + (project.get("repairs") or []) if isinstance(project, dict) else []
    )
    return [
        item
        for item in rounds
        if isinstance(item, dict) and item.get("why") == thomas_project.SENT_BACK and str(item.get("detail") or "")
    ]


def _message_rounds(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep every distinct finding once; unchanged-patch details already quote earlier rounds."""
    rounds = sent_back_rounds(conversation)
    return [
        item
        for index, item in enumerate(rounds)
        if not any(str(item["detail"]) in str(later["detail"]) for later in rounds[index + 1 :])
    ]


def findings_notes(rounds: list[dict[str, Any]]) -> str:
    findings = "\n\n".join(
        f"Send-back {item.get('round') or index}, findings in full:\n{item['detail']}"
        for index, item in enumerate(rounds, 1)
    )
    return f"{THOMAS_NOTES_START}\n{findings}\n{THOMAS_NOTES_END}"


def with_findings(message: str, conversation: dict[str, Any], *, review: bool = False) -> str:
    rounds = _message_rounds(conversation)
    if not rounds:
        return message
    rule = (
        "These findings came after your request and win where the two conflict. "
        "A change they asked for is part of the work, never an extra edit to undo. "
        "Judge the work against your request and every finding together."
        if review
        else "These later send-back findings win where they conflict with your request; keep the fixes they ask for."
    )
    # A sent-back repair already carries its own findings; other repair reasons do not.
    if message.startswith(REPAIR_PREFIX):
        project = conversation.get("thomas_project") or {}
        latest = next((r for r in reversed(project.get("repairs") or []) if isinstance(r, dict)), None)
        previous = rounds[:-1] if latest and latest.get("why") == thomas_project.SENT_BACK else rounds
        notes = findings_notes(previous) if previous else ""
        return message + (f"\n\n{rule}\n\n{notes}" if notes else "")
    if review and THOMAS_NOTES_START in message:
        message = message.replace(THOMAS_NOTES_START, f"{rule}\n\n{THOMAS_NOTES_START}", 1)
        return f"{message}\n\n{findings_notes(rounds)}"
    return f"{message}\n\n{rule}\n\n{findings_notes(rounds)}"


def failed_round_message(message: str, conversation: dict[str, Any]) -> str:
    """Carry the full original round after a failed run, without repeating its findings."""
    rounds = _message_rounds(conversation)
    if not rounds:
        return message
    project = conversation.get("thomas_project") or {}
    latest = next((r for r in reversed(project.get("repairs") or []) if isinstance(r, dict)), None)
    if not latest:
        return with_findings(message, conversation)
    from thomas.server.routes.autopilot_goal import goal_text

    original = repair_message(goal_text(conversation.get("turns") or []), latest)
    # A sent-back round already contains its own findings; other reasons need all of them.
    included = rounds[:-1] if latest.get("why") == thomas_project.SENT_BACK else rounds
    earlier = findings_notes(included) if included else ""
    return f"{message}\n\nThe repair round's whole message, including its steps and findings, follows:\n{original}" + (
        f"\n\n{earlier}" if earlier else ""
    )


def review_request(goal: str, conversation: dict[str, Any]) -> str:
    """Give the second look the original request and all later requirements; preserve old prompts unchanged."""
    rounds = _message_rounds(conversation)
    if not rounds:
        return goal
    findings = "\n\n".join(f"Send-back {item.get('round') or i}:\n{item['detail']}" for i, item in enumerate(rounds, 1))
    return (
        f"{goal}\n\nThese findings came after your request and win where they conflict. "
        "Every fix they asked for is part of the work, never an extra edit to undo. "
        "A finding the change does not fix is a requirement it does not meet.\n\n"
        f"{THOMAS_NOTES_START}\n{findings}\n{THOMAS_NOTES_END}"
    )


def _manifest(sid: str) -> Path | None:
    inbox = green_handoff.inbox_dir()
    for directory in (inbox, inbox.parent / "processed", inbox.parent / "withdrawn"):
        candidate = directory / sid / "submission.json"
        if candidate.is_file():
            return candidate
    return None


def reject_unchanged(conversation: dict[str, Any], cid: str, checked: Any) -> None:
    """Before the second look, fail a patch identical to a hand-in returned with findings."""
    for item in sent_back_rounds(conversation):
        sid = str(item.get("sid") or "")
        if not sid:
            continue
        path = _manifest(sid)
        try:
            if path is None:
                raise FileNotFoundError(sid)
            digest = json.loads(path.read_text(encoding="utf-8"))["patch_sha256"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("could not compare repair patch with sent-back hand-in %s: %s", sid, exc)
            continue
        if not isinstance(digest, str) or not digest or digest != checked.patch_sha256:
            continue
        findings = (
            f"This repair round changed nothing in the change sent back for hand-in {sid} "
            f"(sha256 {digest}). The findings it was sent back with, in full:\n{item['detail']}"
        )
        record_issue(
            surface="autopilot",
            kind="repair_changed_nothing",
            message=findings,
            context={"conversation_id": cid, "hand_in": sid},
        )
        raise precard.ChangeFailedCheck(findings)
