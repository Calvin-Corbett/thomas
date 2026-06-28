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
    FORGE_EVENT_KEY,
    ClaudeStreamTranslator,
    _default_emit,
    _stream_cli,
)

# Safe default toolset for a dispatched headless build: edit files only — NO shell,
# git, or network. The dispatched agent can change code; it cannot run commands or
# touch the network. The human watcher reviews the resulting diff and runs the tests.
SAFE_CLI_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "MultiEdit", "NotebookEdit")


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

    prompt = compose_headless_prompt(goal, definition=definition, plan=plan, history=history)
    if dry_run:
        return CliDispatchResult(False, "dry-run (claude not invoked)", prompt)

    # The kill switch guards EVERY live dispatch path, not just the GUI one.
    if emergency_stop_active():
        return CliDispatchResult(False, f"refused: emergency stop active ({emergency_stop_path()})", prompt)

    claude = claude_bin or shutil.which("claude") or shutil.which("claude.cmd")
    if not claude:
        return CliDispatchResult(False, "refused: claude CLI not found on PATH", prompt)

    emit = emit or _default_emit

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
                        emit(ev)
            return rc_, out_
        # Wrap the prompt as a stream-json user message — the input form claude
        # expects under --input-format stream-json. A raw stdin prompt is ignored
        # in stream-json mode (empty turn / no edits, which silently no-ops a build).
        stdin_payload = json.dumps({"type": "user", "message": {"role": "user", "content": p}}) + "\n"
        return _stream_cli(cmd, str(cwd), timeout, translate, emit, stdin_text=stdin_payload)

    from thomas.forge.anvil import forge_code_git

    verify_failed = False
    try:
        snap_before = forge_code_git.snapshot(cwd)
        rc, out = _run_pass(prompt)
        # The RUN/TEST step: only verify a clean edit pass (a non-zero edit pass
        # is already a failure to surface). The engine runs the real check.
        if verify and rc == 0:
            vrc = _verify_and_iterate(
                cwd, snap_before, emit, _run_pass, goal, verifier=verifier, max_fix_iters=max_fix_iters
            )
            if vrc != 0:
                rc, verify_failed = vrc, True
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
        return CliDispatchResult(False, f"refused: claude run failed: {exc}", prompt)

    changed = _git_changed_files(str(cwd))
    if rc != 0:
        reason = f"verification failed (exit {rc}) after fix attempts" if verify_failed else f"claude exited {rc}"
    elif not changed:
        reason = "claude ran but made NO repo changes (no-op) — nothing to review"
    else:
        reason = f"dispatched via claude CLI ({len(changed)} file(s) changed, verified)"
    return CliDispatchResult(
        ok=(rc == 0),
        reason=reason,
        prompt=prompt,
        returncode=rc,
        changed_files=changed,
        stdout_tail=str(out)[-2000:],
    )


def _git_changed_files(cwd: str) -> list[str]:
    try:
        p = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        return [ln[3:].strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, TypeError):
        return []
