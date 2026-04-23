from __future__ import annotations

import contextlib
import re
import tempfile
from pathlib import Path
from typing import Any

from thomas.core.llm import TokenUsage

_REPO_RELATIVE_PREFIX_RE = re.compile(
    r"(?<![A-Za-z]:\\)(?<!/)\b(?:runtime|tests|thomas|scripts|demo|skills|plugins|plans|docs)/[^\s\"']+",
    re.I,
)
_REPO_ROOT_FILE_RE = re.compile(
    r"\b(?:thomas\.toml|pyproject\.toml|README(?:\.[A-Za-z0-9]+)?|package\.json|package-lock\.json|pnpm-lock\.yaml|poetry\.lock|requirements(?:-dev)?\.txt|uv\.lock)\b",
    re.I,
)


def no_tools_cwd() -> str:
    root = Path(tempfile.gettempdir()) / "thomas_codex_no_tools"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def isolated_tools_cwd() -> str:
    root = Path(tempfile.gettempdir()) / "thomas_codex_tools"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def tools_cwd(text: str = "") -> str:
    prompt = str(text or "")
    repo_root = Path.cwd().resolve()
    if re.search(
        r"\b(?:repo|repository|workspace|project\s+root|current\s+(?:repo|repository|workspace|directory|folder))\b",
        prompt,
        re.I,
    ):
        return str(repo_root)
    if _REPO_RELATIVE_PREFIX_RE.search(prompt) or _REPO_ROOT_FILE_RE.search(prompt):
        return str(repo_root)

    path_match = re.search(r"([A-Za-z]:\\[^\s\"']+|/[^\s\"']+)", prompt)
    if path_match:
        raw_path = path_match.group(1)
        candidate = Path(raw_path)
        workdir = candidate if candidate.exists() and candidate.is_dir() else candidate.parent
        with contextlib.suppress(Exception):
            resolved = workdir.resolve()
            if resolved == repo_root or repo_root in resolved.parents:
                return str(repo_root)
            if resolved.exists() and resolved.is_dir():
                return str(resolved)

    return isolated_tools_cwd()


def coerce_usage(payload: Any) -> TokenUsage | None:
    if isinstance(payload, TokenUsage):
        return payload
    if not isinstance(payload, dict):
        return None

    def _pick(*keys: str) -> int | None:
        for key in keys:
            if key not in payload:
                continue
            try:
                return max(0, int(payload.get(key) or 0))
            except (TypeError, ValueError, OverflowError):
                return None
        return None

    prompt_tokens = _pick("prompt_tokens", "input_tokens", "prompt_token_count", "prompt", "input")
    completion_tokens = _pick(
        "completion_tokens",
        "output_tokens",
        "candidates_token_count",
        "completion",
        "output",
    )
    total_tokens = _pick("total_tokens", "total_token_count")

    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None

    prompt = int(prompt_tokens or 0)
    completion = int(completion_tokens or 0)
    total = int(total_tokens if total_tokens is not None else (prompt + completion))
    return TokenUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


def extract_user_text(messages: list[dict[str, Any]]) -> str:
    text = ""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    parts.append(part)
            text = "\n".join(parts)
        break
    return text


def extract_instructions(messages: list[dict[str, Any]]) -> str:
    for msg in messages:
        if msg.get("role") != "system":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""
