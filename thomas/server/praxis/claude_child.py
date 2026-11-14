"""Read-only Claude CLI children for a Claude-owned Build run channel."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any


def build_claude_read_child_runner(project: Path, *, model_id: str):
    model = model_id.removeprefix("claude:")

    def matches_requested(observed: str) -> bool:
        actual, wanted = observed.casefold(), model.casefold()
        if not actual.startswith("claude"):
            return False
        if wanted in {"sonnet", "opus", "haiku"}:
            return wanted in actual
        return wanted == "claude" or wanted in actual

    async def run(_child_id: str, kind: str, title: str, brief: str) -> AsyncIterator[dict[str, Any]]:
        executable = shutil.which("claude") or shutil.which("claude.cmd")
        if not executable:
            yield {"type": "error", "error": "Claude CLI is unavailable for this child"}
            return
        command = [
            executable,
            "-p",
            "--model",
            model,
            "--permission-mode",
            "dontAsk",
            "--tools",
            "Read",
            "Glob",
            "Grep",
            "--allowedTools",
            "Read",
            "Glob",
            "Grep",
            "--disallowedTools",
            "Task",
            "Bash",
            "Edit",
            "Write",
            "MultiEdit",
            "NotebookEdit",
            "--strict-mcp-config",
            "--output-format",
            "stream-json",
            "--input-format",
            "stream-json",
            "--verbose",
        ]
        prompt = (
            f"You are a read-only {kind} agent for the Build task. {title}. "
            "Inspect the project and report evidence. Do not edit files, run commands, or delegate.\n\n" + brief
        )
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(project),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        observed_model = ""
        terminal: dict[str, Any] | None = None
        try:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(
                (json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n").encode()
            )
            await proc.stdin.drain()
            proc.stdin.close()
            async for raw in proc.stdout:
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "system" and event.get("subtype") == "init":
                    observed_model = str(event.get("model") or "")
                    if observed_model:
                        yield {"type": "model_runtime", "model_used": observed_model}
                elif event.get("type") == "assistant":
                    message = event.get("message") or {}
                    if isinstance(message, dict):
                        observed_model = str(message.get("model") or observed_model)
                        if observed_model:
                            yield {"type": "model_runtime", "model_used": observed_model}
                        for block in message.get("content") or []:
                            if isinstance(block, dict) and block.get("type") == "text":
                                yield {"type": "text", "text": str(block.get("text") or "")}
                elif event.get("type") == "result":
                    terminal = event
            await proc.wait()
            if terminal and not terminal.get("is_error") and matches_requested(observed_model) and proc.returncode == 0:
                yield {"type": "done", "text": str(terminal.get("result") or ""), "model_used": observed_model}
            else:
                reason = (
                    f"Claude child reported model {observed_model or 'unknown'}, expected {model}"
                    if not matches_requested(observed_model)
                    else str((terminal or {}).get("result") or "Claude child ended without a successful result")
                )
                yield {"type": "error", "error": reason[:1000]}
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

    return run
