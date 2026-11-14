"""The model-written paragraph of a BootDoctor report: which profile writes it and what it is told."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from thomas.core.config import AppConfig, ModelConfig
from thomas.core.llm import LLMClient
from thomas.core.llm_slot import models

# (folder that holds the secret store, profile name) -> the stored API key, if any. The entry point hands this in:
# the store lives in thomas.server, which thomas.core may not import.
SecretLookup = Callable[[Path, str], "str | None"]

# What a damaged secret file can raise. SecretStore guards its own parsing with this set, yet its first read of the
# file sits outside that guard, so a secrets.json holding `[]` still raises AttributeError. BootDoctor runs when state
# is broken, so a best-effort key lookup must never be able to stop it. SyntaxError is a broken module on import.
LOOKUP_ERRORS = (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError, SyntaxError)


def best_model_profile(config: AppConfig) -> str | None:
    if not config.models:
        return None

    def score(name: str, model_cfg: ModelConfig) -> float:
        model_text = f"{name} {model_cfg.model}".lower()
        value = 0.0
        keywords = {
            "gpt-5": 120.0,
            "o3": 110.0,
            "o1": 100.0,
            "gpt-4.1": 95.0,
            "claude-3.7": 100.0,
            "claude-3.5": 90.0,
            "opus": 95.0,
            "sonnet": 85.0,
            "gemini": 85.0,
            "deepseek-r1": 90.0,
        }
        for token, bonus in keywords.items():
            if token in model_text:
                value = max(value, bonus)
        value += min(30.0, float(max(0, int(model_cfg.context_window or 0))) / 4096.0)
        if str(model_cfg.provider or "").strip().lower() not in {"local"}:
            value += 5.0
        if name == config.default_model:
            value += 3.0
        return value

    ranked = sorted(config.models.items(), key=lambda it: score(it[0], it[1]), reverse=True)
    return ranked[0][0] if ranked else None


def model_cfg_with_secret(config: AppConfig, profile: str, secret_lookup: SecretLookup | None) -> ModelConfig:
    model_cfg = config.get_model(profile)
    if str(model_cfg.api_key or "").strip():
        return model_cfg
    if secret_lookup is None:
        return model_cfg
    try:
        key = str(secret_lookup(config.memory.root_path / ".thomas", profile) or "").strip()
    except LOOKUP_ERRORS:
        return model_cfg
    return replace(model_cfg, api_key=key) if key else model_cfg


def hide_home_folder(text: str) -> str:
    """Write ``~`` where your home folder is, so your account name is not in what the model is sent.

    The findings carry file paths and the end of the startup log. Only the home folder's own path is replaced, in
    any spelling a path or a log line gives it (either slash, doubled backslashes, any letter case). A sibling
    folder whose name merely starts the same way is left alone.
    """
    try:
        home = str(Path.home())
    except (OSError, RuntimeError, KeyError):
        return text
    spellings = {home, home.replace("\\", "/"), home.replace("/", "\\"), home.replace("/", "\\").replace("\\", "\\\\")}
    for spelling in sorted((s for s in spellings if s.strip("/\\")), key=len, reverse=True):
        text = re.sub(re.escape(spelling) + r"(?![\w-])", "~", text, flags=re.IGNORECASE)
    return text


async def ai_boot_summary(
    *,
    model_cfg: ModelConfig,
    reason: str,
    findings: list[Any],
    repairs: list[str],
) -> str:
    llm = models().open(model_cfg, default=LLMClient, failover_enabled=False)
    try:
        findings_text = "\n".join(f"- [{row.status}] {row.check}: {row.detail}" for row in findings) or "- none"
        repairs_text = "\n".join(f"- {x}" for x in repairs) or "- none"
        prompt = hide_home_folder(
            "You are Thomas Boot Doctor analyst.\n"
            "Given startup diagnostics, provide a concise root-cause hypothesis and "
            "next actions.\n\n"
            f"Reason:\n{reason}\n\n"
            f"Findings:\n{findings_text}\n\n"
            f"Repairs attempted:\n{repairs_text}\n\n"
            "Respond with:\n"
            "1) likely_root_cause\n"
            "2) confidence\n"
            "3) next_steps (3 bullets max)\n"
        )
        messages = [
            {"role": "system", "content": "Be precise, short, and operational."},
            {"role": "user", "content": prompt},
        ]
        chunks: list[str] = []
        stream_obj = llm.stream_chat(messages, tools=None)
        if inspect.isawaitable(stream_obj):
            stream_obj = await stream_obj
        if not hasattr(stream_obj, "__aiter__"):
            raise RuntimeError("LLM boot summary stream is not async iterable")

        async for event in stream_obj:
            if event.type == "token":
                chunks.append(str((event.data or {}).get("text") or ""))
            elif event.type == "error":
                raise RuntimeError(str((event.data or {}).get("error") or "LLM error"))
        text = "".join(chunks).strip()
        if not text:
            raise RuntimeError("empty AI summary")
        return text
    finally:
        await llm.close()
