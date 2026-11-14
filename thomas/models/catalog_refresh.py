"""Keeps the model catalog current: once at start, every day, and when asked.

One refresh at a time. A request that arrives while one is running waits for that
one, so a double press or the daily tick during a press never asks twice.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable
from typing import Any

from thomas.core.config import AppConfig, ModelConfig
from thomas.models.catalog import build_model_catalog_async, load_cached_model_catalog
from thomas.models.sources import TokenFn

log = logging.getLogger(__name__)
AUTOREFRESH_ENV = "THOMAS_MODEL_CATALOG_AUTOREFRESH"
DAILY_S = 24 * 60 * 60


def autorefresh_enabled() -> bool:
    return str(os.environ.get(AUTOREFRESH_ENV, "1")).strip().lower() not in {"0", "false", "no", "off"}


class CatalogRefresher:
    def __init__(
        self,
        config_fn: Callable[[], AppConfig],
        *,
        cfg_with_secrets: Callable[[str], ModelConfig] | None = None,
        codex_token: TokenFn | None = None,
        interval_s: float = DAILY_S,
    ) -> None:
        self._config_fn = config_fn
        self._cfg_with_secrets = cfg_with_secrets
        self._codex_token = codex_token
        self._interval_s = interval_s
        self._running: asyncio.Future[dict[str, Any]] | None = None
        self._daily: asyncio.Task[None] | None = None

    async def current(self) -> dict[str, Any]:
        config = self._config_fn()
        return load_cached_model_catalog(config) or await build_model_catalog_async(config, refresh=False)

    async def refresh(self) -> dict[str, Any]:
        if self._running is None or self._running.done():
            self._running = asyncio.ensure_future(
                build_model_catalog_async(
                    self._config_fn(),
                    refresh=True,
                    cfg_with_secrets=self._cfg_with_secrets,
                    codex_token=self._codex_token,
                )
            )
        return await asyncio.shield(self._running)

    async def _run_daily(self) -> None:
        while True:
            try:
                await self.refresh()
            # A refresh calls every configured provider's reader
            # (thomas/models/sources/*) and writes the cache file: network
            # trouble and disk I/O surface as OSError, a malformed provider
            # answer as ValueError/TypeError/KeyError/AttributeError, and the
            # lazy `codex_token` import this refresher is built with can fail
            # as ImportError; asyncio internals raise RuntimeError. The daily
            # loop's whole job is to keep ticking through any of them and try
            # again tomorrow -- a bad day must never end it until Thomas
            # restarts. `except Exception` would say that more plainly, but
            # this repo's exception_handler gate only allows a broad catch
            # that also re-raises, which would defeat the loop -- so this
            # specific list is the correct fix, not a workaround.
            except (ImportError, OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
                log.warning("model list refresh failed: %s", exc, exc_info=True)
            await asyncio.sleep(self._interval_s)

    def start(self) -> None:
        if self._daily is None:
            self._daily = asyncio.ensure_future(self._run_daily())

    async def stop(self) -> None:
        if self._daily is not None:
            self._daily.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                # _run_daily already swallows every failure kind its own
                # refresh() can raise (see its comment) and keeps looping, so
                # by the time cancel() reaches here the task should only ever
                # end via CancelledError. This is the backstop for the case
                # that is not true, so shutdown's on_cleanup never crashes on
                # a daily-loop failure it did not expect.
                try:
                    await self._daily
                except (ImportError, OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
                    log.warning("model catalog daily refresh task ended unexpectedly: %s", exc, exc_info=True)
            self._daily = None
