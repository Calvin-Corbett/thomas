"""Claude CLI file writer: read-only CLI, engine-owned single-file write."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, AsyncIterator


def _matches(requested: str, observed: str) -> bool:
    wanted = requested.removeprefix("claude:").casefold()
    actual = observed.casefold()
    if not actual.startswith("claude"):
        return False
    if wanted in {"sonnet", "opus", "haiku"}:
        return wanted in actual
    return wanted == actual or wanted in actual


async def run_claude_file_writer(
    workspace: Any, toolset: Any, instructions: str, *, model_id: str, deadline: float
) -> AsyncIterator[dict[str, Any]]:
    """Require a terminal model receipt and route output through fs.write_file."""
    executable = shutil.which("claude") or shutil.which("claude.cmd")
    if not executable:
        yield {"type": "error", "error": "Claude CLI is unavailable for this file writer"}
        return
    model = model_id.removeprefix("claude:")
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
        f"You are building only {workspace.path} from a private project snapshot. "
        "Read the files you need. You have no write tools. Return exactly one JSON object "
        f'with keys "path" (exactly "{workspace.path}") and "content" (the entire replacement UTF-8 file). '
        "No Markdown, explanation, or second file. The host will write only the assigned file, "
        "check that no other file changed, and decide whether to integrate it.\n\n" + instructions
    )
    stdin = json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n"
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(  # noqa: S603 - fixed CLI and bounded arguments
        command,
        cwd=str(workspace.root),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    job = None
    try:
        if os.name == "nt":
            from .windows_job import OwnedWindowsJob

            job = OwnedWindowsJob(proc)
            # A descendant may inherit stdout; end the whole tree when Claude exits.
            threading.Thread(target=lambda: (proc.wait(), job.close()), daemon=True).start()
        assert proc.stdin is not None and proc.stdout is not None

        def feed() -> None:
            try:
                proc.stdin.write(stdin.encode("utf-8"))
                proc.stdin.flush()
            except (OSError, ValueError):
                pass
            finally:
                proc.stdin.close()

        threading.Thread(target=feed, daemon=True).start()
        observed = ""
        observed_models: set[str] = set()
        terminal = None
        async with asyncio.timeout_at(deadline):
            while raw := await asyncio.to_thread(proc.stdout.readline):
                try:
                    event = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "system" and event.get("subtype") == "init":
                    observed = str(event.get("model") or observed)
                    if observed:
                        observed_models.add(observed)
                elif event.get("type") == "assistant":
                    message = event.get("message") or {}
                    if isinstance(message, dict):
                        observed = str(message.get("model") or observed)
                        if observed:
                            observed_models.add(observed)
                        for block in message.get("content") or []:
                            if (
                                isinstance(block, dict)
                                and block.get("type") == "tool_use"
                                and block.get("name") not in {"Read", "Glob", "Grep"}
                            ):
                                raise ValueError("Claude file writer attempted an unapproved tool")
                elif event.get("type") == "result":
                    terminal = event
            await asyncio.to_thread(proc.wait)
        if not terminal or terminal.get("is_error") or proc.returncode != 0:
            raise ValueError("Claude file writer ended without a successful result")
        if not observed_models or any(not _matches(model_id, actual) for actual in observed_models):
            raise ValueError(f"Claude file writer reported model {observed or 'unknown'}, expected {model_id}")
        answer = json.loads(str(terminal.get("result") or ""))
        if not isinstance(answer, dict) or set(answer) != {"path", "content"}:
            raise ValueError("Claude file writer must return only assigned path and full file content")
        if answer["path"] != workspace.path or not isinstance(answer["content"], str):
            raise ValueError("Claude file writer named a different output file")
        result = await toolset.execute("fs.write_file", answer)
        if not result.ok:
            raise ValueError(str(result.error or "assigned file write was refused"))
        yield {
            "type": "model_runtime",
            "model_used": observed,
            "profile_used": "claude_cli",
            "provider_used": "claude_cli",
            "model": observed,
        }
        yield {"type": "text", "text": f"Claude wrote {workspace.path} in its private snapshot."}
    except (OSError, ValueError, json.JSONDecodeError, TimeoutError) as exc:
        yield {"type": "error", "error": str(exc)}
    finally:
        if job is not None:
            job.close()
        if proc.poll() is None:
            proc.kill()
        await asyncio.to_thread(proc.wait)
