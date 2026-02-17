from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Optional

from aiohttp import web

from .api import register_autonomy_routes
from .adapters import ChatAdapter, ChatAdapterConfig
from .engine import AutonomyEngine
from .policy import AutonomyPolicy
from .scheduler import EngineTiming, compute_next_run
from .store import AutonomyStore


def _default_db_path(config: object) -> str:
    # Try common Thomas config shapes; fall back to runtime/.thomas
    root = None
    for attr in ("memory", "config"):
        obj = getattr(config, attr, None)
        if obj is not None:
            for a2 in ("root_path", "root", "path"):
                root = getattr(obj, a2, None)
                if root:
                    break
        if root:
            break
    if not root:
        root = os.path.join("runtime", ".thomas")
    return os.path.join(str(root), "autonomy", "autonomy.sqlite3")


def install_autonomy(
    app: web.Application,
    config: object,
    *,
    enabled: bool = True,
    db_path: Optional[str] = None,
    policy_path: Optional[str] = None,
    api_token: Optional[str] = None,
    timing: EngineTiming = EngineTiming(),
    chat_adapter=None,
) -> Optional[AutonomyEngine]:
    """Install Autonomy Engine into an aiohttp app.

    The engine is stored in:
        app["autonomy_engine"]

    And the store in:
        app["autonomy_store"]
    """

    if not enabled:
        return None

    db_path = db_path or _default_db_path(config)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    if not policy_path:
        policy_path = os.path.join(os.path.dirname(db_path), "autonomy_policy.toml")

    policy = AutonomyPolicy.load(policy_path)

    # Optional HMAC key for a tamper-evident audit chain
    integrity_key = None
    env_key = os.environ.get("THOMAS_AUTONOMY_AUDIT_KEY")
    if env_key:
        integrity_key = env_key.encode("utf-8")

    store = AutonomyStore(db_path, integrity_key=integrity_key)
    # Best-effort default chat adapter: prefer an in-process hook if Thomas provides
    # app["chat_submit_json"], otherwise loop back to /api/chat.
    if chat_adapter is None:
        chat_adapter = ChatAdapter(app=app, cfg=ChatAdapterConfig(api_token=api_token))

    engine = AutonomyEngine(store=store, policy=policy, timing=timing, chat_adapter=chat_adapter)

    register_autonomy_routes(app, engine=engine, store=store, policy=policy, api_token=api_token)

    async def on_startup(_app: web.Application):
        await engine.start()

        # Seed a daily briefing job if none exists (idempotent-ish by kind check).
        existing = [j for j in store.list_jobs(kind="daily_briefing", limit=5)]
        if not existing:
            schedule = {"type": "daily", "at": "08:00", "tz": "America/Chicago"}
            next_run = compute_next_run(schedule, datetime.now(timezone.utc))
            store.create_job(
                name="Daily Briefing",
                kind="daily_briefing",
                payload={},
                schedule=schedule,
                next_run_at=next_run,
                risk_class="low",
            )
            engine.wake_up()

    async def on_cleanup(_app: web.Application):
        await engine.stop()
        store.close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    app["autonomy_engine"] = engine
    app["autonomy_store"] = store
    app["autonomy_policy"] = policy
    return engine
