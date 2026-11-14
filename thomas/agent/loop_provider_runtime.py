"""Provider connection diagnostics and prompt-rate window calculations."""

from __future__ import annotations

import logging
import time
from typing import Any

TPM_WINDOW_SECONDS = 60.0
TPM_WAIT_SLICE_SECONDS = 20.0

log = logging.getLogger(__name__)


class ProviderPromptWindow:
    """Mutable rolling prompt-token window used by a single agent run."""

    def __init__(self, prompt_budget: int) -> None:
        self.prompt_budget = max(0, int(prompt_budget))
        self.entries: list[tuple[float, int]] = []

    def prune(self, now_ts: float | None = None) -> None:
        prune_prompt_window(self.entries, time.monotonic() if now_ts is None else now_ts)

    def projected_wait_seconds(self, next_prompt_tokens: int) -> tuple[float, int, int]:
        now_ts = time.monotonic()
        self.prune(now_ts)
        return projected_wait_seconds(
            self.entries,
            prompt_budget=self.prompt_budget,
            next_prompt_tokens=next_prompt_tokens,
            now_ts=now_ts,
        )

    def record(self, tokens: int) -> int:
        self.entries.append((time.monotonic(), int(tokens)))
        self.prune()
        return self.token_total()

    def token_total(self) -> int:
        return sum(max(0, int(tokens)) for _, tokens in self.entries)

    def observed_average(self) -> int:
        return int(self.token_total() / max(1, len(self.entries)))


async def compact_conversation_if_needed(
    agent: Any,
    *,
    preserve_last: int,
    setup: Any = None,
) -> dict[str, int] | None:
    """Run optional auto-compaction without allowing it to fail the turn."""
    try:
        hard_cap = agent._context_window
        if setup is not None:
            hard_cap = agent._request_message_budget(setup.tool_specs)
            if setup.history_token_cap > 0:
                hard_cap = min(hard_cap, setup.history_token_cap)
        result = await agent._auto_compact_if_needed(
            hard_cap=hard_cap,
            threshold=0.70,
            preserve_recent=max(preserve_last, 8),
        )
        if result:
            if result["tokens_saved"] > 0:
                log.info(
                    "Auto-compacted conversation: %d -> %d tokens (saved %d)",
                    result["original_tokens"],
                    result["compacted_tokens"],
                    result["tokens_saved"],
                )
            else:
                log.info("Auto-compaction was due at %d tokens but found nothing it could compact", hard_cap)
        return result
    except Exception as exc:  # REVIEWED: compaction is optional and must not break a turn
        log.debug("Auto-compaction check failed (non-fatal): %s", exc)


def connection_error_message(llm: Any) -> str:
    """Name the provider that actually dropped the connection."""
    cfg = getattr(llm, "config", None)
    base_url = str(getattr(cfg, "base_url", "") or "").strip()
    provider = str(getattr(cfg, "provider", "") or "").strip()
    model = str(getattr(cfg, "model", "") or "").strip()
    target = base_url or provider or model or "the configured model provider"
    message = f"Lost the connection to {target} mid-run (network drop or expired login)."
    if base_url and ("localhost" in base_url or "127.0.0.1" in base_url):
        message += " If this is a local Ollama endpoint, check: ollama serve"
    return message


def prune_prompt_window(prompt_window: list[tuple[float, int]], now_ts: float) -> None:
    """Discard prompt-token observations outside the active TPM window."""
    cutoff = now_ts - TPM_WINDOW_SECONDS
    prompt_window[:] = [(ts, tok) for ts, tok in prompt_window if ts >= cutoff]


def projected_wait_seconds(
    prompt_window: list[tuple[float, int]],
    *,
    prompt_budget: int,
    next_prompt_tokens: int,
    now_ts: float,
) -> tuple[float, int, int]:
    """Return wait time, projected usage, and current rolling prompt usage."""
    if prompt_budget <= 0:
        return 0.0, 0, 0
    prune_prompt_window(prompt_window, now_ts)
    current_prompt = sum(max(0, int(tok)) for _, tok in prompt_window)
    projected_prompt = current_prompt + max(0, int(next_prompt_tokens))
    if projected_prompt <= prompt_budget:
        return 0.0, projected_prompt, current_prompt

    running_prompt = current_prompt
    wait_s = TPM_WINDOW_SECONDS
    for timestamp, tokens in prompt_window:
        running_prompt -= max(0, int(tokens))
        if running_prompt + max(0, int(next_prompt_tokens)) <= prompt_budget:
            wait_s = max(0.25, TPM_WINDOW_SECONDS - (now_ts - timestamp))
            break
    return wait_s, projected_prompt, current_prompt
