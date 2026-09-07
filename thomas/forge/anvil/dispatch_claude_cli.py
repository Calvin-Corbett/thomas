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
from .forge_code_settings import direct_shell_allowed
from .forge_event_stream import (
    CLAUDE_CLI_LOGIN_GUIDANCE,
    CLI_READ_ONLY_TOOL_NAMES,
    FORGE_EVENT_KEY,
    ClaudeStreamTranslator,
    _default_emit,
    _stream_cli,
    is_claude_cli_login_error,
)
from .task_context import repo_context_for

# Safe default toolset for a dispatched headless build: edit files only — NO shell,
# git, or network. The dispatched agent can change code; it cannot run commands or
# touch the network. The human watcher reviews the resulting diff and runs the tests.
SAFE_CLI_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "MultiEdit", "NotebookEdit")


def _claude_cli_tools(
    allowed_tools: tuple[str, ...],
    guardrails: str,
    *,
    autonomy_level: int,
    file_access: str,
) -> tuple[tuple[str, ...], bool]:
    """Return the exact built-in surface and whether Bash must be denied."""

    _ = allowed_tools  # caller rules never widen the exact built-in surface
    direct_shell = direct_shell_allowed(
        autonomy_level=autonomy_level,
        file_access=file_access,
        guardrails=guardrails,
    )
    return SAFE_CLI_TOOLS + (("Bash",) if direct_shell else ()), not direct_shell


def _is_read_only_cli_tool(tool_name: str) -> bool:
    """NAME-only fallback: can this claude tool, by name, only ever look?

    Used to tell a run that only looked from one that tried to change something:
    a request to inspect and explain must read files to answer, and reading is
    not a failed edit. The name list lives in ``forge_event_stream`` next to the
    translator that stamps ``access`` from it — the stamp (which judges Bash by
    its COMMAND) always wins over this fallback. Anything not listed is assumed
    capable of writing, so an unrecognised tool stays strict.
    """
    return str(tool_name or "").strip().casefold() in CLI_READ_ONLY_TOOL_NAMES


@dataclass
class CliDispatchResult:
    ok: bool
    reason: str
    prompt: str
    returncode: int = 0
    changed_files: list[str] = field(default_factory=list)
    stdout_tail: str = ""
    # What Claude actually SAID. The stream carries it, `emit_event` reads it to
    # set `saw_reply`, and before 2026-09-03 it was dropped there — so a caller
    # could learn that a reply arrived but never what it was. A benchmark run on
    # that day recorded two tasks as `ok chars=0` while 368 lines of real work
    # sat in the worktree: the dispatcher had no field to return the answer in.
    # `stdout_tail` is not a substitute; it is a truncated tail of raw stream
    # JSON, not the reply.
    reply: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "returncode": self.returncode,
            "changed_files": self.changed_files,
            "prompt_chars": len(self.prompt),
            # Counted, not inlined: a summary line stays readable, and a zero
            # here is the visible symptom of the bug above.
            "reply_chars": len(self.reply),
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


# Claude Code consults only Edit(path) (and Read) rules for file permissions; a Write,
# NotebookEdit or MultiEdit path rule is accepted, never consulted, and warned about at
# startup (docs: permissions, "Read and Edit"). Edit(path) governs every built-in write.
_FENCE_RULE_TOOLS = ("Edit",)


def _fence_settings_file(cwd: str | Path, protected_paths: list[str] | None) -> Path | None:
    """Write a Claude Code settings file whose deny rules cover the run's fence.

    A directory entry becomes a glob over everything under it. Returns None when
    there is nothing to fence, so the command line stays as it was.
    """
    entries = []
    for raw in protected_paths or []:
        text = str(raw or "").strip().replace("\\", "/")
        if not text:
            continue
        if text.endswith("/") or (Path(cwd) / text).is_dir():
            text = text.rstrip("/") + "/**"
        entries.append(text)
    if not entries:
        return None
    rules = [f"{tool}({entry})" for entry in entries for tool in _FENCE_RULE_TOOLS]
    folder = Path(cwd) / ".thomas"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "claude-fence-settings.json"
    target.write_text(json.dumps({"permissions": {"deny": rules}}, indent=2), encoding="utf-8")
    return target


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
    protected_paths: list[str] | None = None,
    allow_without_history: bool = False,
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

    # An empty `definition` is what made every dispatch start amnesiac: the
    # model got the task sentence and nothing else, and paid in turns to
    # rediscover a repository the index already knows. Fill it only when the
    # caller supplied nothing, so an explicit definition always wins, and treat
    # retrieval failure as no context rather than as a failed dispatch.
    if not str(definition or "").strip():
        definition = repo_context_for(goal)

    prompt = compose_headless_prompt(
        goal,
        definition=definition,
        plan=plan,
        history=history,
        file_access=file_access,
        guardrails=guardrails,
        autonomy_level=autonomy_level,
        project_root=cwd,
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
    saw_final = False
    saw_refusal = False
    saw_tool_activity = False
    saw_named_tool = False
    saw_mutating_tool = False
    saw_failed_tool_result = False
    saw_login_failure = False
    final_reply = ""

    def emit_event(event: dict[str, Any]) -> None:
        nonlocal saw_reply, saw_final, saw_refusal, saw_tool_activity, saw_named_tool, saw_mutating_tool
        nonlocal saw_failed_tool_result, saw_login_failure, final_reply
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
            # A `final` is the whole answer and replaces what came before; a
            # `say` is one chunk of a streamed one, so those accumulate. Keeping
            # only the last `say` would truncate every multi-chunk reply to its
            # tail.
            if kind == "final":
                final_reply = reply_text
            elif reply_text:
                final_reply += reply_text
            if kind == "final":
                # ``final`` comes only from a Claude result whose ``is_error``
                # is false. That protocol verdict is stronger than the process
                # code: Claude can exit 1 after landing and reporting the work.
                saw_final = True
            if _is_conversational_reply(reply_text):
                saw_reply = True
            if _is_action_refusal(reply_text):
                saw_refusal = True
        elif kind in {"tool", "tool_result"}:
            saw_tool_activity = True
            if kind == "tool_result" and bool(event.get("is_error")):
                saw_failed_tool_result = True
            # ``tool`` always carries a name; a ``tool_result`` carries one only
            # when the translator correlated it back to its call.
            name = str(event.get("name") or "").strip()
            if name and name != "tool":
                saw_named_tool = True
                # The translator stamps ``access`` ("read"/"write") onto tool
                # events, classifying Bash by its COMMAND rather than its name.
                # Trust the stamp when present — without it, an explain-only run
                # whose Bash ran `ls` counted as write-capable and an errored
                # read demoted the whole answered run. Name-based classification
                # stays as the fallback for unstamped events; it fails toward
                # write, so an unseen command is never relaxed. Same contract as
                # _confirmed_conversation_reply and dispatch_agent_loop.
                access = str(event.get("access") or "").strip()
                if access == "write" or (access != "read" and not _is_read_only_cli_tool(name)):
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
        cli_tools, deny_bash = _claude_cli_tools(
            allowed_tools,
            guardrails,
            autonomy_level=autonomy_level,
            file_access=file_access,
        )
        # The run's file fence, as Claude Code permission deny rules: a fenced
        # write is refused by the CLI itself, never left to the brief's prose.
        fence_settings = _fence_settings_file(cwd, protected_paths)
        cmd = [
            claude,
            "-p",
            "--model",
            model,
            "--permission-mode",
            "dontAsk",
            *(["--settings", str(fence_settings)] if fence_settings else []),
            "--tools",
            *cli_tools,
            "--allowedTools",
            *cli_tools,
            *(["--disallowedTools", "Bash"] if deny_bash else []),
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
        # The person's open-time choice to work without history arrives as this
        # argument, never inferred; with it the snapshot is a content manifest.
        snap_before = forge_code_git.snapshot(cwd, allow_without_history=allow_without_history)
        rc, out = _run_pass(prompt)
        # The RUN/TEST step follows protocol truth, not only process truth.
        # Claude can emit a confirmed successful ``result`` and then exit 1;
        # that run is eligible to succeed, so its changed files must still pass
        # the real verifier before we accept it.
        if verify and (rc == 0 or saw_final):
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
    process_completed = rc == 0 or saw_final
    conversation_reply = process_completed and not changed and saw_reply and not tools_disqualify and not action_refused
    succeeded = (
        process_completed
        and not saw_login_failure
        and not verify_failed
        and not action_refused
        and (bool(changed) or conversation_reply)
    )
    if rc != 0 and not succeeded:
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
    elif rc:
        reason = (
            f"dispatched via claude CLI ({len(changed)} file(s) changed; "
            f"Claude reported success; build process exited {rc})"
        )
    else:
        reason = f"dispatched via claude CLI ({len(changed)} file(s) changed; engine checks passed)"
    return CliDispatchResult(
        ok=succeeded,
        reason=reason,
        prompt=prompt,
        returncode=rc,
        changed_files=changed,
        stdout_tail=str(out)[-2000:],
        reply=final_reply,
    )
