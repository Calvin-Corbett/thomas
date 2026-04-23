"""Direct fast-path action helpers for the tools specialist."""

from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import os
import re
from pathlib import Path
from typing import Any

from thomas.marketplace.specialists.tools_fast_path_prompting import (
    _normalize_requested_content,
    _normalize_requested_reply,
    _parse_clock_time,
    _resolve_app_launch_target,
    _resolve_desktop_path,
    _sanitize_task_filename,
)
from thomas.tools.browser import BrowserClickTool, BrowserOpenTool
from thomas.tools.filesystem import _is_protected_runtime_path

log = logging.getLogger(__name__)

def _find_named_file_on_desktop(filename: str) -> Path:
    candidate_name = _normalize_requested_content(filename)
    desktop = _resolve_desktop_path()
    if not desktop.exists():
        raise FileNotFoundError("Desktop folder not found")
    direct = desktop / candidate_name
    if direct.is_file():
        return direct
    for match in desktop.rglob(candidate_name):
        if match.is_file():
            return match
    raise FileNotFoundError(f"Could not find {candidate_name} on the Desktop")


def _blocked_runtime_target(path: Path) -> str | None:
    repo_root = Path.cwd().resolve()
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return None
    return _is_protected_runtime_path(repo_root, resolved)


def _strip_html_markup(fragment: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", fragment or "")
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_inline_text(text: Any) -> str:
    if text is None:
        return ""
    value = re.sub(r"\s+", " ", str(text)).strip()
    if len(value) > 400:
        value = value[:400].rstrip() + "…"
    return value


def _extract_main_headline_text(html_text: str) -> str:
    if not html_text:
        return ""
    for pattern in (
        r"(?is)<h1\b[^>]*>(.*?)</h1>",
        r"(?is)<meta\b[^>]*(?:property|name)\s*=\s*[\"'](?:og:title|twitter:title)[\"'][^>]*content\s*=\s*[\"'](.*?)[\"'][^>]*>",
        r"(?is)<title\b[^>]*>(.*?)</title>",
    ):
        match = re.search(pattern, html_text)
        if match:
            text = _strip_html_markup(match.group(1))
            if text:
                return text
    return ""


async def _fetch_browser_headline(url: str) -> str:
    result = await _browser_read_open(
        url,
        session_name="headline-read",
        headline_only=True,
    )
    if not bool(getattr(result, "ok", False)):
        raise RuntimeError(str(getattr(result, "error", "") or f"Failed to open {url}"))
    data = getattr(result, "data", None)
    payload = data if isinstance(data, dict) else {}
    headline = _clean_inline_text(payload.get("headline"))
    if headline:
        return headline
    extracted = _extract_main_headline_text(str(payload.get("text") or ""))
    if extracted:
        return extracted
    title = _clean_inline_text(payload.get("title"))
    if title:
        return title
    raise ValueError(f"Could not find a main headline at {url}")


async def _fetch_browser_title(url: str) -> str:
    result = await _browser_read_open(
        url,
        session_name="headline-read",
        headline_only=True,
    )
    if not bool(getattr(result, "ok", False)):
        raise RuntimeError(str(getattr(result, "error", "") or f"Failed to open {url}"))
    data = getattr(result, "data", None)
    payload = data if isinstance(data, dict) else {}
    title = _clean_inline_text(payload.get("title"))
    if title:
        return title
    headline = _clean_inline_text(payload.get("headline"))
    if headline:
        return headline
    raise ValueError(f"Could not find a page title at {url}")


async def _fetch_browser_main_text(url: str) -> str:
    result = await _browser_read_open(
        url,
        session_name="content-read",
        headline_only=False,
    )
    if not bool(getattr(result, "ok", False)):
        raise RuntimeError(str(getattr(result, "error", "") or f"Failed to open {url}"))
    data = getattr(result, "data", None)
    payload = data if isinstance(data, dict) else {}
    text = str(payload.get("text") or "").strip()
    if text:
        return text
    headline = _clean_inline_text(payload.get("headline"))
    if headline:
        return headline
    title = _clean_inline_text(payload.get("title"))
    if title:
        return title
    raise ValueError(f"Could not extract main text at {url}")


async def _browser_read_open(url: str, *, session_name: str, headline_only: bool) -> Any:
    args: dict[str, Any] = {"url": url, "session": session_name, "headless": True}
    if headline_only:
        args["headline_only"] = True
    else:
        args["lane"] = "read"
    result = await BrowserOpenTool().execute(args)
    if bool(getattr(result, "ok", False)):
        return result

    retry_args = dict(args)
    retry_args["session"] = f"{session_name}-retry"
    retry_result = await BrowserOpenTool().execute(retry_args)
    if bool(getattr(retry_result, "ok", False)):
        return retry_result
    return retry_result


async def _browser_action_open(url: str, *, session_name: str = "action-direct") -> tuple[Any, str]:
    args: dict[str, Any] = {
        "url": url,
        "session": session_name,
        "headless": True,
        "lane": "action",
        "headline_only": True,
        "navigation_only": True,
    }
    result = await BrowserOpenTool().execute(args)
    if bool(getattr(result, "ok", False)):
        return result, session_name

    retry_session = f"{session_name}-retry"
    retry_args = dict(args)
    retry_args["session"] = retry_session
    retry_result = await BrowserOpenTool().execute(retry_args)
    if bool(getattr(retry_result, "ok", False)):
        return retry_result, retry_session
    return retry_result, retry_session


async def _browser_click_in_session(label: str, *, session_name: str) -> Any:
    label_text = _normalize_requested_content(label)
    escaped_label = label_text.replace('"', '\\"')
    selector_candidates = [
        f'role=link[name="{escaped_label}"]',
        f'role=button[name="{escaped_label}"]',
        f'a:has-text("{escaped_label}")',
        f'button:has-text("{escaped_label}")',
        label_text,
    ]
    last_error = ""
    for selector in selector_candidates:
        click_result = await BrowserClickTool().execute(
            {
                "selector": selector,
                "session": session_name,
                "timeout_ms": 1500,
                "post_click_stabilize_ms": 800,
                "prefer_link_navigation": True,
            }
        )
        if bool(getattr(click_result, "ok", False)):
            return click_result
        last_error = str(getattr(click_result, "error", "") or f"Failed to click {label_text}")
    raise RuntimeError(last_error or f"Failed to click {label_text}")


async def _run_capture_command(*args: str, cwd: str | None = None, timeout: float = 30.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(OSError, ProcessLookupError):
            proc.kill()
        with contextlib.suppress(OSError, ProcessLookupError):
            await proc.communicate()
        raise
    return (
        int(proc.returncode or 0),
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
    )


async def _create_weekday_local_reminder(task_name: str, message: str, *, time_text: str) -> tuple[Path, str]:
    hour, minute = _parse_clock_time(time_text)
    safe_name = _normalize_requested_reply(task_name)
    reminder_text = _normalize_requested_content(message)
    local_appdata = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
    script_path = local_appdata / f"{_sanitize_task_filename(safe_name)}.ps1"
    script_body = (
        "$message = @'\n"
        f"{reminder_text}\n"
        "'@\n"
        "$title = @'\n"
        f"{safe_name}\n"
        "'@\n"
        "$wshell = New-Object -ComObject WScript.Shell\n"
        "[void]$wshell.Popup($message, 0, $title, 64)\n"
    )
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_body, encoding="utf-8")

    schedule_time = f"{hour:02d}:{minute:02d}"
    task_command = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script_path}"'
    returncode, stdout_text, stderr_text = await _run_capture_command(
        "schtasks.exe",
        "/Create",
        "/F",
        "/SC",
        "WEEKLY",
        "/D",
        "MON,TUE,WED,THU,FRI",
        "/ST",
        schedule_time,
        "/TN",
        safe_name,
        "/TR",
        task_command,
    )
    if returncode != 0:
        error_text = stderr_text.strip() or stdout_text.strip() or f"schtasks exited with code {returncode}"
        raise RuntimeError(error_text)
    return script_path, f"{safe_name} Ready"


async def _launch_local_application(app_name: str) -> str:
    display_name, target = _resolve_app_launch_target(app_name)
    escaped_target = target.replace("'", "''")
    returncode, stdout_text, stderr_text = await _run_capture_command(
        "powershell.exe",
        "-NoProfile",
        "-Command",
        f"Start-Process -FilePath '{escaped_target}'",
    )
    if returncode != 0:
        error_text = stderr_text.strip() or stdout_text.strip() or f"Start-Process exited with code {returncode}"
        raise RuntimeError(error_text)
    return f"{display_name} opened"
