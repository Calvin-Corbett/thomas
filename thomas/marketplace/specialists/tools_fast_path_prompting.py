"""Direct fast-path helpers for the tools specialist."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

_TOOL_FIRST_PROMPT_RE = re.compile(
    r"(?:\buse\s+(?:your\s+)?(?:file|files|tool|tools)\b|"
    r"\b(?:create|write|read|open|list|show|run|execute)\b.*\b(?:file|files|folder|directory|path|command|script|repo|repository|workspace)\b|"
    r"\btop[- ]level\s+files?\b|"
    r"\bcurrent\s+(?:repo|repository|workspace)\b|"
    r"\bopen\s+https?://[^\s,\"')]+.*\b(?:headline|title|main\s+(?:text|content)|page\s+text)\b)",
    re.I,
)
_STRICT_OUTPUT_ONLY_RE = re.compile(
    r"(?:\b(?:answer|reply|respond|return)\s+with\s+only\b|"
    r"\bonly\s+the\s+exact\b|"
    r"\banswer\s+with\s+exactly\b|"
    r"\breply\s+with\s+exactly\b)",
    re.I,
)
_DIRECT_FILE_WRITE_RE = re.compile(
    r"\bcreate\s+the\s+file\s+(?P<path>[A-Za-z]:\\[^\s,\"']+|/[^\s,\"']+)\s+containing\s+(?P<content>.+?)"
    r"(?=,\s*(?:then|and)\b|[.!?]\s+(?:then|and|answer|reply|respond|return|hand)\b|\s+(?:then|and)\s+\b(?:answer|reply|respond|return)\b|$)",
    re.I,
)
_DIRECT_PYTHON_RUN_RE = re.compile(
    r"\bcreate\s+(?P<path>[A-Za-z]:\\[^\s,\"']+\.py|/[^\s,\"']+\.py)\s+that\s+prints\s+(?P<expr>.+?)"
    r"\s*,\s*run\s+it\s*,\s*then\s+(?:answer|reply|respond|return)\s+with\s+only\s+the\s+printed\s+number\b",
    re.I,
)
_DIRECT_DESKTOP_FILE_FIND_RE = re.compile(
    r"\bfind\s+the\s+file\s+named\s+(?P<name>\"[^\"]+\"|'[^']+'|[A-Za-z0-9_. -]+?)\s+on\s+the\s+desktop"
    r"(?:,\s*|\s+then\s+|\s*,\s*then\s+)"
    r"(?:answer|reply|respond|return)\s+with\s+only\s+(?:the\s+)?(?:exact\s+)?(?:full\s+)?file\s+path\b",
    re.I,
)
_DIRECT_URL_HEADLINE_RE = re.compile(
    r"\bopen\s+(?P<url>https?://[^\s,\"')]+)\s+and\s+(?:answer|reply|respond|return)\s+with\s+only\s+the\s+exact\s+"
    r"(?:main\s+)?headline(?:\s+(?:text|on\s+the\s+page))?\b",
    re.I,
)
_DIRECT_URL_TITLE_RE = re.compile(
    r"\bopen\s+(?P<url>https?://[^\s,\"')]+)\s+and\s+(?:answer|reply|respond|return)\s+with\s+only\s+the\s+exact\s+"
    r"(?:page\s+title|title)\b",
    re.I,
)
_DIRECT_URL_MAIN_TEXT_RE = re.compile(
    r"\bopen\s+(?P<url>https?://[^\s,\"')]+)\s+and\s+(?:answer|reply|respond|return)\s+with\s+only\s+the\s+exact\s+"
    r"(?:main\s+(?:text|content|body|article(?:\s+text)?)|page\s+text)\b",
    re.I,
)
_DIRECT_URL_CLICK_AND_REPLY_RE = re.compile(
    r"\bopen\s+(?P<url>https?://[^\s,\"')]+)\s+and\s+click\s+(?P<label>.+?)"
    r"(?:,\s*|\s+then\s+|\s*,\s*then\s+)"
    r"(?:answer|reply|respond|return)\s+with\s+only\s+(?P<response>.+?)(?:[.!?])?\s*$",
    re.I,
)
_DIRECT_APP_OPEN_RE = re.compile(
    r"\b(?:open|launch|start)\s+(?P<app>(?!https?://)[A-Za-z0-9 ._()-]{2,80}?)"
    r"(?:,\s*|\s+then\s+|\s*,\s*then\s+)"
    r"(?:answer|reply|respond|return)\s+with\s+only\s+(?P<response>.+?)(?:[.!?])?\s*$",
    re.I,
)
_DIRECT_WEEKDAY_REMINDER_RE = re.compile(
    r"\bcreate\s+a?\s*recurring\s+weekday\s+(?P<time>\d{1,2}:\d{2}\s*(?:AM|PM))\s+local\s+reminder\s+named\s+"
    r"(?P<name>.+?)\s+that\s+shows\s+the\s+message\s+(?P<message>.+?)"
    r"(?=\.\s*(?:Do\s+it\s+now|If\s+it\s+works|If\s+it\s+fails)\b|,\s*(?:then|and)\b|$)",
    re.I,
)
_SAFE_PRINT_EXPR_RE = re.compile(r"^[0-9+\-*/%().\s]+$")
_APP_LAUNCH_TARGETS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "paint": "mspaint.exe",
    "mspaint": "mspaint.exe",
    "settings": "ms-settings:",
}


def _should_force_tool_first(prompt: str) -> bool:
    return bool(_TOOL_FIRST_PROMPT_RE.search(str(prompt or "")))


def _should_require_output_only(prompt: str) -> bool:
    return bool(_STRICT_OUTPUT_ONLY_RE.search(str(prompt or "")))


def _extract_strict_output(prompt: str, response: str, tool_outputs: list[str]) -> str:
    prompt_text = str(prompt or "")
    lowered = prompt_text.lower()
    response_text = str(response or "").strip()
    cleaned_outputs = [str(item or "").strip() for item in tool_outputs if str(item or "").strip()]

    def _last_nonempty_line(text: str) -> str:
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def _looks_like_failure(text: str) -> bool:
        lowered_text = str(text or "").strip().lower()
        if not lowered_text:
            return False
        return (
            lowered_text.startswith("fail:")
            or "error" in lowered_text
            or "failed" in lowered_text
            or "unable" in lowered_text
            or "blocker" in lowered_text
            or "timed out" in lowered_text
            or "connection failed" in lowered_text
        )

    conditional_match = re.search(
        r"\bif\s+it\s+works,\s*(?:answer|reply|respond|return)\s+with\s+only\s+(?P<success>.+?)"
        r"\.\s*if\s+it\s+fails,\s*(?:answer|reply|respond|return)\s+with\s+only\s+(?P<failure>.+?)(?:[.!?])?\s*$",
        prompt_text,
        re.I,
    )
    if conditional_match:
        success_text = _normalize_requested_reply(conditional_match.group("success"))
        failure_text = _normalize_requested_reply(conditional_match.group("failure"))
        failure_text = re.sub(r"\s+and\s+the\s+blocker\s*$", "", failure_text, flags=re.I).rstrip()
        failure_source = next(
            (
                source
                for source in [response_text, *reversed(cleaned_outputs)]
                if _looks_like_failure(source)
            ),
            "",
        )
        if failure_source:
            if failure_source.lower().startswith(failure_text.lower()):
                return failure_source
            if failure_text.endswith(":"):
                detail = failure_source.lstrip(": ").strip()
                return f"{failure_text} {detail}".rstrip()
            return failure_text
        if success_text:
            return success_text

    if "printed number" in lowered:
        tail_match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*$", response_text)
        if tail_match:
            return tail_match.group(1)
        for source in reversed(cleaned_outputs):
            line = _last_nonempty_line(source)
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", line):
                return line
        return response_text

    if "headline" in lowered:
        for source in list(reversed(cleaned_outputs)) + [response_text]:
            line = _last_nonempty_line(source)
            if line:
                sentence_parts = [
                    part.strip()
                    for part in re.split(r"(?<=[.!?])\s*(?=[A-Z0-9])", line)
                    if part.strip()
                ]
                if len(sentence_parts) > 1:
                    return sentence_parts[-1]
                return line

    if "page title" in lowered or re.search(r"\bexact\s+title\b", lowered):
        for source in list(reversed(cleaned_outputs)) + [response_text]:
            line = _last_nonempty_line(source)
            if line:
                return line

    wants_path_and_contents = (
        "path and contents" in lowered
        or "file path and contents" in lowered
        or (
            ("full file path" in lowered or "file path" in lowered)
            and "contents" in lowered
            and ("next line" in lowered or "one line" in lowered)
        )
    )
    if wants_path_and_contents:
        path_match = re.search(
            r"([A-Za-z]:\\[^\s,\"']+)",
            prompt_text,
            re.I,
        )
        if path_match is None:
            path_match = re.search(
                r"(/[^\s,\"']+)",
                prompt_text,
                re.I,
            )
        prompt_contents_match = re.search(
            r"\bcontaining\s+(.+?)(?=,\s*(?:then|and)\b|\s+(?:then|and)\s+\b(?:answer|reply|respond|return)\b|$)",
            prompt_text,
            re.I,
        )
        prompt_contents = prompt_contents_match.group(1).strip() if prompt_contents_match else ""
        contents = cleaned_outputs[-1] if cleaned_outputs else (prompt_contents or _last_nonempty_line(response_text))
        if path_match and contents:
            return f"{path_match.group(1)}\n{contents}"

    literal_match = re.search(
        r"\b(?:answer|reply|respond|return)\s+with\s+only\s+(?P<literal>[A-Za-z0-9 _-]{1,40})[.!?]?\s*$",
        prompt_text,
        re.I,
    )
    if literal_match:
        literal = _normalize_requested_reply(literal_match.group("literal"))
        if literal and not any(
            marker in literal.lower()
            for marker in ("exact", "headline", "title", "text", "path", "contents", "printed", "blocker")
        ):
            return literal

    if cleaned_outputs:
        return cleaned_outputs[-1]
    return response_text


def _normalize_target_path(raw_path: str) -> Path:
    return Path(str(raw_path or "").strip().strip('"').strip("'")).expanduser()


def _normalize_requested_content(raw_content: str) -> str:
    content = str(raw_content or "").strip()
    if content.lower().startswith("exactly "):
        content = content[8:].strip()
    return content.strip('"').strip("'")


def _normalize_requested_reply(raw_response: str) -> str:
    response = _normalize_requested_content(raw_response)
    if re.fullmatch(r"[A-Za-z0-9 _-]+[.!?]", response):
        response = response[:-1].rstrip()
    return response


def _sanitize_task_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", str(name or "").strip())
    return cleaned or "ThomasReminder"


def _parse_clock_time(raw_time: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*(AM|PM)\s*", str(raw_time or ""), re.I)
    if not match:
        raise ValueError(f"Unsupported reminder time: {raw_time}")
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = match.group(3).upper()
    if hour < 1 or hour > 12 or minute < 0 or minute > 59:
        raise ValueError(f"Unsupported reminder time: {raw_time}")
    if meridiem == "AM":
        hour = 0 if hour == 12 else hour
    else:
        hour = hour if hour == 12 else hour + 12
    return hour, minute


def _resolve_app_launch_target(app_name: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", " ", str(app_name or "").strip()).strip(" .")
    lowered = normalized.lower()
    target = _APP_LAUNCH_TARGETS.get(lowered)
    if target:
        return normalized, target
    if re.fullmatch(r"[A-Za-z0-9_. -]{2,80}", normalized):
        candidate = normalized if normalized.lower().endswith(".exe") else f"{normalized}.exe"
        return normalized, candidate
    raise ValueError(f"Unsupported app launch target: {app_name}")


def _resolve_desktop_path() -> Path:
    candidates: list[Path] = []
    home = Path.home()
    candidates.append(home / "Desktop")
    one_drive = os.environ.get("ONEDRIVE")
    if one_drive:
        candidates.append(Path(one_drive) / "Desktop")
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        candidates.append(Path(user_profile) / "Desktop")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
