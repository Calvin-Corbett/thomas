from __future__ import annotations

from typing import Any

try:
    from aiohttp.web import AppKey  # aiohttp >= 3.9
except Exception:  # pragma: no cover
    AppKey = None  # type: ignore


def _k(name: str):
    if AppKey is None:
        return name
    # type is intentionally Any to avoid importing dataclasses here (prevents cycles)
    return AppKey(name, Any)  # type: ignore[arg-type]


CONFIG = _k("realtime.config")
CHAT_STREAMER = _k("realtime.chat_streamer")
STT_ADAPTER = _k("realtime.stt_adapter")
PINNED_GOALS_PROVIDER = _k("realtime.pinned_goals_provider")
RECENT_TASKS_PROVIDER = _k("realtime.recent_tasks_provider")
REQUIRE_API_ACCESS = _k("realtime.require_api_access")
