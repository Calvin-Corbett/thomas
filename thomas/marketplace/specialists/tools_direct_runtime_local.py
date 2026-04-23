"""Direct local-machine handlers for the tools specialist."""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import AsyncIterator
from typing import Any

from thomas.marketplace.orchestrator.protocol import CapabilityToken
from thomas.marketplace.specialists.tools_fast_path import (
    _DIRECT_APP_OPEN_RE,
    _DIRECT_DESKTOP_FILE_FIND_RE,
    _DIRECT_WEEKDAY_REMINDER_RE,
    _extract_strict_output,
    _normalize_requested_content,
    _normalize_requested_reply,
)


async def handle_direct_runtime_local(prompt: str, token: CapabilityToken) -> AsyncIterator[dict[str, Any]]:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return

    desktop_find_match = _DIRECT_DESKTOP_FILE_FIND_RE.search(prompt_text)
    if desktop_find_match:
        if not token.permits_action("read"):
            yield {"type": "error", "error": "Permission denied: token does not permit reads"}
            return
        filename = _normalize_requested_content(desktop_find_match.group("name"))
        start = time.monotonic()
        yield {
            "type": "tool_start",
            "name": "direct.find_file",
            "id": "direct.find_file",
            "args": {"name": filename, "scope": "Desktop"},
        }
        try:
            from thomas.marketplace.specialists import tools as tools_mod

            found_path = tools_mod._find_named_file_on_desktop(filename)
        except (OSError, RuntimeError, ValueError) as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.find_file",
                "id": "direct.find_file",
                "ok": False,
                "result": str(exc),
                "ms": elapsed,
            }
            failure_text = _extract_strict_output(prompt_text, str(exc), [str(exc)]) or str(exc)
            yield {"type": "error", "error": failure_text}
            return

        elapsed = int((time.monotonic() - start) * 1000)
        found_text = str(found_path)
        yield {
            "type": "tool_result",
            "name": "direct.find_file",
            "id": "direct.find_file",
            "ok": True,
            "result": found_text,
            "ms": elapsed,
        }
        response = _extract_strict_output(prompt_text, found_text, [found_text]) or found_text
        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1, "tool_calls": 1}
        return

    app_open_match = _DIRECT_APP_OPEN_RE.search(prompt_text)
    if app_open_match:
        if not token.permits_action("execute"):
            yield {"type": "error", "error": "Permission denied: token does not permit execute actions"}
            return
        app_name = _normalize_requested_content(app_open_match.group("app"))
        desired_response = _normalize_requested_reply(app_open_match.group("response")) or "OK"

        start = time.monotonic()
        yield {
            "type": "tool_start",
            "name": "direct.open_app",
            "id": "direct.open_app",
            "args": {"app": app_name},
        }
        try:
            from thomas.marketplace.specialists import tools as tools_mod

            open_result = await tools_mod._launch_local_application(app_name)
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.open_app",
                "id": "direct.open_app",
                "ok": False,
                "result": "App launch timed out after 30s",
                "ms": elapsed,
            }
            yield {"type": "error", "error": "Direct app launch timed out"}
            return
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.open_app",
                "id": "direct.open_app",
                "ok": False,
                "result": str(exc),
                "ms": elapsed,
            }
            failure_text = _extract_strict_output(prompt_text, str(exc), [str(exc)]) or str(exc)
            yield {"type": "error", "error": failure_text}
            return

        elapsed = int((time.monotonic() - start) * 1000)
        yield {
            "type": "tool_result",
            "name": "direct.open_app",
            "id": "direct.open_app",
            "ok": True,
            "result": open_result,
            "ms": elapsed,
        }
        response = _extract_strict_output(prompt_text, desired_response, [open_result]) or desired_response
        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1, "tool_calls": 1}
        return

    reminder_match = _DIRECT_WEEKDAY_REMINDER_RE.search(prompt_text)
    if reminder_match:
        if not (token.permits_action("write") and token.permits_action("execute")):
            yield {"type": "error", "error": "Permission denied: token does not permit write+execute actions"}
            return
        task_name = _normalize_requested_reply(reminder_match.group("name"))
        message = _normalize_requested_content(reminder_match.group("message"))
        time_text = reminder_match.group("time").strip()

        write_start = time.monotonic()
        yield {
            "type": "tool_start",
            "name": "direct.write_reminder_script",
            "id": "direct.write_reminder_script",
            "args": {"task_name": task_name},
        }
        try:
            from thomas.marketplace.specialists import tools as tools_mod

            script_path, ready_text = await tools_mod._create_weekday_local_reminder(
                task_name,
                message,
                time_text=time_text,
            )
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - write_start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.write_reminder_script",
                "id": "direct.write_reminder_script",
                "ok": False,
                "result": "Reminder setup timed out after 30s",
                "ms": elapsed,
            }
            yield {"type": "error", "error": "Direct reminder setup timed out"}
            return
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            elapsed = int((time.monotonic() - write_start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.write_reminder_script",
                "id": "direct.write_reminder_script",
                "ok": False,
                "result": str(exc),
                "ms": elapsed,
            }
            failure_text = _extract_strict_output(prompt_text, str(exc), [str(exc)]) or str(exc)
            yield {"type": "error", "error": failure_text}
            return

        elapsed = int((time.monotonic() - write_start) * 1000)
        yield {
            "type": "tool_result",
            "name": "direct.write_reminder_script",
            "id": "direct.write_reminder_script",
            "ok": True,
            "result": str(script_path),
            "ms": elapsed,
        }
        yield {
            "type": "tool_start",
            "name": "direct.schedule_task",
            "id": "direct.schedule_task",
            "args": {"task_name": task_name, "time": time_text, "days": "MON,TUE,WED,THU,FRI"},
        }
        yield {
            "type": "tool_result",
            "name": "direct.schedule_task",
            "id": "direct.schedule_task",
            "ok": True,
            "result": ready_text,
            "ms": 0,
        }
        response = _extract_strict_output(prompt_text, ready_text, [ready_text]) or ready_text
        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1, "tool_calls": 2}
        return
