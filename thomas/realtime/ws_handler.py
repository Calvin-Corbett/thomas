from __future__ import annotations

import asyncio
import contextlib
from typing import Any, AsyncIterator, Optional

from aiohttp import web, WSMsgType

from .config import RealtimeConfig
from . import keys
from .protocol import parse_json_message, make, ProtocolError
from .state import ConversationState
from .telemetry import Telemetry
from .quality import QualityMetrics
from .stt_dedupe import STTDedupeWindow
from .intent import predict_intent, next_action_suggestions
from .nudges import NudgeEngine
from .stt import DisabledSTTAdapter, STTAdapter
from .utils import AsyncCancelScope, utc_ms


async def _default_pinned_goals_provider(user_id: str | None, session_id: str, state: ConversationState) -> list[dict[str, Any]]:
    return list(state.pinned_goals)


async def _default_recent_tasks_provider(user_id: str | None, session_id: str) -> list[dict[str, Any]]:
    return []


async def _http_chat_bridge(app: web.Application, payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """Fallback: call local /api/chat over loopback and stream text.

    This is a best-effort bridge to minimize integration friction when you don't want to touch internal chat plumbing.
    """
    import aiohttp
    import json as _json

    req = payload.get("_request")
    if req is None:
        raise RuntimeError("http bridge requires _request injected")  # pragma: no cover

    # Never reflect client-supplied Host back into the bridge target.
    port = int(req.url.port or (443 if str(req.scheme).lower() == "https" else 80))
    url = f"{req.scheme}://127.0.0.1:{port}/api/chat"
    body = {k: v for k, v in payload.items() if not k.startswith("_")}
    forward_headers: dict[str, str] = {}
    auth = str(req.headers.get("Authorization") or "").strip()
    if auth:
        forward_headers["Authorization"] = auth
    x_api_token = str(req.headers.get("X-Api-Token") or "").strip()
    if x_api_token:
        forward_headers["X-Api-Token"] = x_api_token

    timeout = aiohttp.ClientTimeout(total=None, sock_read=None)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.post(url, json=body, headers=forward_headers or None) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                try:
                    s = line.decode("utf-8", errors="ignore").strip()
                except Exception:
                    continue
                if not s:
                    continue
                if s.startswith("data:"):
                    s = s[5:].strip()

                if s.startswith("{") and s.endswith("}"):
                    try:
                        obj = _json.loads(s)
                        if isinstance(obj, dict):
                            if obj.get("type") in ("delta", "assistant_delta") and "text" in obj:
                                yield {"type": "delta", "text": obj["text"]}
                                continue
                            if obj.get("type") in ("done", "assistant_done"):
                                yield {"type": "done", "usage": obj.get("usage")}
                                continue
                            if "text" in obj and isinstance(obj["text"], str):
                                yield {"type": "delta", "text": obj["text"]}
                                continue
                    except Exception:
                        pass
                yield {"type": "delta", "text": s}
    yield {"type": "done"}


def _get_cfg(app: web.Application) -> RealtimeConfig:
    cfg: RealtimeConfig | None = app.get(keys.CONFIG) or app.get("realtime.config")
    if cfg is None:
        from .config import load_realtime_config
        cfg = load_realtime_config()
        app[keys.CONFIG] = cfg
    return cfg


def _get_stt_adapter(app: web.Application) -> STTAdapter:
    return app.get(keys.STT_ADAPTER) or app.get("realtime.stt_adapter") or DisabledSTTAdapter()


async def _get_chat_streamer(app: web.Application, cfg: RealtimeConfig):
    if cfg.chat_bridge == "direct" and (app.get(keys.CHAT_STREAMER) or app.get("realtime.chat_streamer")):
        return (app.get(keys.CHAT_STREAMER) or app["realtime.chat_streamer"]), "direct"
    return _http_chat_bridge, "http"


class _MetricsPacer:
    """Rate-limits metrics pushes to avoid spamming the WS."""
    def __init__(self, min_interval_ms: int = 400):
        self.min_interval_ms = min_interval_ms
        self._next_ms = 0

    def due(self) -> bool:
        now = utc_ms()
        if now >= self._next_ms:
            self._next_ms = now + self.min_interval_ms
            return True
        return False


class RealtimeSession:
    def __init__(self, *, app: web.Application, request: web.Request):
        self.app = app
        self.request = request
        self.cfg = _get_cfg(app)

        from .state import new_session_id
        self.state = ConversationState(session_id=new_session_id())
        self.telemetry = Telemetry()
        self.quality = QualityMetrics()
        self.dedupe = STTDedupeWindow(window_ms=self.cfg.stt.dedupe_window_ms)
        self.nudges = NudgeEngine(
            cooldown_sec=self.cfg.nudges.cooldown_sec,
            max_per_minute=self.cfg.nudges.max_per_minute,
            max_per_session=self.cfg.nudges.max_per_session,
        )
        self._scope = AsyncCancelScope()
        self._active_generation: asyncio.Task | None = None
        self._closed = asyncio.Event()
        self._user_id: str | None = None

        # Audio streaming (optional server-side STT)
        self._audio_mime: str = "audio/webm;codecs=opus"
        self._audio_seq: int = 0

        self._metrics = _MetricsPacer()

        # Track whether assistant is actively generating (for barge-in semantics)
        self._assistant_generating: bool = False

    async def close(self):
        await self._scope.cancel_all()
        if self._active_generation and not self._active_generation.done():
            self._active_generation.cancel()
            with contextlib.suppress(Exception):
                await self._active_generation
        self._closed.set()

    def set_mode(self, mode: str):
        self.state.mode = mode
        self.telemetry.mode = mode

    async def send_error(self, ws: web.WebSocketResponse, code: str, message: str, retryable: bool = False):
        self.telemetry.errors += 1
        await ws.send_json(make("error", code=code, message=message, retryable=retryable))

    async def send_metrics(self, ws: web.WebSocketResponse, force: bool = False):
        if not force and not self._metrics.due():
            return
        await ws.send_json(make("metrics", telemetry=self.telemetry.as_dict(), quality=self.quality.as_dict(), state=self.state.to_dict()))

    async def interrupt(self, ws: web.WebSocketResponse, reason: str = "barge_in"):
        self.telemetry.interruptions += 1
        self.quality.barge_in_events += 1

        if self._active_generation and not self._active_generation.done():
            self._active_generation.cancel()
            self.quality.assistant_canceled += 1
            self._assistant_generating = False
            await ws.send_json(make("assistant_done", usage=None, quality={"canceled": True, "reason": reason}))

        self._active_generation = None
        await self.send_metrics(ws)

    async def handle_user_text(self, ws: web.WebSocketResponse, text: str, attachments: list[dict[str, Any]] | None, mode: str | None):
        if mode:
            self.set_mode(mode)

        self.state.add_turn("user", text)
        self.telemetry.mark_user_submit()
        await self.send_metrics(ws)

        intent = predict_intent(text, context={"mode": self.state.mode})
        suggestions = next_action_suggestions(intent, context={"mode": self.state.mode})
        await ws.send_json(make("intent", intent={"name": intent.name, "confidence": intent.confidence, "slots": intent.slots or {}}, suggestions=suggestions))

        # Optional nudge
        if self.cfg.nudges.enabled:
            pg_provider = self.app.get(keys.PINNED_GOALS_PROVIDER) or self.app.get("realtime.pinned_goals_provider") or (lambda user_id, session_id: _default_pinned_goals_provider(user_id, session_id, self.state))
            rt_provider = self.app.get(keys.RECENT_TASKS_PROVIDER) or self.app.get("realtime.recent_tasks_provider") or _default_recent_tasks_provider
            pinned = await pg_provider(self._user_id, self.state.session_id)
            recent = await rt_provider(self._user_id, self.state.session_id)
            n = self.nudges.maybe_nudge(last_user_text=text, pinned_goals=pinned, recent_tasks=recent, mode=self.state.mode, quality=self.quality.as_dict())
            if n:
                self.nudges.record_sent()
                await ws.send_json(make("nudge", nudge={"title": n.title, "text": n.text, "kind": n.kind, "confidence": n.confidence}))

        # Cancel any previous generation
        await self.interrupt(ws, reason="new_user_text")

        streamer, bridge = await _get_chat_streamer(self.app, self.cfg)

        async def run_generation():
            self._assistant_generating = True
            try:
                payload = {
                    "mode": self.state.mode,
                    "messages": [{"role": "user", "content": text}],
                    "attachments": attachments or [],
                    "realtime": {"session_id": self.state.session_id},
                    "_request": self.request,  # only used by http bridge
                }

                agen = streamer(self.app, payload) if bridge == "http" else streamer(payload)  # type: ignore[misc]
                async for ev in agen:
                    if ev.get("type") == "delta" and isinstance(ev.get("text"), str):
                        self.telemetry.mark_assistant_delta()
                        await ws.send_json(make("assistant_delta", text=ev["text"]))
                        await self.send_metrics(ws)
                    elif ev.get("type") == "done":
                        self.telemetry.mark_assistant_done()
                        usage = ev.get("usage") or None
                        if isinstance(usage, dict):
                            self.telemetry.tokens_in += int(usage.get("input_tokens", 0) or 0)
                            self.telemetry.tokens_out += int(usage.get("output_tokens", 0) or 0)
                        await ws.send_json(make("assistant_done", usage=usage, quality={"canceled": False}))
                        await self.send_metrics(ws, force=True)

                self.state.add_turn("assistant", "")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await self.send_error(ws, "assistant_error", str(e), retryable=True)
                await self.send_metrics(ws, force=True)
            finally:
                self._assistant_generating = False

        self._active_generation = asyncio.create_task(run_generation())

    async def handle_stt_text(self, ws: web.WebSocketResponse, *, text: str, is_final: bool, confidence: float, seq: int, src: str, ts: int | None = None):
        dec = self.dedupe.decide(text, is_final=is_final, confidence=confidence, ts_ms=ts)
        if not dec.accept:
            self.telemetry.stt_duplicates_suppressed += 1
            self.quality.stt_duplicates += 1
            await self.send_metrics(ws)
            return

        if is_final:
            self.telemetry.mark_stt_final()

        await ws.send_json(make("stt_accepted", text=text, is_final=is_final, confidence=confidence, seq=seq, src=src, dedupe={"reason": dec.reason, "sim": dec.similarity}))
        await self.send_metrics(ws)

    async def handle_audio_begin(self, mime: str):
        self._audio_mime = mime or self._audio_mime
        self._audio_seq = 0

    async def handle_audio_chunk(self, ws: web.WebSocketResponse, data: bytes):
        if not self.cfg.stt.enabled:
            return
        adapter = _get_stt_adapter(self.app)
        self._audio_seq += 1
        try:
            res = await adapter.transcribe_chunk(data, mime=self._audio_mime, seq=self._audio_seq, meta={"session_id": self.state.session_id})
        except Exception as e:
            await self.send_error(ws, "stt_adapter", str(e), retryable=True)
            return
        if res:
            await self.handle_stt_text(ws, text=res.text, is_final=res.is_final, confidence=res.confidence, seq=res.seq, src=res.src, ts=utc_ms())

    async def handle_ping(self, ws: web.WebSocketResponse, n: int, client_ts: int | None):
        self.telemetry.ws_pings += 1
        if client_ts:
            rtt = utc_ms() - int(client_ts)
            self.telemetry.set_rtt(max(0, rtt))
        await ws.send_json(make("pong", n=n))
        await self.send_metrics(ws)


async def handle_realtime_ws(request: web.Request) -> web.StreamResponse:
    app = request.app
    cfg = _get_cfg(app)

    ws = web.WebSocketResponse(heartbeat=cfg.ws_ping_interval_sec, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)

    if not cfg.enabled:
        await ws.send_json(make("error", code="disabled", message="Realtime layer is disabled. Set runtime/.thomas/realtime.toml enabled=true.", retryable=False))
        await ws.close()
        return ws

    sess = RealtimeSession(app=app, request=request)
    sess.telemetry.mark_hello()

    await ws.send_json(make("ready", session={"id": sess.state.session_id}, server={"version": "rhai1.1"}, cfg={
        "budgets": {
            "fast": vars(cfg.budgets_fast),
            "balanced": vars(cfg.budgets_balanced),
            "deep": vars(cfg.budgets_deep),
        },
        "stt": {"enabled": cfg.stt.enabled},
        "nudges": {"enabled": cfg.nudges.enabled},
    }))
    await sess.send_metrics(ws, force=True)

    idle_timer = None
    last_activity = utc_ms()

    async def idle_watchdog():
        nonlocal last_activity
        try:
            while True:
                await asyncio.sleep(1)
                if (utc_ms() - last_activity) > (cfg.ws_idle_timeout_sec * 1000):
                    await ws.send_json(make("error", code="idle_timeout", message="Realtime session idle timeout", retryable=True))
                    await ws.close()
                    break
        except asyncio.CancelledError:
            return

    idle_timer = asyncio.create_task(idle_watchdog())

    try:
        async for msg in ws:
            last_activity = utc_ms()
            if msg.type == WSMsgType.TEXT:
                try:
                    obj = parse_json_message(msg.data)
                except ProtocolError as e:
                    await sess.send_error(ws, "protocol", str(e), retryable=False)
                    continue

                t = obj.get("t")
                if t == "hello":
                    mode = obj.get("mode") or "balanced"
                    sess.set_mode(mode)
                    await sess.send_metrics(ws, force=True)
                elif t == "text":
                    await sess.handle_user_text(ws, obj.get("text") or "", obj.get("attachments"), obj.get("mode"))
                elif t == "stt":
                    await sess.handle_stt_text(
                        ws,
                        text=str(obj.get("text") or ""),
                        is_final=bool(obj.get("is_final")),
                        confidence=float(obj.get("confidence") or 0.0),
                        seq=int(obj.get("seq") or 0),
                        src=str(obj.get("src") or "client"),
                        ts=int(obj.get("ts") or utc_ms()),
                    )
                elif t == "audio_begin":
                    await sess.handle_audio_begin(str(obj.get("mime") or "audio/webm;codecs=opus"))
                elif t == "interrupt":
                    await sess.interrupt(ws, reason=str(obj.get("reason") or "interrupt"))
                elif t == "ping":
                    await sess.handle_ping(ws, int(obj.get("n") or 0), obj.get("client_ts"))
                elif t == "telemetry":
                    kind = str(obj.get("kind") or "")
                    if kind == "audio_underrun":
                        sess.quality.audio_underruns += 1
                    elif kind == "ws_reconnect":
                        sess.quality.ws_reconnects += 1
                    await sess.send_metrics(ws, force=True)
                elif t == "pin_goal":
                    goal = obj.get("goal") or {}
                    if isinstance(goal, dict) and goal.get("title"):
                        g = {"id": goal.get("id") or f"g_{utc_ms()}", "title": str(goal["title"]), "details": str(goal.get("details") or "")}
                        sess.state.pinned_goals.insert(0, g)
                        await ws.send_json(make("pin_goal_ok", goal=g))
                        await sess.send_metrics(ws, force=True)
                elif t == "unpin_goal":
                    gid = str(obj.get("goal_id") or "")
                    if gid:
                        sess.state.pinned_goals = [g for g in sess.state.pinned_goals if str(g.get("id")) != gid]
                        await ws.send_json(make("unpin_goal_ok", goal_id=gid))
                        await sess.send_metrics(ws, force=True)
                else:
                    await sess.send_error(ws, "unknown", f"Unknown message type: {t}", retryable=False)

            elif msg.type == WSMsgType.BINARY:
                # Binary audio chunk for server-side STT fallback (optional)
                await sess.handle_audio_chunk(ws, msg.data)

            elif msg.type == WSMsgType.ERROR:
                break

    finally:
        if idle_timer and not idle_timer.done():
            idle_timer.cancel()
            with contextlib.suppress(Exception):
                await idle_timer
        await sess.close()
        await ws.close()

    return ws
