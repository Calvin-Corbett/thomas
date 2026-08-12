"""Token-usage receipts for the Chat V2 event stream."""

from __future__ import annotations

from typing import Any

from thomas.server.routes.chat_v2_keys import APP_SESSION_LLM_CACHE


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (OverflowError, TypeError, ValueError):
        return 0


def _normalize_usage(usage: Any, *, minimum_total: Any = 0) -> dict[str, int]:
    if isinstance(usage, dict):
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
    else:
        prompt = getattr(usage, "prompt_tokens", 0)
        completion = getattr(usage, "completion_tokens", 0)
        total = getattr(usage, "total_tokens", 0)
    prompt_count = _nonnegative_int(prompt)
    completion_count = _nonnegative_int(completion)
    total_count = _nonnegative_int(total)
    return {
        "prompt_tokens": prompt_count,
        "completion_tokens": completion_count,
        "total_tokens": max(total_count, prompt_count + completion_count, _nonnegative_int(minimum_total)),
    }


def _usage_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return _normalize_usage(
        {
            "prompt_tokens": after["prompt_tokens"] - before["prompt_tokens"],
            "completion_tokens": after["completion_tokens"] - before["completion_tokens"],
            "total_tokens": after["total_tokens"] - before["total_tokens"],
        }
    )


def terminal_usage_fields(
    *,
    run_usage: Any = None,
    session_usage: Any = None,
    minimum_session_total: Any = 0,
) -> dict[str, dict[str, int]]:
    """Build the normalized usage contract shared by every V2 terminal event."""
    run = _normalize_usage(run_usage)
    session = _normalize_usage(
        session_usage,
        minimum_total=max(_nonnegative_int(minimum_session_total), run["total_tokens"]),
    )
    return {"usage": run, "run_usage": run, "session_usage": session}


def session_usage_for_session(app: Any, session_id: str, *, persisted_total: Any = 0) -> dict[str, int]:
    """Read cached provider totals while retaining the durable session-total floor."""
    cache = app.get(APP_SESSION_LLM_CACHE, {})
    entry = cache.get(session_id) if isinstance(cache, dict) else None
    llm = getattr(entry, "llm", None)
    return _normalize_usage(getattr(llm, "session_usage", None), minimum_total=persisted_total)


class UsageReceiptDispatcher:
    """Enrich ``done`` events with per-turn and cumulative token receipts."""

    def __init__(
        self,
        dispatcher: Any,
        llm: Any,
        *,
        prior_session_tokens: Any = 0,
        token_economy: dict[str, str] | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._llm = llm
        self._prior_session_tokens = _nonnegative_int(prior_session_tokens)
        self._token_economy = dict(token_economy or {})
        self._usage_before = self._session_usage()
        self.run_usage = _normalize_usage(None)

    def _session_usage(self) -> dict[str, int]:
        return _normalize_usage(getattr(self._llm, "session_usage", None))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._dispatcher, name)

    async def emit_route(self, *, mode: str, autonomy_level: int) -> None:
        """Emit the canonical Chat V2 entry route with its turn controls."""
        await self._dispatcher.emit(
            {
                "type": "route",
                "route": {"path": "orchestrator", "confidence": 1.0},
                "mode": mode,
                "token_economy": dict(self._token_economy),
                "autonomy_level": autonomy_level,
            }
        )

    async def emit_done(self, *args: Any, **kwargs: Any) -> None:
        raw_session_usage = self._session_usage()
        run_usage = _usage_delta(self._usage_before, raw_session_usage)
        usage_fields = terminal_usage_fields(
            run_usage=run_usage,
            session_usage=raw_session_usage,
            minimum_session_total=self._prior_session_tokens + run_usage["total_tokens"],
        )
        self.run_usage = run_usage
        kwargs.update(usage_fields)
        kwargs["tokens_used"] = max(_nonnegative_int(kwargs.get("tokens_used")), run_usage["total_tokens"])
        if self._token_economy:
            kwargs["token_economy"] = dict(self._token_economy)
            raw_token_report = kwargs.get("token_report")
            token_report = dict(raw_token_report) if isinstance(raw_token_report, dict) else {}
            token_report["token_economy"] = dict(self._token_economy)
            kwargs["token_report"] = token_report
        await self._dispatcher.emit_done(*args, **kwargs)


__all__ = ["UsageReceiptDispatcher", "session_usage_for_session", "terminal_usage_fields"]
