"""Direct file/runtime handlers for the tools specialist."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from typing import Any

from thomas.marketplace.orchestrator.protocol import CapabilityToken
from thomas.marketplace.specialists.tools_fast_path import (
    _DIRECT_FILE_WRITE_RE,
    _DIRECT_PYTHON_RUN_RE,
    _SAFE_PRINT_EXPR_RE,
    _blocked_runtime_target,
    _extract_strict_output,
    _normalize_requested_content,
    _normalize_target_path,
)


async def handle_direct_runtime_files(prompt: str, token: CapabilityToken) -> AsyncIterator[dict[str, Any]]:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return

    write_match = _DIRECT_FILE_WRITE_RE.search(prompt_text)
    if write_match:
        if not token.permits_action("write"):
            yield {"type": "error", "error": "Permission denied: token does not permit file writes"}
            return
        path = _normalize_target_path(write_match.group("path"))
        blocked = _blocked_runtime_target(path)
        if blocked:
            yield {"type": "error", "error": blocked}
            return
        content = _normalize_requested_content(write_match.group("content"))
        start = time.monotonic()
        yield {"type": "tool_start", "name": "direct.write_file", "id": "direct.write_file", "args": {"path": str(path)}}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.write_file",
                "id": "direct.write_file",
                "ok": False,
                "result": str(exc),
                "ms": elapsed,
            }
            yield {"type": "error", "error": f"Direct file write failed: {exc}"}
            return

        elapsed = int((time.monotonic() - start) * 1000)
        yield {
            "type": "tool_result",
            "name": "direct.write_file",
            "id": "direct.write_file",
            "ok": True,
            "result": written,
            "ms": elapsed,
        }
        response = _extract_strict_output(prompt_text, "", [written]) or f"{path}\n{written}"
        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1, "tool_calls": 1}
        return

    py_match = _DIRECT_PYTHON_RUN_RE.search(prompt_text)
    if py_match:
        if not (token.permits_action("write") and token.permits_action("execute")):
            yield {"type": "error", "error": "Permission denied: token does not permit write+execute actions"}
            return
        expr = py_match.group("expr").strip()
        if not _SAFE_PRINT_EXPR_RE.fullmatch(expr):
            return
        path = _normalize_target_path(py_match.group("path"))
        blocked = _blocked_runtime_target(path)
        if blocked:
            yield {"type": "error", "error": blocked}
            return
        source = f"print({expr})\n"

        write_start = time.monotonic()
        yield {"type": "tool_start", "name": "direct.write_file", "id": "direct.write_file", "args": {"path": str(path)}}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            elapsed = int((time.monotonic() - write_start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.write_file",
                "id": "direct.write_file",
                "ok": False,
                "result": str(exc),
                "ms": elapsed,
            }
            yield {"type": "error", "error": f"Direct script write failed: {exc}"}
            return
        write_elapsed = int((time.monotonic() - write_start) * 1000)
        yield {
            "type": "tool_result",
            "name": "direct.write_file",
            "id": "direct.write_file",
            "ok": True,
            "result": source,
            "ms": write_elapsed,
        }

        run_start = time.monotonic()
        yield {"type": "tool_start", "name": "direct.run_python", "id": "direct.run_python", "args": {"path": str(path)}}
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(path.parent),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - run_start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.run_python",
                "id": "direct.run_python",
                "ok": False,
                "result": "Command timed out after 30s",
                "ms": elapsed,
            }
            yield {"type": "error", "error": "Direct python execution timed out"}
            return
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            elapsed = int((time.monotonic() - run_start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.run_python",
                "id": "direct.run_python",
                "ok": False,
                "result": str(exc),
                "ms": elapsed,
            }
            yield {"type": "error", "error": f"Direct python execution failed: {exc}"}
            return

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        run_elapsed = int((time.monotonic() - run_start) * 1000)
        ok = proc.returncode == 0
        run_result = stdout if ok else (stderr or stdout or f"Exit code {proc.returncode}")
        yield {
            "type": "tool_result",
            "name": "direct.run_python",
            "id": "direct.run_python",
            "ok": ok,
            "result": run_result,
            "ms": run_elapsed,
        }
        if not ok:
            yield {"type": "error", "error": f"Direct python execution failed with exit code {proc.returncode}"}
            return

        response = _extract_strict_output(prompt_text, stdout, [stdout]) or stdout.strip()
        if not response:
            yield {"type": "error", "error": "Direct python execution returned empty output"}
            return
        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1, "tool_calls": 2}
        return
