"""Claude CLI headless dispatch — runs ``claude -p`` as a streaming subprocess."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bridge_config import emergency_stop_active, emergency_stop_path
from .bridge_prompts import compose_headless_prompt
from .build_verify import _verify_and_iterate
from .forge_event_stream import (
    CLAUDE_CLI_LOGIN_GUIDANCE,
    FORGE_EVENT_KEY,
    ClaudeStreamTranslator,
    _default_emit,
    _stream_cli,
    is_claude_cli_login_error,
)

# Safe default toolset for a dispatched headless build: edit files only — NO shell,
# git, or network. The dispatched agent can change code; it cannot run commands or
# touch the network. The human watcher reviews the resulting diff and runs the tests.
SAFE_CLI_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "MultiEdit", "NotebookEdit")

# Claude's own tool vocabulary, which is not Thomas's. Used to tell a run that
# only looked from one that tried to change something: a request to inspect and
# explain must read files to answer, and reading is not a failed edit. Anything
# not listed is assumed capable of writing, so an unrecognised tool stays strict.
_CLI_READ_ONLY_TOOLS = frozenset(
    {"read", "glob", "grep", "notebookread", "todoread", "websearch", "webfetch", "ls"}
)


def _is_read_only_cli_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip().casefold() in _CLI_READ_ONLY_TOOLS


@dataclass
class CliDispatchResult:
    ok: bool
    reason: str
    prompt: str
    returncode: int = 0
    changed_files: list[str] = field(default_factory=list)
    stdout_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "returncode": self.returncode,
            "changed_files": self.changed_files,
            "prompt_chars": len(self.prompt),
        }


def _is_conversational_reply(text: str) -> bool:
    """Distinguish a real reply from a bare, unproved completion claim."""

    normalized = str(text or "").strip().lower().rstrip(".!?")
    if not normalized:
        return False
    if normalized in {"done", "finished", "complete", "completed", "built", "fixed", "updated", "implemented"}:
        return False
    return True


def _is_action_refusal(text: str) -> bool:
    """Recognize an explicit inability report so it cannot masquerade as success."""

    normalized = " ".join(str(text or "").lower().split())
    inability = any(marker in normalized for marker in ("i can't", "i cannot", "i couldn’t", "i couldn't", "unable to"))
    blocker = any(
        marker in normalized
        for marker in (
            "tool isn't available",
            "tool is not available",
            "tool unavailable",
            "tool isn't registered",
            "tool is not registered",
            "no file tool",
            "no write tool",
            "don't have access",
            "do not have access",
            "required file tool",
            # Hallucinated "your tools aren't set up" refusals. The file tools
            # (Read/Edit/Write/Glob/Grep) are ALWAYS registered when the model
            # runs, so these claims are false — detect them so the run is scored
            # a refusal (ok=False -> retry) instead of a silent "I can't, go
            # re-enable something" bounce. (Live: an FPS fix bounced this way.)
            "aren't exposed",
            "isn't exposed",
            "are not exposed",
            "is not exposed",
            "tools aren't available",
            "tools are not available",
            "re-enable the workspace",
            "re-enable workspace",
            "workspace tools",
        )
    )
    return inability and blocker


def dispatch_via_claude_cli(
    goal: str,
    *,
    cwd: str | Path,
    definition: str = "",
    plan: str = "",
    branch_only: bool = True,
    allowed_tools: tuple[str, ...] = SAFE_CLI_TOOLS,
    model: str = "sonnet",
    timeout: int = 300,
    dry_run: bool = True,
    runner: Any = None,
    claude_bin: str | None = None,
    emit: Callable[[dict[str, Any]], None] | None = None,
    verify: bool = True,
    verifier: Any = None,
    max_fix_iters: int = 2,
    history: Any = None,
    file_access: str = "project",
    guardrails: str = "guarded",
    autonomy_level: int = 3,
) -> CliDispatchResult:
    """Dispatch a build task to Claude Code HEADLESSLY (``claude -p``) — the safe,
    observable bridge that needs no GUI/PC control.

    This is still a real autonomous build, so it is bounded: a restricted tool
    allowlist (edit files only, no shell/git/network), a working directory, and a
    timeout. ``dry_run`` (the default) returns the prompt WITHOUT running anything.

    It is a reason→edit→verify LOOP, not a one-shot edit: after the agent's edit
    pass, the ENGINE (``verify=True``) runs a REAL verification subprocess over the
    files THIS run changed (byte-compile + import, or pytest for a changed test)
    and, if it fails, feeds the failure back for up to ``max_fix_iters`` more edit
    passes, re-verifying each time. The pass/fail shown is the genuine subprocess
    exit code — never fabricated. ``verifier`` is injectable for tests.

    Streaming: the live path runs ``claude -p --output-format stream-json
    --verbose`` and reads the child's stdout line-by-line, translating each event
    into a forge event and ``emit``-ing it the instant it arrives.

    ``runner`` is injectable for tests: a callable (cmd:list, cwd, timeout) ->
    (returncode:int, stdout:str). When provided it takes the buffered path.
    """
    import shutil

    prompt = compose_headless_prompt(
        goal,
        definition=definition,
        plan=plan,
        history=history,
        file_access=file_access,
        guardrails=guardrails,
        autonomy_level=autonomy_level,
    )
    if dry_run:
        return CliDispatchResult(False, "dry-run (claude not invoked)", prompt)

    # The kill switch guards EVERY live dispatch path, not just the GUI one.
    if emergency_stop_active():
        return CliDispatchResult(False, f"refused: emergency stop active ({emergency_stop_path()})", prompt)

    claude = claude_bin or shutil.which("claude") or shutil.which("claude.cmd")
    if not claude:
        return CliDispatchResult(False, "refused: claude CLI not found on PATH", prompt)

    emit_sink = emit or _default_emit
    saw_reply = False
    saw_refusal = False
    saw_tool_activity = False
    saw_named_tool = False
    saw_mutating_tool = False
    saw_failed_tool_result = False
    saw_login_failure = False

    def emit_event(event: dict[str, Any]) -> None:
        nonlocal saw_reply, saw_refusal, saw_tool_activity, saw_named_tool, saw_mutating_tool
        nonlocal saw_failed_tool_result, saw_login_failure
        kind = str(event.get(FORGE_EVENT_KEY) or "")
        if kind == "error" and is_claude_cli_login_error(str(event.get("text") or "")):
            # The CLI died unauthenticated. Remember it so the run's recorded
            # reason names the situation instead of only "claude exited 1" —
            # the recorded reason was exactly what the owner saw when this
            # happened live (2026-08-05: chip on GPT, dispatch on empty model,
            # 15s to a raw "/login" prompt).
            saw_login_failure = True
        if kind in {"final", "say"}:
            reply_text = str(event.get("text") or "")
            if _is_conversational_reply(reply_text):
                saw_reply = True
            if _is_action_refusal(reply_text):
                saw_refusal = True
        elif kind in {"tool", "tool_result"}:
            saw_tool_activity = True
            if kind == "tool_result" and bool(event.get("is_error")):
                saw_failed_tool_result = True
            # Only ``tool`` carries a name; ``tool_result`` does not.
            name = str(event.get("name") or "").strip()
            if name and name != "tool":
                saw_named_tool = True
                if not _is_read_only_cli_tool(name):
                    saw_mutating_tool = True
        emit_sink(event)

    def _run_pass(p: str) -> tuple[int, str]:
        # stream-json + verbose => one structured JSON event per line as they
        # happen (assistant text, tool_use, tool_result, result), not one blob.
        # The PROMPT is passed via STDIN as a stream-json USER MESSAGE (built
        # below), NOT as the -p argv value: a large (e.g. funnel-composed) prompt
        # overflows the Windows command-line limit -> [WinError 206]. NOTE: in
        # stream-json OUTPUT mode a raw stdin prompt is ignored (you get an empty
        # turn / no edits), so we MUST also set --input-format stream-json and feed
        # a {"type":"user",...} line. (Verified: raw stdin -> only system events;
        # stream-json user message -> assistant + result.)
        cmd = [
            claude,
            "-p",
            "--model",
            model,
            "--allowedTools",
            *allowed_tools,
            "--output-format",
            "stream-json",
            "--input-format",
            "stream-json",
            "--verbose",
            # Stream assistant prose as token-progressive ``content_block_delta``
            # events so first token and every token after surface live.
            "--include-partial-messages",
        ]
        # A fresh stateful translator per pass: the structural insight gate
        # (suppress pre-observation plan reasoning; dedupe repeats) needs run-level
        # state, and each pass re-plans, so the gate resets between passes.
        translate = ClaudeStreamTranslator()
        if runner is not None:
            # Buffered fallback (tests / injection): the injected runner asserts on
            # argv and has no Windows arg-length limit, so keep the prompt as an arg.
            rc_, out_ = runner([claude, "-p", p, *cmd[2:]], str(cwd), timeout)
            for ln in str(out_).splitlines():
                if ln.strip():
                    for ev in translate(ln):
                        emit_event(ev)
            return rc_, out_
        # Wrap the prompt as a stream-json user message — the input form claude
        # expects under --input-format stream-json. A raw stdin prompt is ignored
        # in stream-json mode (empty turn / no edits, which silently no-ops a build).
        stdin_payload = json.dumps({"type": "user", "message": {"role": "user", "content": p}}) + "\n"
        return _stream_cli(cmd, str(cwd), timeout, translate, emit_event, stdin_text=stdin_payload)

    from thomas.forge.anvil import forge_code_git

    verify_failed = False
    try:
        snap_before = forge_code_git.snapshot(cwd)
        rc, out = _run_pass(prompt)
        # The RUN/TEST step: only verify a clean edit pass (a non-zero edit pass
        # is already a failure to surface). The engine runs the real check.
        if verify and rc == 0:
            vrc = _verify_and_iterate(
                cwd, snap_before, emit_event, _run_pass, goal, verifier=verifier, max_fix_iters=max_fix_iters
            )
            if vrc != 0:
                rc, verify_failed = vrc, True
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
        return CliDispatchResult(False, f"refused: claude run failed: {exc}", prompt)

    changed = forge_code_git.project_delta_since(cwd, snap_before)
    action_refused = saw_refusal
    # See the same rule in dispatch_agent_loop: a run that changed nothing can
    # still have answered. Relaxed only with positive evidence -- names were
    # visible and every one was read-only.
    read_only_run = saw_named_tool and not saw_mutating_tool
    # The same contract dispatch_agent_loop settled on 2026-08-05: a
    # write-capable tool disqualifies the answer only when a tool FAILURE was
    # also seen. Git truth (`not changed`) is already established below, every
    # result succeeded, and the answer arrived -- demoting that run to a
    # failure was manufacturing an error out of the tool's NAME. Unnamed tool
    # activity still disqualifies: nothing is known about what it did.
    tools_disqualify = saw_tool_activity and not read_only_run and (saw_failed_tool_result or not saw_named_tool)
    conversation_reply = rc == 0 and not changed and saw_reply and not tools_disqualify and not action_refused
    if rc != 0:
        if saw_login_failure:
            # Not a build failure at all — the executor could never start work.
            # The exit code is kept in `returncode`; the sentence carries what
            # the owner can actually do about it.
            reason = CLAUDE_CLI_LOGIN_GUIDANCE
        elif verify_failed:
            reason = f"verification failed (exit {rc}) after fix attempts"
        else:
            reason = f"claude exited {rc}"
    elif action_refused:
        detail = " after leaving partial file changes" if changed else ""
        reason = f"Claude could not complete the requested action{detail}"
    elif not changed:
        if conversation_reply:
            reason = "Claude replied without changing files"
        else:
            reason = "claude ran but made NO repo changes (no-op) — nothing to review"
    else:
        reason = f"dispatched via claude CLI ({len(changed)} file(s) changed; engine checks passed)"
    return CliDispatchResult(
        ok=(rc == 0 and not action_refused and (bool(changed) or conversation_reply)),
        reason=reason,
        prompt=prompt,
        returncode=rc,
        changed_files=changed,
        stdout_tail=str(out)[-2000:],
    )
