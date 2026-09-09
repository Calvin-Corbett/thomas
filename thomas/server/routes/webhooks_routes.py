# thomas/server/routes/webhooks_routes.py
"""HTTP route handlers for webhook management and receiving."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import uuid
from typing import Any

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, Field

from thomas.server.routes.webhooks import (
    _INBOX,
    _RATE_LIMITER,
    _RECEIPTS,
    _STATS,
    _STORE,
    DEFAULT_RATE_LIMIT_PER_MIN,
    INBOX_BODY_MAX_BYTES,
    INBOX_STORE_BODY,
    MAX_COMMITS_INCLUDED,
    STORE_RAW_PAYLOAD,
    STRIPE_TOLERANCE_SECONDS,
    WebhookRecord,
    _client_ip,
    _emit_event,
    _now_iso,
    _payload_string,
    _queue_goal,
    _read_body_limited,
    _require_admin,
    _require_generic_secret_for_signature_enforcement,
    _require_json_object,
    _require_provider_secrets_for_signature_enforcement,
    _split_secrets,
    _unix_now,
    _webhook_signature_enforcement_enabled,
    webhook_router,
)
from thomas.server.routes.webhooks_delivery import (
    WebhookDeliveryDeps,
    inbox_retry_impl,
    receive_github_webhook_impl,
    receive_stripe_webhook_impl,
    receive_webhook_impl,
    test_webhook_impl,
)


def _hmac_sha256_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _normalize_sig(sig_header: str) -> tuple[str | None, str]:
    sig_header = (sig_header or "").strip()
    if "=" in sig_header:
        algo, hexsig = sig_header.split("=", 1)
        return algo.strip().lower(), hexsig.strip().lower()
    return None, sig_header.lower()


def _validate_simple_hmac_any(secrets: list[str], body: bytes, signature_header: str | None, header_name: str) -> None:
    if not signature_header:
        raise HTTPException(status_code=401, detail=f"Missing {header_name} header.")
    algo, sig_hex = _normalize_sig(signature_header)
    if algo not in ("sha256", None):
        raise HTTPException(status_code=401, detail="Invalid signature algorithm.")
    for s in secrets:
        expected = _hmac_sha256_hex(s, body)
        if hmac.compare_digest(expected, sig_hex):
            return
    raise HTTPException(status_code=401, detail="Invalid signature.")


def _validate_stripe_signature_any(secrets: list[str], body: bytes, stripe_sig_header: str | None) -> None:
    if not stripe_sig_header:
        raise HTTPException(status_code=401, detail="Missing Stripe-Signature header.")

    parts = [p.strip() for p in stripe_sig_header.split(",") if p.strip()]
    kv: dict[str, str] = {}
    v1s: list[str] = []
    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "v1":
            v1s.append(v)
        else:
            kv[k] = v

    ts_str = kv.get("t")
    if not ts_str or not ts_str.isdigit():
        raise HTTPException(status_code=401, detail="Invalid Stripe-Signature header (missing t).")
    ts = int(ts_str)

    now = _unix_now()
    if abs(now - ts) > STRIPE_TOLERANCE_SECONDS:
        raise HTTPException(status_code=401, detail="Stripe signature timestamp outside tolerance.")

    signed = f"{ts}.".encode() + body

    for secret in secrets:
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        for sig in v1s:
            if hmac.compare_digest(expected, sig):
                return

    raise HTTPException(status_code=401, detail="Invalid Stripe signature.")


_ZERO_DECIMAL_CURRENCIES = {
    "BIF",
    "CLP",
    "DJF",
    "GNF",
    "JPY",
    "KMF",
    "KRW",
    "MGA",
    "PYG",
    "RWF",
    "UGX",
    "VND",
    "VUV",
    "XAF",
    "XOF",
    "XPF",
}


def _format_stripe_amount(amount: Any, currency: str) -> str:
    cur = (currency or "").upper() or "USD"
    try:
        a = int(amount)
    except Exception:
        try:
            a = int(float(amount))
        except Exception:
            return str(amount)

    if cur in _ZERO_DECIMAL_CURRENCIES:
        return f"{a}"
    return f"{(a / 100.0):.2f}"


_PLACEHOLDER_RE = re.compile(r"\{payload(?:\.[^}]+)?\}")


def _get_by_path(payload: Any, path: str) -> Any:
    """
    path examples:
      "payload.name"
      "payload.customer.email"
      "payload.commits.0.message"
    """
    if not path.startswith("payload"):
        return ""
    cur: Any = payload
    parts = path.split(".")[1:]  # drop "payload"
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            if part.isdigit():
                idx = int(part)
                cur = cur[idx] if 0 <= idx < len(cur) else None
            else:
                return ""
        else:
            return ""
        if cur is None:
            return ""
    return cur


def _stringify_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return str(v)
    try:
        s = json.dumps(v, ensure_ascii=False)
    except Exception:
        s = str(v)
    # keep placeholders readable
    if len(s) > 2000:
        s = s[:2000] + "…"
    return s


def _interpolate_template(template: str, payload: dict[str, Any]) -> str:
    # Fast path for classic {payload}
    full_payload_str = _payload_string(payload)

    def repl(match: re.Match) -> str:
        tok = match.group(0).strip("{}")
        if tok == "payload":
            return full_payload_str
        v = _get_by_path(payload, tok)
        return _stringify_value(v)

    return _PLACEHOLDER_RE.sub(repl, template)


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _inbox_record_base(
    *,
    provider: str,
    webhook_id: str | None,
    request: Request | None,
    body: bytes,
    signature_header: str | None,
    delivery_id: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "received_at": _now_iso(),
        "provider": provider,
        "webhook_id": webhook_id,
        "delivery_id": delivery_id,
        "client_ip": _client_ip(request) if request else None,
        "body_sha256": _sha256_hex(body),
        "content_length": len(body),
    }
    if signature_header:
        rec["signature_header"] = signature_header[:512]  # don't allow insane headers
    if extra:
        rec.update(extra)
    if INBOX_STORE_BODY:
        if len(body) <= INBOX_BODY_MAX_BYTES:
            # JSON expected; store UTF-8 if possible, else base64
            try:
                rec["body"] = body.decode("utf-8")
                rec["body_encoding"] = "utf-8"
            except Exception:
                rec["body_b64"] = base64.b64encode(body).decode("ascii")
                rec["body_encoding"] = "base64"
        else:
            rec["body_truncated"] = True
            try:
                rec["body_preview"] = body[:INBOX_BODY_MAX_BYTES].decode("utf-8", errors="replace")
            except Exception:
                rec["body_preview_b64"] = base64.b64encode(body[:INBOX_BODY_MAX_BYTES]).decode("ascii")
    return rec


def _stats_key(provider: str, webhook_id: str | None) -> str:
    return f"{provider}:{webhook_id or '-'}"


class RegisterWebhookRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    secret: str | None = Field(default=None, max_length=2048)
    goal_template: str = Field(..., min_length=1, max_length=100_000)
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=100000)


class RegisterWebhookResponse(BaseModel):
    status: str
    id: str


class PatchWebhookRequest(BaseModel):
    secret: str | None = Field(default=None, max_length=2048)
    goal_template: str | None = Field(default=None, min_length=1, max_length=100_000)
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=100000)


class ListWebhookItem(BaseModel):
    id: str
    has_secret: bool
    goal_template: str
    created_at: str
    rate_limit_per_min: int


class ReceiveWebhookResponse(BaseModel):
    status: str
    goal_id: str


class TestWebhookResponse(BaseModel):
    status: str
    goal_id: str
    signature: str | None = None


def _delivery_deps() -> WebhookDeliveryDeps:
    return WebhookDeliveryDeps(
        store=_STORE,
        inbox=_INBOX,
        receipts=_RECEIPTS,
        stats=_STATS,
        rate_limiter=_RATE_LIMITER,
        store_raw_payload=STORE_RAW_PAYLOAD,
        max_commits_included=MAX_COMMITS_INCLUDED,
        now_iso=_now_iso,
        require_admin=_require_admin,
        require_json_object=_require_json_object,
        interpolate_template=_interpolate_template,
        payload_string=_payload_string,
        queue_goal=_queue_goal,
        emit_event=_emit_event,
        format_stripe_amount=_format_stripe_amount,
        read_body_limited=_read_body_limited,
        client_ip=_client_ip,
        split_secrets=_split_secrets,
        require_provider_secrets_for_signature_enforcement=_require_provider_secrets_for_signature_enforcement,
        require_generic_secret_for_signature_enforcement=_require_generic_secret_for_signature_enforcement,
        validate_simple_hmac_any=_validate_simple_hmac_any,
        validate_stripe_signature_any=_validate_stripe_signature_any,
        inbox_record_base=_inbox_record_base,
        stats_key=_stats_key,
    )


@webhook_router.post("/register", response_model=RegisterWebhookResponse)
async def register_webhook(
    body: RegisterWebhookRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> RegisterWebhookResponse:
    _require_admin(x_admin_token)

    wid = body.id.strip()
    if (not wid) or "/" in wid or "\\" in wid or wid in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid webhook id.")

    rl = int(body.rate_limit_per_min or DEFAULT_RATE_LIMIT_PER_MIN)
    rec = WebhookRecord(
        id=wid,
        secret=body.secret.strip() if isinstance(body.secret, str) and body.secret.strip() else None,
        goal_template=body.goal_template,
        created_at=_now_iso(),
        rate_limit_per_min=rl,
    )
    if _webhook_signature_enforcement_enabled() and not rec.secret:
        raise HTTPException(
            status_code=400,
            detail=(
                "Webhook secret is required when webhook signature enforcement is enabled "
                "(set THOMAS_WEBHOOK_REQUIRE_SIGNATURES=0 to disable for local development)."
            ),
        )
    _STORE.register(rec)
    _emit_event("webhook.registered", {"id": wid})
    return RegisterWebhookResponse(status="registered", id=wid)


@webhook_router.patch("/{id}")
async def patch_webhook(
    id: str,
    body: PatchWebhookRequest,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    _require_admin(x_admin_token)

    wid = id.strip()
    rec = _STORE.get(wid)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Webhook '{wid}' not registered.")

    new_secret = rec.secret
    if body.secret is not None:
        new_secret = body.secret.strip() if body.secret.strip() else None

    new_template = rec.goal_template
    if body.goal_template is not None:
        new_template = body.goal_template

    new_rl = rec.rate_limit_per_min
    if body.rate_limit_per_min is not None:
        new_rl = int(body.rate_limit_per_min)

    new_rec = WebhookRecord(
        id=rec.id,
        secret=new_secret,
        goal_template=new_template,
        created_at=rec.created_at,
        rate_limit_per_min=new_rl,
    )
    if _webhook_signature_enforcement_enabled() and not new_rec.secret:
        raise HTTPException(
            status_code=400,
            detail=(
                "Webhook secret is required when webhook signature enforcement is enabled "
                "(set THOMAS_WEBHOOK_REQUIRE_SIGNATURES=0 to disable for local development)."
            ),
        )
    _STORE.upsert(new_rec)
    return {"status": "updated", "id": wid}


@webhook_router.delete("/{id}")
async def delete_webhook(
    id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, str]:
    _require_admin(x_admin_token)

    wid = id.strip()
    _STORE.delete(wid)
    _emit_event("webhook.deleted", {"id": wid})
    return {"status": "deleted", "id": wid}


@webhook_router.get("", response_model=list[dict[str, Any]])
async def list_webhooks(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> list[dict[str, Any]]:
    _require_admin(x_admin_token)

    items = _STORE.list()
    return [
        ListWebhookItem(
            id=r.id,
            has_secret=bool(r.secret),
            goal_template=r.goal_template,
            created_at=r.created_at,
            rate_limit_per_min=r.rate_limit_per_min,
        ).model_dump()
        for r in items
    ]


@webhook_router.get("/{id}")
async def get_webhook(
    id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    _require_admin(x_admin_token)
    wid = id.strip()
    rec = _STORE.get(wid)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Webhook '{wid}' not registered.")
    stats = _STATS.get(_stats_key("generic", wid))
    return {
        "id": rec.id,
        "has_secret": bool(rec.secret),
        "goal_template": rec.goal_template,
        "created_at": rec.created_at,
        "rate_limit_per_min": rec.rate_limit_per_min,
        "stats": stats,
    }


@webhook_router.get("/stats/all")
async def stats_all(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    _require_admin(x_admin_token)
    return _STATS.all()


@webhook_router.get("/inbox/recent")
async def inbox_recent(
    limit: int = 50,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> list[dict[str, Any]]:
    _require_admin(x_admin_token)
    return _INBOX.tail(limit)


@webhook_router.post("/inbox/retry/{event_id}", response_model=ReceiveWebhookResponse)
async def inbox_retry(
    event_id: str,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> ReceiveWebhookResponse:
    payload = await inbox_retry_impl(
        event_id=event_id,
        x_admin_token=x_admin_token,
        deps=_delivery_deps(),
    )
    return ReceiveWebhookResponse(**payload)


@webhook_router.post("/test/{id}", response_model=TestWebhookResponse)
async def test_webhook(
    id: str,
    payload: dict[str, Any],
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> TestWebhookResponse:
    out = await test_webhook_impl(
        webhook_id=id,
        payload=payload,
        x_admin_token=x_admin_token,
        deps=_delivery_deps(),
    )
    return TestWebhookResponse(**out)


@webhook_router.post("/receive/github", response_model=ReceiveWebhookResponse)
async def receive_github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
) -> ReceiveWebhookResponse:
    payload = await receive_github_webhook_impl(
        request=request,
        x_hub_signature_256=x_hub_signature_256,
        x_github_event=x_github_event,
        x_github_delivery=x_github_delivery,
        deps=_delivery_deps(),
    )
    return ReceiveWebhookResponse(**payload)


@webhook_router.post("/receive/stripe", response_model=ReceiveWebhookResponse)
async def receive_stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> ReceiveWebhookResponse:
    payload = await receive_stripe_webhook_impl(
        request=request,
        stripe_signature=stripe_signature,
        deps=_delivery_deps(),
    )
    return ReceiveWebhookResponse(**payload)


@webhook_router.post("/receive/{id}", response_model=ReceiveWebhookResponse)
async def receive_webhook(
    id: str,
    request: Request,
    x_webhook_signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    x_webhook_delivery: str | None = Header(default=None, alias="X-Webhook-Delivery"),
) -> ReceiveWebhookResponse:
    payload = await receive_webhook_impl(
        webhook_id=id,
        request=request,
        x_webhook_signature=x_webhook_signature,
        x_webhook_delivery=x_webhook_delivery,
        deps=_delivery_deps(),
    )
    return ReceiveWebhookResponse(**payload)
