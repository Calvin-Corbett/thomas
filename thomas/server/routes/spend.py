from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse

from thomas.core.cost_tracker import get_cost_tracker

router = APIRouter(prefix="/api/spend", tags=["spend"])

_ASSET_DIR = Path(__file__).resolve().parents[1] / "web"
_JS_PATH = _ASSET_DIR / "spend_widget.js"
_CSS_PATH = _ASSET_DIR / "spend_widget.css"


@router.get("/today")
def spend_today() -> dict:
    ct = get_cost_tracker()
    return {
        "total_usd": float(ct.today_usd()),
        "by_model": ct.by_model(),
        "by_model_detail": ct.today_by_model_detail(),
        "call_count": int(ct.today_call_count()),
        "tokens": ct.today_tokens(),
    }


@router.get("/session")
def spend_session() -> dict:
    ct = get_cost_tracker()
    return {
        "total_usd": float(ct.session_usd()),
        "by_model_detail": ct.session_by_model_detail(),
        "call_count": int(ct.session_call_count()),
        "tokens": ct.session_tokens(),
    }


@router.post("/session/reset")
def spend_session_reset() -> dict:
    ct = get_cost_tracker()
    ct.reset_session()
    return {"ok": True}


@router.get("/history")
def spend_history(days: int = Query(7, ge=1, le=365)) -> list[dict]:
    ct = get_cost_tracker()
    return ct.by_day(days=days)


@router.get("/pricing")
def spend_pricing() -> dict:
    ct = get_cost_tracker()
    return {"pricing": ct.pricing_table()}


@router.get("/export.csv")
def spend_export_csv(days: int = Query(30, ge=1, le=365)) -> Response:
    ct = get_cost_tracker()
    rows = ct.by_day(days=days)
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "usd"])
    for r in rows:
        w.writerow([r["date"], f"{float(r['usd']):.10f}"])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="thomas_spend_{days}d.csv"'},
    )


@router.get("/stream")
def spend_stream(request: Request) -> StreamingResponse:
    ct = get_cost_tracker()
    sub = ct.subscribe()

    def gen() -> Iterator[bytes]:
        try:
            yield b"event: hello\ndata: {}\n\n"
            while True:
                if hasattr(request, "is_disconnected") and request.is_disconnected():
                    break
                payload = sub.get(timeout_s=15.0)
                if payload is None:
                    yield b": keepalive\n\n"
                    continue
                data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
                yield f"event: spend\ndata: {data}\n\n".encode("utf-8")
        finally:
            sub.close()
            ct.unsubscribe(sub)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/widget.js")
def spend_widget_js() -> Response:
    return Response(_JS_PATH.read_text(encoding="utf-8"), media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/widget.css")
def spend_widget_css() -> Response:
    return Response(_CSS_PATH.read_text(encoding="utf-8"), media_type="text/css", headers={"Cache-Control": "no-cache"})
