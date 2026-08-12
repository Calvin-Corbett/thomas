"""Scheduled-task and realtime-interruption parity probes."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def scheduled_task_lifecycle_probe(_ctx: Any) -> tuple[bool, str]:
    """Exercise the production scheduler lifecycle without leaving a real task behind."""
    from thomas.core.scheduler import TaskScheduler

    task_id = f"parity-schedule-{int(time.time() * 1000)}"
    notifications: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="thomas-parity-schedule-") as temp_dir:
        schedule_path = Path(temp_dir) / "schedules.json"

        def notify(goal: str, channel: str) -> None:
            notifications.append({"goal": goal, "channel": channel})

        scheduler = TaskScheduler(notify, schedule_path=schedule_path, auto_start=False)
        try:
            scheduler.add_task(task_id, "every 15 minutes", "PARITY-SCHEDULE-CREATED", "parity-notifications")
            created = scheduler.list_tasks()
            scheduler.run_now(task_id)
            deadline = time.monotonic() + 5.0
            fired: list[dict[str, Any]] = []
            while time.monotonic() < deadline:
                fired = scheduler.list_tasks()
                history = fired[0].get("run_history", []) if fired else []
                if notifications and history:
                    break
                time.sleep(0.02)
            scheduler.pause_task(task_id)
            paused = scheduler.list_tasks()
            scheduler.update_task(
                task_id,
                cron="every hour",
                task="PARITY-SCHEDULE-UPDATED",
                channel="parity-updated",
                misfire_policy="skip",
                misfire_grace_s=30,
            )
            updated = scheduler.list_tasks()
            scheduler.resume_task(task_id)
            resumed = scheduler.list_tasks()
            scheduler.remove_task(task_id)
            deleted = scheduler.list_tasks()
        finally:
            scheduler.stop()
        persisted = json.loads(schedule_path.read_text(encoding="utf-8")) if schedule_path.is_file() else []

    created_row = created[0] if created else {}
    fired_row = fired[0] if fired else {}
    paused_row = paused[0] if paused else {}
    updated_row = updated[0] if updated else {}
    resumed_row = resumed[0] if resumed else {}
    history = fired_row.get("run_history", []) if isinstance(fired_row, dict) else []
    passed = bool(
        created_row.get("id") == task_id
        and created_row.get("cron") == "*/15 * * * *"
        and notifications == [{"goal": "PARITY-SCHEDULE-CREATED", "channel": "parity-notifications"}]
        and history
        and history[-1].get("ok") is True
        and paused_row.get("status") == "paused"
        and updated_row.get("status") == "paused"
        and updated_row.get("cron") == "0 * * * *"
        and updated_row.get("task") == "PARITY-SCHEDULE-UPDATED"
        and updated_row.get("channel") == "parity-updated"
        and updated_row.get("misfire_policy") == "skip"
        and resumed_row.get("status") == "active"
        and resumed_row.get("next_run")
        and deleted == []
        and isinstance(persisted, dict)
        and persisted.get("tasks") == []
    )
    actual = {
        "task_id": task_id,
        "notifications": notifications,
        "created": created_row,
        "fired_history": history,
        "paused": paused_row,
        "updated": updated_row,
        "resumed": resumed_row,
        "deleted": deleted,
        "persisted_after_cleanup": persisted,
    }
    return passed, json.dumps(actual, ensure_ascii=False)


def scheduled_recovery_dedup_noise_probe(_ctx: Any) -> tuple[bool, str]:
    """Prove unique catch-up, clock rollback safety, durable skip, and useful-only alerts."""
    from thomas.core.scheduler import TaskScheduler
    from thomas.notify._types import Category, ChannelType, Notification, Recipient
    from thomas.notify.routing import DeduplicationEngine

    class Clock:
        def __init__(self, start: datetime) -> None:
            self.value = start

        def now(self) -> datetime:
            return self.value

        def advance(self, delta: timedelta) -> None:
            self.value += delta

    def wait_for_history(scheduler: TaskScheduler, count: int) -> list[dict[str, Any]]:
        deadline = time.monotonic() + 3.0
        history: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            rows = scheduler.list_tasks()
            history = list(rows[0].get("run_history", [])) if rows else []
            if len(history) >= count:
                break
            time.sleep(0.01)
        return history

    with tempfile.TemporaryDirectory(prefix="thomas-parity-schedule-adversarial-") as temp_dir:
        temp = Path(temp_dir)
        clock = Clock(datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))
        invocations: list[str] = []
        delivered: list[str] = []
        suppressed: list[str] = []
        callback_lock = threading.Lock()
        dedupe = DeduplicationEngine(window=timedelta(minutes=5))
        recipient = Recipient(user_id="parity-monitor", email="parity@example.test")

        def monitor(goal: str, channel: str) -> None:
            with callback_lock:
                invocations.append(f"{goal}:{channel}")
                template_id = "parity-monitor-stable" if len(invocations) <= 2 else "parity-monitor-changed"
                notification = Notification(
                    recipient=recipient,
                    template_id=template_id,
                    channel_type=ChannelType.EMAIL,
                    category=Category.UPDATES,
                )
                if dedupe.is_duplicate(notification):
                    suppressed.append(template_id)
                else:
                    dedupe.mark_sent(notification)
                    delivered.append(template_id)

        schedule_path = temp / "catch_up.json"
        scheduler = TaskScheduler(
            monitor,
            schedule_path=schedule_path,
            now_fn=clock.now,
            catch_up_limit=2,
            max_workers=1,
            auto_start=False,
        )
        try:
            scheduler.add_task("monitor", "* * * * *", "CHECK-MONITOR", "alerts")
            clock.advance(timedelta(minutes=5))
            scheduler._poll_once()
            catch_up_history = wait_for_history(scheduler, 2)
            catch_up_slots = [str(row.get("scheduled_for") or "") for row in catch_up_history]

            scheduler._poll_once()
            time.sleep(0.05)
            duplicate_poll_count = len(scheduler.list_tasks()[0].get("run_history", []))

            clock.advance(timedelta(minutes=-10))
            scheduler._poll_once()
            time.sleep(0.05)
            rollback_count = len(scheduler.list_tasks()[0].get("run_history", []))

            clock.advance(timedelta(minutes=11))
            scheduler._poll_once()
            final_history = wait_for_history(scheduler, 3)
            final_slots = [str(row.get("scheduled_for") or "") for row in final_history]
        finally:
            scheduler.stop()

        skip_clock = Clock(datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc))
        skip_invocations: list[str] = []
        skip_path = temp / "skip.json"
        skip_scheduler = TaskScheduler(
            lambda goal, channel: skip_invocations.append(f"{goal}:{channel}"),
            schedule_path=skip_path,
            now_fn=skip_clock.now,
            auto_start=False,
        )
        reloaded: TaskScheduler | None = None
        try:
            skip_scheduler.add_task("skip", "* * * * *", "SKIP-STALE", "alerts")
            skip_scheduler.update_task("skip", misfire_policy="skip", misfire_grace_s=5)
            skip_clock.advance(timedelta(minutes=5))
            skip_scheduler._poll_once()
            persisted = json.loads(skip_path.read_text(encoding="utf-8"))
            persisted_next = str(persisted["tasks"][0].get("next_run_at") or "")
            reloaded = TaskScheduler(
                lambda goal, channel: skip_invocations.append(f"reload:{goal}:{channel}"),
                schedule_path=skip_path,
                now_fn=skip_clock.now,
                auto_start=False,
            )
            reloaded_next = str(reloaded.list_tasks()[0].get("next_run") or "")
        finally:
            skip_scheduler.stop()
            if reloaded is not None:
                reloaded.stop()

    unique_catch_up = len(catch_up_slots) == 2 and len(set(catch_up_slots)) == 2
    clock_rollback_safe = duplicate_poll_count == 2 and rollback_count == 2 and len(final_slots) == 3
    unique_final_slots = len(final_slots) == len(set(final_slots))
    noise_suppressed = delivered == ["parity-monitor-stable", "parity-monitor-changed"] and suppressed == [
        "parity-monitor-stable"
    ]
    skipped_durably = (
        not skip_invocations and persisted_next.startswith("2026-07-13T12:06:00") and reloaded_next == persisted_next
    )
    passed = bool(
        unique_catch_up and clock_rollback_safe and unique_final_slots and noise_suppressed and skipped_durably
    )
    actual = {
        "catch_up_slots": catch_up_slots,
        "unique_catch_up": unique_catch_up,
        "duplicate_poll_count": duplicate_poll_count,
        "rollback_count": rollback_count,
        "final_slots": final_slots,
        "clock_rollback_safe": clock_rollback_safe,
        "unique_final_slots": unique_final_slots,
        "monitor_invocations": invocations,
        "delivered": delivered,
        "suppressed": suppressed,
        "noise_suppressed": noise_suppressed,
        "skip_invocations": skip_invocations,
        "persisted_next": persisted_next,
        "reloaded_next": reloaded_next,
        "skipped_durably": skipped_durably,
    }
    return passed, json.dumps(actual, ensure_ascii=False)


def _realtime_interrupt_receipt() -> dict[str, Any]:
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    from thomas.marketplace.realtime import keys
    from thomas.marketplace.realtime.config import RealtimeConfig
    from thomas.marketplace.realtime.ws_handler import RealtimeSession

    class _WebSocket:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        async def send_json(self, payload: dict[str, Any]) -> None:
            self.events.append(dict(payload))

    async def _exercise() -> dict[str, Any]:
        async def _slow_streamer(_payload: dict[str, Any]):
            yield {"type": "delta", "text": "begin"}
            await asyncio.sleep(5)
            yield {"type": "delta", "text": "should-not-arrive"}
            yield {"type": "done"}

        app = web.Application()
        app[keys.CONFIG] = RealtimeConfig(enabled=True, chat_bridge="direct")
        app[keys.CHAT_STREAMER] = _slow_streamer
        request = make_mocked_request("GET", "/api/realtime/ws", app=app)
        ws = _WebSocket()
        session = RealtimeSession(app=app, request=request)
        await session.handle_user_text(ws, "hello", None, "balanced")
        for _ in range(50):
            if any(event.get("t") == "assistant_delta" for event in ws.events):
                break
            await asyncio.sleep(0.01)
        started = time.perf_counter()
        await session.interrupt(ws, reason="barge_in")
        interrupt_ms = round((time.perf_counter() - started) * 1000)
        await session.close()
        done = [event for event in ws.events if event.get("t") == "assistant_done"]
        return {
            "interrupt_ms": interrupt_ms,
            "canceled": bool(done and done[-1].get("quality", {}).get("canceled")),
            "barge_in_events": session.quality.barge_in_events,
            "assistant_canceled": session.quality.assistant_canceled,
            "late_delta_seen": any("should-not-arrive" in str(event) for event in ws.events),
        }

    return asyncio.run(_exercise())
