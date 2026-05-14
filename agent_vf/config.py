from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class LLMConfig:
    # OpenAI-compatible REST endpoint (works with local servers too)
    base_url: str = "http://127.0.0.1:8001/v1"
    api_key: str = "local"
    model: str = "gpt-4.1-mini"
    timeout_s: float = 90.0
    temperature: float = 0.2
    max_tokens: int = 900

@dataclass
class AppConfig:
    root: Path = Path("./runtime")
    thread: str = "default"
    mode: str = "auto"  # fast, deep, learning, auto, no_memory
    llm: LLMConfig = field(default_factory=LLMConfig)
    tool_allowlist: list[str] = field(default_factory=lambda: ["fs.read", "fs.write", "web.open", "browser.playwright"])
    safety: dict[str, Any] = field(default_factory=lambda: {
        "fs_root": "./sandbox_files",
        "deny_network": False,
    })
