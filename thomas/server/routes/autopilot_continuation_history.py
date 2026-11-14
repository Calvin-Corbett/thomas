"""Count self-continuations with execution evidence and explain their endings."""

from __future__ import annotations

import json
from typing import Any

from thomas.core.claude_plan import plan_limit_words
from thomas.forge.anvil.forge_code_store import transcript_text
from thomas.forge.anvil.forge_event_stream import is_login_refusal
from thomas.server.routes.autopilot_goal import steers_in
from thomas.server.routes.autopilot_messages import (
    CONTINUATION_PREFIX,
    REPAIR_PREFIX,
    RESTART_MARK,
    RESTART_PREFIX,
    RESUME_PREFIX,
    REVIEW_PREFIX,
    TROUBLE_RESUME_PREFIX,
)


def actually_ran(turn: dict[str, Any]) -> bool:
    """Require work or model output, not merely a subprocess/error receipt.

    The runtime saves agent turns even for configuration errors, missing runner
    binaries, quota refusals and a restart before the engine could start. Neither
    a run id, a model header nor files already dirty at launch proves execution.
    Older turns without evidence are left uncharged rather than guessed to run.
    """
    speech: list[dict[str, Any]] = []
    for line in transcript_text(turn.get("transcript")).splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("fc")
        if kind in {"tool", "tool_result"} and event.get("name"):
            return True
        if kind == "say":
            # Preserve whitespace deltas so provider-error suffixes match exactly.
            # Historical say events also carried arbitrary CLI stderr/banners.
            speech.append(event)
        elif kind in {"reason", "insight"} and str(event.get("text") or "").strip():
            return True
        if kind == "error" and speech:
            # Provider errors can arrive as text before the flagged message.
            # Retract only their matching suffix, not earlier real work.
            text = str(event.get("provider_text") or event.get("text") or "").strip()
            if "(Claude CLI said: " in text and text.endswith(")"):
                text = text.rsplit("(Claude CLI said: ", 1)[1][:-1]
            text_block = event.get("text_block")
            if text_block is not None:
                speech = [piece for piece in speech if piece.get("text_block") != text_block]
            for start in range(len(speech) - 1, -1, -1):
                if not speech[start].get("delta") or text_block is not None:
                    break
                if "".join(str(piece.get("text") or "") for piece in speech[start:]).strip() == text:
                    del speech[start:]
                    break
        if kind == "final" and event.get("ok") is not False and str(event.get("text") or "").strip():
            return True
    # A refusal can be split across process and model-labelled chunks. Test the
    # whole sentence as well as model text, without discarding earlier work.
    groups: list[tuple[str, list[str]]] = []
    previous_delta = False
    for event in speech:
        source = str(event.get("source") or "")
        text = str(event.get("text") or "")
        starts_refusal = plan_limit_words(text) or is_login_refusal(text)
        if not groups or source != groups[-1][0] or starts_refusal or (event.get("delta") and not previous_delta):
            groups.append((source, []))
        groups[-1][1].append(text)
        previous_delta = bool(event.get("delta"))
    for index, (source, pieces) in enumerate(groups):
        tail_groups = [pieces]
        for next_source, next_pieces in groups[index + 1 :]:
            if next_source == source:
                break
            tail_groups.append(next_pieces)
        tail = "".join(piece for group in tail_groups for piece in group).strip()
        if plan_limit_words(tail) or is_login_refusal(tail):
            return False
        text = "".join(pieces).strip()
        if source == "model" and text and not plan_limit_words(text) and not is_login_refusal(text):
            return True
    return False


def ran_continuations(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair each unsteered continuation request with its next recorded run, since the last instruction.

    Queued requests and startup-only receipts do not spend a run. Restarts and
    quota resumes carry the request forward; each execution is charged once by
    run id. Only a new instruction or live steering resets the budget.
    """
    return _recorded_runs(turns, continuations_only=True)


def executed_runs_since_instruction(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Executed runs in the current budget, including the initial instructed run."""
    return _recorded_runs(turns, continuations_only=False)


def _recorded_runs(turns: list[dict[str, Any]], *, continuations_only: bool) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    pending = False
    continuation_context = False
    seen: set[str] = set()
    last_request = ""
    # autopilot_park names the Claude plan explicitly in its quota-resume turn.
    claude_resume_prefix = f"{CONTINUATION_PREFIX}: resuming after the Claude plan's usage limit"
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        if turn.get("role") == "agent":
            run_id = str(turn.get("run_id") or "")
            eligible = pending or not continuations_only or (run_id and run_id in seen)
            prior = next((i for i, run in enumerate(runs) if run_id and run.get("run_id") == run_id), None)
            if eligible:
                if run_id:
                    seen.add(run_id)
                if prior is not None:
                    latest = {**runs[prior], **turn}
                    for field in ("outcome", "reason"):
                        if not str(turn.get(field) or "").strip():
                            latest[field] = runs[prior].get(field)
                    if not actually_ran(turn):
                        latest["transcript"] = runs[prior].get("transcript")
                    runs[prior] = latest
                elif actually_ran(turn):
                    runs.append(turn)
            # Even an unstarted receipt closes this request. A later unrelated
            # agent turn cannot inherit its place in the budget.
            if not run_id or prior is None:
                pending = False
            continue
        if turn.get("role") != "user":
            continue
        text = str(turn.get("text") or "")
        if text.startswith(RESTART_PREFIX):
            # Unwrap the interrupted request. Each resumed run with execution
            # evidence counts; the restart request itself does not.
            original = text
            while text.startswith(RESTART_PREFIX) and RESTART_MARK in text:
                text = text.split(RESTART_MARK, 1)[1]
            new_steering = steers_in(original.partition(RESTART_MARK)[0])
            if new_steering or steers_in(text):
                if text != last_request or new_steering:
                    runs = []
                    seen.clear()
                pending = continuation_context = False
            elif text != original:
                if text.startswith((RESUME_PREFIX, TROUBLE_RESUME_PREFIX, claude_resume_prefix)):
                    pending = continuation_context
                else:
                    pending = continuation_context = text.startswith(
                        (CONTINUATION_PREFIX, REVIEW_PREFIX, REPAIR_PREFIX)
                    )
                    if not pending:
                        runs = []
                        seen.clear()
            else:
                pending = continuation_context
        elif steers_in(text):
            runs = []
            pending = continuation_context = False
            seen.clear()
        elif text.startswith((RESUME_PREFIX, TROUBLE_RESUME_PREFIX, claude_resume_prefix)):
            # A resume after a refused first continuation still belongs to that
            # continuation, even when there are no charged runs yet.
            pending = continuation_context
        elif text.startswith((CONTINUATION_PREFIX, REVIEW_PREFIX, REPAIR_PREFIX)):
            pending = continuation_context = True
        else:
            runs = []
            pending = continuation_context = False
            seen.clear()
        last_request = text.strip()
    return runs


def continuation_history(conversation: dict[str, Any]) -> dict[str, Any]:
    """Read-only explanation for the conversation API and its existing renderer."""
    runs = ran_continuations(conversation.get("turns") or [])
    return {
        "count": len(runs),
        "runs": [
            {
                "run": index,
                "run_id": turn.get("run_id") or "",
                "ts": turn.get("ts") or "",
                "outcome": turn.get("outcome") or "unknown",
                "reason": turn.get("reason") or "no reason recorded",
            }
            for index, turn in enumerate(runs, 1)
        ],
    }


def ending_details(runs: list[dict[str, Any]]) -> str:
    """Show the recorded outcome and reason for each run counted toward the cap."""
    return "; ".join(
        f"{index}. {turn.get('outcome') or 'unknown'}: {turn.get('reason') or 'no reason recorded'}"
        for index, turn in enumerate(runs, 1)
    )
