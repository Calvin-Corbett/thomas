"""A separate evaluator decides "done" at xhigh and max.

The worker grades its own work generously; a second call with a different job
does not. The evaluator sees the task, the contract with the machine verdicts
already filled in, and the reply. It may ask for checks to be RUN in the
workspace (up to a small budget) and gets the results back before its final
verdict. It must name every item it could not verify - "unchecked" is a valid
verdict, "met" without evidence is not.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import httpx

from thomas.core.acceptance_contract import ContractItem, Runner, default_runner
from thomas.core.llm import LLMError
from thomas.core.structured_output import extract_json
from thomas.tools.web_playtest import WebPlaytestTool, playtest_available, recent_reports

log = logging.getLogger(__name__)

# What a model call, its JSON reply and a requested shell check can raise.
_EVALUATOR_ERRORS = (
    LLMError,
    httpx.HTTPError,
    TimeoutError,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    RuntimeError,
    subprocess.SubprocessError,
)

# A word is a command only where a command starts: the head of the line or the
# first token after a pipe or a chain. Live, the judge's honest check for "never
# loads from the internet" (a search of the sources for fetch, curl, wget, http)
# was refused for naming the words, and the goal went unchecked.
_DENIED_HEADS = {
    "rm",
    "sudo",
    "curl",
    "wget",
    "mkfs",
    "dd",
    "chmod",
    "chown",
    "kill",
    "shutdown",
    "reboot",
    "del",
    "rmdir",
}
_SEGMENT_SPLIT_RE = re.compile(r"\|\||&&|[|;&]")
_QUOTED_RE = re.compile(r"\"[^\"]*\"|'[^']*'")
_STDERR_REDIRECT_RE = re.compile(r"\b2>\s*(?:nul|/dev/null)\b", re.IGNORECASE)


def command_denied(cmd: str) -> str | None:
    """Why the judge may not run ``cmd``, or None when it may."""

    unquoted = _QUOTED_RE.sub(" ", str(cmd or ""))
    if ">" in _STDERR_REDIRECT_RE.sub(" ", unquoted):
        return "writes a file (redirect)"
    for segment in _SEGMENT_SPLIT_RE.split(unquoted):
        words = segment.split()
        if not words:
            continue
        head = words[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        if head.endswith(".exe"):
            head = head[:-4]
        if head in _DENIED_HEADS:
            return f"runs {head}"
        if head == "git" and len(words) > 1 and words[1].lower() == "push":
            return "runs git push"
    return None


JUDGE_SYSTEM = (
    "You are the acceptance evaluator for another agent's finished work. You did not do the work and you "
    "do not trust its reply. Your job: for every contract item decide met, unmet, or unchecked, using only "
    "evidence - the machine verdicts given to you, results of checks you asked to run, or facts in the reply "
    "that a check confirmed. A claim in the reply is not evidence; the reply may be wrong or misleading and "
    "grading is strict and automated. Be conservative: when a check could settle an item, ask for it "
    "(read a file, run the program on an edge input, run it twice for determinism) rather than guessing; an "
    "item the reply claims but a check contradicts is unmet with a short, actionable gap. Say unchecked "
    "only when no check could settle it; never say met without evidence. The work you grade is what THIS "
    "run did: the files its own tool calls wrote or the delta it reported. A checkout may hold other "
    "uncommitted changes from other work; those are not this run's and must not count for or against it. "
    "Answer with one JSON object and nothing else."
)
JUDGE_ADVERSARIAL = (
    " Be adversarial: assume the work has a defect the worker did not notice. Ask for checks that would "
    "expose it - edge inputs, a second run for determinism, a field in the data the code never reads."
)
_SCHEMA_HINT = (
    'JSON shape: {"item_verdicts": {"<item_id>": "met"|"unmet"|"unchecked", ...}, '
    '"item_reasons": {"<item_id>": "<one sentence: the evidence behind that verdict, or what was missing>", ...}, '
    '"checks": [{"cmd": "<shell command to run in the workspace>", "why": "<what it proves>"}], '
    '"findings": ["<a defect or gap you found>", ...]}. Omit "checks" when you need none; give a reason for '
    "every unmet or unchecked item."
)
MAX_PLAYTESTS = 3  # nine features in one contract cannot be settled by one playtest

_PLAYTEST_HINT = (
    ' The object may also carry "playtests": [{"page": "<html file in the workspace>", '
    '"steps": [{"click": "..."}, {"hold": "w", "seconds": 10}, {"observe": "#hud"}, ...], '
    '"why": "<what it proves>"}] (up to three are run, in order).'
)


@dataclass
class EvaluatorResult:
    available: bool
    items: list[ContractItem]
    findings: list[str] = field(default_factory=list)
    checks_run: list[dict[str, Any]] = field(default_factory=list)
    calls: int = 0
    error: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "findings": list(self.findings),
            "checks_run": list(self.checks_run),
            "calls": self.calls,
            "error": self.error,
        }


def _session_index_line(report: str) -> str:
    lines = [ln.strip() for ln in str(report or "").splitlines() if ln.strip()]
    steps = [ln for ln in lines[1:] if ln[:1].isdigit()]
    kinds = " > ".join(ln.split(" ", 2)[1] for ln in steps if len(ln.split(" ", 2)) > 1)[:160]
    last = next((ln for ln in reversed(steps) if "observe" in ln or "eval" in ln), steps[-1] if steps else "")
    return f"- {len(steps)} steps ({kinds}); last: {last[:300]}"


def _contract_table(items: Sequence[ContractItem]) -> str:
    rows = []
    for it in items:
        state = ("met" if it.satisfied else "unmet") if it.checked else "unchecked"
        rows.append(f"- {it.item_id} [{state}] {it.description}" + (f" (evidence: {it.detail})" if it.detail else ""))
    return "\n".join(rows)


def _parse(text: Any) -> dict[str, Any]:
    data, _err = extract_json(str(text or ""))
    return data if isinstance(data, dict) else {}


def _apply_verdicts(
    items: Sequence[ContractItem], verdicts: dict[str, Any], reasons: dict[str, Any] | None = None
) -> list[ContractItem]:
    # The reason rides with the verdict: a hold that says only "evaluator: unmet"
    # cannot be acted on or argued with (the record-aware proof run was held to
    # "do not replay" with no word on what the judge thought it saw).
    out: list[ContractItem] = []
    for it in items:
        item = ContractItem.from_dict(it.to_dict())
        verdict = str(verdicts.get(item.item_id) or "").strip().lower()
        reason = str((reasons or {}).get(item.item_id) or "").strip()[:300]
        because = f" - {reason}" if reason else ""
        if item.machine and item.checked:
            if verdict == "unmet" and item.satisfied:  # the evaluator may overturn a pass, never a fail
                item.satisfied, item.detail = False, "evaluator: " + (item.detail or "unmet") + because
        elif verdict in {"met", "unmet"}:
            item.checked, item.satisfied = True, verdict == "met"
            item.detail = f"evaluator: {verdict}{because}"
        elif verdict == "unchecked" and reason:
            item.detail = f"evaluator: unchecked{because}"
        out.append(item)
    return out


async def evaluate_with_model(
    llm: Any,
    *,
    task_text: str,
    response_text: str,
    items: Sequence[ContractItem],
    workspace: str | Path,
    run_checks: bool,
    adversarial: bool = False,
    runner: Runner | None = None,
    max_checks: int = 4,
    check_timeout: float = 120.0,
    tool_events: Sequence[dict[str, Any]] | None = None,
) -> EvaluatorResult:
    """One judge call; a second only when it asked for checks and checks may run.

    ``tool_events`` are the worker's recorded tool calls; the last playtest
    sessions among them are quoted to the judge verbatim. A browser's report is
    the tool's output, not the worker's claim, and the judge that only saw the
    worker's prose said "no independent web.playtest was run" while fourteen
    sessions sat in the record.
    """

    chat = getattr(llm, "chat", None)
    if not callable(chat):
        return EvaluatorResult(available=False, items=list(items), error="llm has no chat()")
    run = runner or default_runner
    ws = Path(workspace)
    system = JUDGE_SYSTEM + (JUDGE_ADVERSARIAL if adversarial else "")
    # A shell cannot press START. When the work is a page, the judge may also
    # play it once, through the same session the worker has, and rule on what
    # the browser showed rather than on the worker's account of it.
    can_play = bool(run_checks) and playtest_available()
    # The judge writes the checks; it has to know the machine. Live: two Unix
    # commands on Windows, both failed, and the one requirement stayed unchecked.
    check_offer = (
        f"You may request up to {max_checks} shell checks to run in the workspace before your final verdict. "
        f"They run with the default shell on {platform.system()} "
        f"({'cmd.exe syntax, NOT PowerShell: use dir, type, findstr; no grep, cat, ls, sed, Get-Content or Select-String' if os.name == 'nt' else 'POSIX sh syntax'}). "
    )
    if can_play:
        check_offer += (
            "You may also request up to THREE playtests of an HTML page in the workspace in a real headless browser "
            "(one per feature you need to see, in the same reply): "
            "steps are click (button text or CSS selector), press, hold (a key or keys for seconds), type, wait, "
            "observe (an element's text), eval, screenshot; the result reports what each step saw, page errors "
            "and how much of each canvas is painted. A shell check cannot press a key or read a HUD: when an "
            "item is about what a page or game does, the playtest is the only check that settles it. For such "
            "an item you MUST include one playtest in your first reply instead of a shell check or an "
            "'unchecked' verdict; leaving it unchecked when a playtest could have settled it is a wrong answer. "
        )
    recorded = [
        str(e.get("output_preview") or "")
        for e in (tool_events or [])
        if isinstance(e, dict)
        and str(e.get("name") or "") == "web.playtest"
        and str(e.get("output_preview") or "").strip()
    ][-3:]
    # The saved session reports are the full text; the loop's tool preview is
    # cut at 2000 characters, and a race's results come after that.
    saved = recent_reports(ws, limit=20) if recorded else []
    earlier: list[str] = []
    if saved:
        recorded, earlier = saved[-3:], saved[:-3]
    recorded_block = (
        "PLAYTEST SESSIONS RECORDED DURING THE WORK (verbatim browser tool output, not the worker's words; "
        "this is evidence you may rule on):\n" + "\n---\n".join(r[-6000:] for r in recorded) + "\n\n"
        if recorded
        else ""
    )
    if earlier:
        # Nine features across a dozen sessions: the newest three in full, the
        # rest one line each, so "play each feature" can be judged on every play.
        recorded_block += (
            "EARLIER SESSIONS (one line each: the steps that ran and the last thing seen):\n"
            + "\n".join(_session_index_line(r) for r in earlier)
            + "\n\n"
        )
    # A goal item brings the goals file: "do not close the goals" is checked by
    # reading it, and nothing else shows the judge whether they stand.
    goals_block = ""
    if any(str(it.item_id).startswith("goal:") or str(it.source) == "goal" for it in items):
        try:
            goals_text = (ws / ".thomas" / "goals.json").read_text(encoding="utf-8")
        except OSError:
            goals_text = "(no goals file)"
        goals_block = (
            f"GOALS FILE (.thomas/goals.json at verdict time; a standing goal is done: false):\n{goals_text[:6000]}\n\n"
        )
    user = (
        f"TASK:\n{str(task_text or '')[:12000]}\n\nCONTRACT (machine verdicts already applied):\n{_contract_table(items)}\n\n"
        f"WORKER REPLY:\n{str(response_text or '')[:8000]}\n\n"
        + recorded_block
        + goals_block
        + (check_offer if run_checks else "")
        + _SCHEMA_HINT
        + (_PLAYTEST_HINT if can_play else "")
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    result = EvaluatorResult(available=True, items=list(items))
    try:
        reply = await chat(messages)
        result.calls += 1
        data = _parse(reply.get("text") if isinstance(reply, dict) else reply)
        # Up to two check rounds: shell checks and playtests first; then, if the
        # judge asks to PLAY after seeing its shell results (the proof run's
        # judge wrote "the required browser check was not performed" into its
        # final verdict because the second reply had been final), one more.
        played_any = False
        for round_no in (1, 2):
            checks = [c for c in (data.get("checks") or []) if isinstance(c, dict) and str(c.get("cmd") or "").strip()]
            playtests = (
                [p for p in (data.get("playtests") or []) if isinstance(p, dict) and str(p.get("page") or "").strip()]
                if can_play
                else []
            )
            if round_no == 2:
                checks = []  # the second round is for the browser only
                if played_any or not playtests:
                    break
            if not run_checks or not (checks or playtests):
                break
            for play in playtests[:MAX_PLAYTESTS]:
                played_any = True
                steps = play.get("steps") if isinstance(play.get("steps"), list) else []
                played = await WebPlaytestTool(ws).execute(
                    {"page": str(play.get("page")), "steps": steps, "viewport": play.get("viewport") or {}}
                )
                result.checks_run.append(
                    {
                        "playtest": str(play.get("page")),
                        "steps": len(steps),
                        "why": str(play.get("why") or ""),
                        "ok": bool(played.ok),
                        "result": str(played.data if played.ok else played.error or "")[-3000:],
                    }
                )
            for check in checks[:max_checks]:
                cmd = str(check.get("cmd") or "").strip()
                why_denied = command_denied(cmd)
                if why_denied:
                    result.checks_run.append({"cmd": cmd, "skipped": f"denied: {why_denied}"})
                    continue
                code, tail = run(cmd, ws, check_timeout)
                # 800 characters cut a loop over eight receipts to its last one,
                # and the judge called the other seven "not inspectable".
                result.checks_run.append(
                    {"cmd": cmd, "why": str(check.get("why") or ""), "exit": code, "tail": tail[-3000:]}
                )
            closing = (
                "\n\nNow give your final verdict. No more shell checks; you may still request playtests once. "
                if round_no == 1 and not played_any and can_play
                else "\n\nNow give your final verdict. No more checks. "
            )
            messages.append({"role": "assistant", "content": json.dumps(data)})
            messages.append(
                {
                    "role": "user",
                    "content": "CHECK RESULTS:\n"
                    + json.dumps(result.checks_run, indent=1)[:24000]
                    + closing
                    + _SCHEMA_HINT,
                }
            )
            reply = await chat(messages)
            result.calls += 1
            data = _parse(reply.get("text") if isinstance(reply, dict) else reply)
        verdicts = data.get("item_verdicts") if isinstance(data.get("item_verdicts"), dict) else {}
        reasons = data.get("item_reasons") if isinstance(data.get("item_reasons"), dict) else {}
        result.items = _apply_verdicts(items, verdicts, reasons)
        result.findings = [str(f) for f in (data.get("findings") or []) if str(f).strip()][:20]
        if not verdicts:
            # A reply with no verdicts is a judge that did not rule (a refusal, or
            # output that was not the JSON asked for); it must not read as
            # "unchecked everything" with nothing to show for it.
            raw = str((reply.get("text") if isinstance(reply, dict) else reply) or "").strip()
            result.error = "judge reply carried no verdicts"
            result.findings.append(f"judge said: {raw[:200]}" if raw else "judge said nothing")
    except _EVALUATOR_ERRORS as exc:  # an evaluator outage must not fake a verdict either way
        log.warning("acceptance evaluator unavailable: %s", exc)
        return EvaluatorResult(
            available=False, items=list(items), calls=result.calls, error=f"{type(exc).__name__}: {exc}"
        )
    return result


__all__ = ["EvaluatorResult", "command_denied", "evaluate_with_model", "JUDGE_SYSTEM"]
