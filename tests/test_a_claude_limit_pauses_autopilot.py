"""A Claude plan limit pauses Autopilot until it resets, the same as a ChatGPT one.

You asked that Autopilot "shouldnt stop until it ha a finoisherfd product it deems good failures will happena nd
he must fix them and continue". Since 2026-09-24 the self-fix projects run Build on your Claude plan through the
Claude Code CLI, and a Claude limit read as "claude exited 1" after "You've hit your session limit · resets ...":
Autopilot would have spent its 12 continuations on it again. The CLI lines below are its own (2.1.278): the human
sentences are copied from real Claude Code transcripts. They go through the real translator, the dispatcher, the
runner's terminal event, the runtime's verdict, the conversation store, ``decide()``, ``after_run`` and the park.
Stubbed: only Build's start hook and the clocks.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from thomas.forge.anvil import dispatch_claude_cli, forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.evolve_verdict import _terminal_engine_verdict

GOAL = "Make the Send button blue"
SESSION = "You've hit your session limit · resets 12:20pm (America/Chicago)"
FABLE = "You've reached your Fable 5 limit. Run /usage-credits to continue or switch models with /model."
THROTTLED = "API Error: Server is temporarily limiting requests (not your usage limit) · Rate limited"
CREDITS = "Usage credits are required for this model."


def _cli_lines(text: str, *, resets_at: int | None = None) -> list[str]:
    """What ``claude -p --output-format stream-json`` prints when a request is refused with a 429."""
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": "s"})]
    if resets_at is not None:
        info = {"status": "rejected", "resetsAt": resets_at, "rateLimitType": "five_hour", "overageStatus": "rejected"}
        lines.append(json.dumps({"type": "rate_limit_event", "rate_limit_info": info, "session_id": "s"}))
    message = {"model": "<synthetic>", "role": "assistant", "content": [{"type": "text", "text": text}]}
    lines.append(
        json.dumps({"type": "assistant", "message": message, "error": "rate_limit", "is_api_error_message": True})
    )
    result = {"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429,
              "terminal_reason": "api_error", "result": text, "session_id": "s"}  # fmt: skip
    return [*lines, json.dumps(result, ensure_ascii=False)]


def _conversation(tmp_path: Path) -> tuple[Path, Path, str]:
    catalog, project = tmp_path / "catalog", tmp_path / "project"
    project.mkdir(parents=True)
    (project / "README.md").write_text("readme\n", encoding="utf-8")
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=project, check=True)
    draft = forge_code_store.draft_conversation(title="blue send button")
    forge_code_store.persist_draft_with_user_turn(project, draft, GOAL)
    settings = ForgeCodeSettings.from_payload({"autonomy_level": ap.AUTOPILOT}).capability_report()
    forge_code_projects.bind_conversation(catalog, draft["id"], project, settings=settings)
    return catalog, project, draft["id"]


def _run(project: Path, cid: str, lines: list[str]) -> str:
    """One Build run on the Claude CLI that meets ``lines``: the dispatcher, then the runner's terminal event, then
    the runtime's verdict and reason (evolve_agent_runtime), stored as the run's agent turn."""
    events: list[dict[str, Any]] = []
    result = dispatch_claude_cli.dispatch_via_claude_cli(
        GOAL, cwd=project, definition="x", dry_run=False, claude_bin="claude.exe", emit=events.append,
        runner=lambda cmd, cwd, timeout: (1, "\n".join(lines)), verify=False,
    )  # fmt: skip
    events.append({"fc": "error", "text": result.reason, "is_error": True, "terminal": True})  # forge_code_runner
    transcript = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
    _ok, cause = _terminal_engine_verdict(transcript)
    forge_code_store.append_agent_turn(
        project, cid, model="claude:opus", transcript=transcript, changed_files=[], returncode=1, ok=False,
        noop=False, reason=f"the run crashed before finishing — {cause}", outcome="failed",
    )  # fmt: skip
    return result.reason


def _app(catalog: Path, starts: list[dict[str, Any]]) -> dict[Any, Any]:
    async def start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        starts.append(body)
        root = Path(forge_code_projects.conversation_metadata(catalog, body["conversation_id"])["project_root"])
        forge_code_store.append_user_turn(root, body["conversation_id"], body["message"])  # as the start route does
        return 200, {"ok": True}

    return {APP_PRAXIS_START_CODE_RUN: start, APP_LOCAL_PORT: 8898}


def _when(moment: float) -> str:
    local = datetime.fromtimestamp(moment)
    return f"{local:%A} {local.day} {local:%B} at {local:%H:%M}"


@pytest.mark.asyncio
async def test_a_claude_session_limit_waits_until_its_reset_and_resumes_by_itself(tmp_path: Path) -> None:
    from thomas.server import autopilot_park

    catalog, project, cid = _conversation(tmp_path)
    resets_at = int(time.time()) + 3 * 3600  # the CLI's rate_limit_event, in Unix seconds

    reason = _run(project, cid, _cli_lines(SESSION, resets_at=resets_at))
    decision = ap.decide(ap._load_joined_conversation(project, catalog, cid))

    assert reason.startswith("Claude HTTP 429 usage limit reached.") and SESSION in reason, "a limit, not a crash"
    assert decision.action == "wait", decision
    assert (decision.retry_at, decision.provider) == (resets_at, "Claude")
    paused = f"Paused: your Claude usage limit is reached. It resets {_when(resets_at)}, and Thomas carries on by "
    assert decision.reason == paused + "himself then."
    app = _app(catalog, starts := [])
    assert (await ap.after_run(app, project, catalog, cid)).action == "wait" and starts == []
    assert await autopilot_park.resume_due(app, catalog, now=resets_at - 60) == []
    assert await autopilot_park.resume_due(app, catalog, now=resets_at + 1) == [cid]
    assert len(starts) == 1 and starts[0]["message"].startswith(ap.RESUME_PREFIX)


def _clock_words(at: datetime) -> str:
    """A time the way the CLI prints it: "12:20pm", "8am"."""
    minutes = f":{at.minute:02d}" if at.minute else ""
    return f"{at.hour % 12 or 12}{minutes}{'pm' if at.hour >= 12 else 'am'}"


def _printed(at: datetime) -> tuple[int, bool]:
    """When the CLI's printed time is, in its own zone when this machine can look the zone up; otherwise on this
    machine's clock (the CLI runs here) and an hour later, to be sure it has reset."""
    try:
        return int(at.replace(tzinfo=ZoneInfo("America/Chicago")).timestamp()), True
    except ZoneInfoNotFoundError:
        return int(at.astimezone().timestamp()) + 3600, False


@pytest.mark.parametrize("form", ["session: a bare time, under a day away", "weekly: a date, more than a day away"])
def test_with_no_rate_limit_event_it_waits_until_the_time_the_cli_printed(tmp_path: Path, form: str) -> None:
    now = datetime.now().replace(second=0, microsecond=0)
    if form.startswith("session"):
        at = now + timedelta(hours=3)  # like SESSION
        text = f"You've hit your session limit · resets {_clock_words(at)} (America/Chicago)"
    else:
        at = (now + timedelta(days=2)).replace(hour=8, minute=0)  # like WEEKLY
        text = f"You've hit your weekly limit · resets {at:%b} {at.day}, {_clock_words(at)} (America/Chicago)"
    catalog, project, cid = _conversation(tmp_path)

    _run(project, cid, _cli_lines(text))
    decision = ap.decide(ap._load_joined_conversation(project, catalog, cid))

    retry_at, exact = _printed(at)
    assert decision.action == "wait", decision
    assert (decision.retry_at, decision.provider) == (retry_at, "Claude")
    if exact:
        assert f"It resets {_when(retry_at)}, and Thomas carries on by himself then." in decision.reason
    else:  # never a precise time it did not say
        assert decision.reason == (
            f"Paused: your Claude usage limit is reached. Thomas carries on by himself {_when(retry_at)}, once it "
            "has reset."
        )


def test_a_limit_that_names_no_reset_is_looked_at_again_in_half_an_hour(tmp_path: Path) -> None:
    catalog, project, cid = _conversation(tmp_path)

    _run(project, cid, _cli_lines(FABLE))
    conversation = ap._load_joined_conversation(project, catalog, cid)
    decision = ap.decide(conversation)

    failed_at = datetime.fromisoformat(conversation["turns"][-1]["ts"]).timestamp()
    assert decision.action == "wait", decision
    assert decision.retry_at == pytest.approx(failed_at + 30 * 60) and "did not say when it resets" in decision.reason


@pytest.mark.parametrize("text", [THROTTLED, CREDITS])
def test_a_claude_429_that_is_not_your_plan_limit_is_retried_as_before(tmp_path: Path, text: str) -> None:
    catalog, project, cid = _conversation(tmp_path)

    reason = _run(project, cid, _cli_lines(text))
    conversation = ap._load_joined_conversation(project, catalog, cid)

    assert reason == "claude exited 1"
    assert (
        conversation["turns"][-1]["reason"]
        == f"the run crashed before finishing — Claude HTTP 429 rate limited. {text}"
    )
    assert ap.decide(conversation).action == "continue", "a short-lived throttle is not a pause"
