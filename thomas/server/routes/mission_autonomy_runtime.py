"""Mission autonomy runtime bootstrap helpers."""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.config import AppConfig
from thomas.server.app_keys import APP_SELF_BASE_URL


def build_mission_autonomy_helpers(app: web.Application):
    """Build mission autonomy helper callables bound to the aiohttp app."""
    autonomy_bootstrap_lock = asyncio.Lock()

    def _mission_find_config() -> AppConfig | None:
        for _k, value in app.items():
            if isinstance(value, AppConfig):
                return value
        return None

    async def _mission_bootstrap_autonomy() -> bool:
        store = app.get("autonomy_store")
        engine = app.get("autonomy_engine")
        if store is not None and engine is not None:
            if not bool(getattr(engine, "is_running", False)):
                with contextlib.suppress(Exception):
                    await engine.start()
            return True

        async with autonomy_bootstrap_lock:
            store = app.get("autonomy_store")
            engine = app.get("autonomy_engine")
            if store is not None and engine is not None:
                if not bool(getattr(engine, "is_running", False)):
                    with contextlib.suppress(Exception):
                        await engine.start()
                return True

            cfg = _mission_find_config()
            if cfg is None:
                return False

            try:
                from thomas.marketplace.autonomy.adapters import ChatAdapter, ChatAdapterConfig
                from thomas.marketplace.autonomy.engine import AutonomyEngine
                from thomas.marketplace.autonomy.policy import AutonomyPolicy
                from thomas.marketplace.autonomy.scheduler import EngineTiming
                from thomas.marketplace.autonomy.store import AutonomyStore

                root = Path(getattr(getattr(cfg, "memory", None), "root_path", "") or Path("runtime") / ".thomas")
                db_path = Path(os.environ.get("THOMAS_AUTONOMY_DB_PATH") or (root / "autonomy" / "autonomy.sqlite3"))
                db_path.parent.mkdir(parents=True, exist_ok=True)
                policy_path = Path(
                    os.environ.get("THOMAS_AUTONOMY_POLICY_PATH") or (db_path.parent / "autonomy_policy.toml")
                )
                policy = AutonomyPolicy.load(str(policy_path))
                audit_key = os.environ.get("THOMAS_AUTONOMY_AUDIT_KEY")
                integrity_key = audit_key.encode("utf-8") if audit_key else None
                store = AutonomyStore(str(db_path), integrity_key=integrity_key)

                api_token = (
                    str(
                        os.environ.get("THOMAS_AUTONOMY_TOKEN")
                        or getattr(getattr(cfg, "server", None), "api_token", "")
                        or ""
                    ).strip()
                    or None
                )
                self_base_url = str(app.get(APP_SELF_BASE_URL) or "").strip()
                adapter_cfg = ChatAdapterConfig(
                    base_url=self_base_url or "http://127.0.0.1:8080",
                    api_token=api_token,
                )
                chat_adapter = ChatAdapter(app=app, cfg=adapter_cfg)
                engine = AutonomyEngine(
                    store=store,
                    policy=policy,
                    timing=EngineTiming(),
                    chat_adapter=chat_adapter,
                )
                await engine.start()
                app_state = getattr(app, "_state", None)
                if isinstance(app_state, dict):
                    app_state["autonomy_store"] = store
                    app_state["autonomy_engine"] = engine
                    app_state["autonomy_policy"] = policy
                else:
                    app["autonomy_store"] = store
                    app["autonomy_engine"] = engine
                    app["autonomy_policy"] = policy

                if not bool(app.get("_mission_autonomy_cleanup_registered")):

                    async def _cleanup_mission_autonomy(_app: web.Application) -> None:
                        runtime_engine = _app.get("autonomy_engine")
                        runtime_store = _app.get("autonomy_store")
                        if runtime_engine is not None:
                            with contextlib.suppress(Exception):
                                await runtime_engine.stop()
                        if runtime_store is not None:
                            with contextlib.suppress(Exception):
                                runtime_store.close()

                    with contextlib.suppress(Exception):
                        app.on_cleanup.append(_cleanup_mission_autonomy)
                        app_state = getattr(app, "_state", None)
                        if isinstance(app_state, dict):
                            app_state["_mission_autonomy_cleanup_registered"] = True
                        else:
                            app["_mission_autonomy_cleanup_registered"] = True

                return True
            except Exception:
                return app.get("autonomy_store") is not None and app.get("autonomy_engine") is not None

    async def _mission_require_store(*, auto_enable: bool = False) -> Any:
        store = app.get("autonomy_store")
        if store is None and auto_enable:
            await _mission_bootstrap_autonomy()
            store = app.get("autonomy_store")
        if store is None:
            raise web.HTTPNotFound(text="autonomy store is not available")
        return store

    def _mission_wakeup_engine() -> None:
        engine = app.get("autonomy_engine")
        if engine is None:
            return
        wake = getattr(engine, "wake_up", None)
        if callable(wake):
            wake()

    return _mission_bootstrap_autonomy, _mission_require_store, _mission_wakeup_engine
