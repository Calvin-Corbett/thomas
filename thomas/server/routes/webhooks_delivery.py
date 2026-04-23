"""Delivery and retry handlers extracted from webhook route module."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import HTTPException, Request


@dataclass
class WebhookDeliveryDeps:
    store: Any
    inbox: Any
    receipts: Any
    stats: Any
    rate_limiter: Any
    store_raw_payload: bool
    max_commits_included: int
    now_iso: Callable[[], str]
    require_admin: Callable[[Optional[str]], None]
    require_json_object: Callable[[bytes], Dict[str, Any]]
    interpolate_template: Callable[[str, Dict[str, Any]], str]
    payload_string: Callable[[Dict[str, Any]], str]
    queue_goal: Callable[[str, str, Dict[str, Any]], str]
    emit_event: Callable[[str, Dict[str, Any]], None]
    format_stripe_amount: Callable[[Any, str], str]
    read_body_limited: Callable[[Request], Awaitable[bytes]]
    client_ip: Callable[[Request], str]
    split_secrets: Callable[[Optional[str]], List[str]]
    require_provider_secrets_for_signature_enforcement: Callable[..., None]
    require_generic_secret_for_signature_enforcement: Callable[[Any], None]
    validate_simple_hmac_any: Callable[[List[str], bytes, Optional[str], str], None]
    validate_stripe_signature_any: Callable[[List[str], bytes, Optional[str]], None]
    inbox_record_base: Callable[..., Dict[str, Any]]
    stats_key: Callable[[str, Optional[str]], str]


def _response(*, status: str, goal_id: str) -> Dict[str, str]:
    return {"status": status, "goal_id": goal_id}


def _github_goal_text(
    payload: Dict[str, Any],
    *,
    event: str,
    max_commits_included: int,
) -> tuple[str, str]:
    repo = (
        payload.get("repository", {}).get("full_name")
        or payload.get("repository", {}).get("name")
        or "unknown-repo"
    )
    if event == "push":
        ref = payload.get("ref") or ""
        branch = ref.split("/")[-1] if isinstance(ref, str) and ref else "unknown"
        commits = payload.get("commits") or []
        messages: List[str] = []
        if isinstance(commits, list):
            for c in commits[:max_commits_included]:
                if isinstance(c, dict):
                    m = c.get("message")
                    if isinstance(m, str) and m.strip():
                        messages.append(m.strip().replace("\n", " "))
        commit_messages = "; ".join(messages) if messages else "no commit messages"
        return f"Review and summarize the push to {repo} branch {branch}: {commit_messages}", repo

    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        number = payload.get("number") or pr.get("number") or "?"
        title = pr.get("title") or payload.get("title") or "Untitled"
        return f"Review PR #{number}: {title} in {repo}", repo

    raise HTTPException(status_code=400, detail=f"Unsupported GitHub event: {event or 'unknown'}")


def _stripe_payment_goal(payload: Dict[str, Any], *, format_stripe_amount: Callable[[Any, str], str]) -> tuple[str, str]:
    obj = (((payload.get("data") or {}).get("object")) or {})
    if not isinstance(obj, dict):
        obj = {}
    amount = obj.get("amount_received") or obj.get("amount") or 0
    currency = (obj.get("currency") or "").upper() or "USD"
    customer = obj.get("customer") or obj.get("receipt_email") or obj.get("customer_email") or "unknown"
    amount_str = format_stripe_amount(amount, currency)
    return f"Log successful payment of {amount_str} {currency} from {customer}", currency


async def inbox_retry_impl(
    *,
    event_id: str,
    x_admin_token: Optional[str],
    deps: WebhookDeliveryDeps,
) -> Dict[str, str]:
    deps.require_admin(x_admin_token)
    rec = deps.inbox.find_event(event_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Event not found in inbox (recent window).")

    provider = rec.get("provider")
    webhook_id = rec.get("webhook_id")
    body_bytes: Optional[bytes] = None
    if rec.get("body_encoding") == "utf-8" and isinstance(rec.get("body"), str):
        body_bytes = rec["body"].encode("utf-8")
    elif rec.get("body_encoding") == "base64" and isinstance(rec.get("body_b64"), str):
        body_bytes = base64.b64decode(rec["body_b64"].encode("ascii"))
    elif isinstance(rec.get("body_preview"), str):
        body_bytes = rec["body_preview"].encode("utf-8")

    if not body_bytes:
        raise HTTPException(
            status_code=400,
            detail="Stored body not available for retry. Enable THOMAS_WEBHOOK_INBOX_STORE_BODY=1.",
        )

    if provider == "generic" and isinstance(webhook_id, str):
        payload = deps.require_json_object(body_bytes)
        stored = deps.store.get(webhook_id)
        goal_text = (
            deps.interpolate_template(stored.goal_template, payload)
            if stored
            else deps.payload_string(payload)
        )
        meta: Dict[str, Any] = {
            "webhook_id": webhook_id,
            "retry_of_event_id": event_id,
            "body_sha256": rec.get("body_sha256"),
        }
        if deps.store_raw_payload:
            meta["raw"] = payload
        goal_id = deps.queue_goal(goal_text, "webhook.generic.retry", meta)
        deps.stats.bump(
            deps.stats_key("generic", webhook_id),
            inc_total_received=1,
            inc_total_queued=1,
            last_received_at=deps.now_iso(),
            last_goal_id=goal_id,
            last_error=None,
        )
        deps.emit_event(
            "webhook.retried",
            {"provider": "generic", "webhook_id": webhook_id, "goal_id": goal_id, "event_id": event_id},
        )
        return _response(status="queued", goal_id=goal_id)

    if provider == "github":
        payload = deps.require_json_object(body_bytes)
        event = (
            "push"
            if "commits" in payload and "ref" in payload
            else "pull_request"
            if "pull_request" in payload
            else "unknown"
        )
        goal_text, repo = _github_goal_text(
            payload,
            event=event,
            max_commits_included=deps.max_commits_included,
        )
        meta = {
            "provider": "github",
            "event": event,
            "repo": repo,
            "retry_of_event_id": event_id,
            "body_sha256": rec.get("body_sha256"),
        }
        if deps.store_raw_payload:
            meta["raw"] = payload
        goal_id = deps.queue_goal(goal_text, "webhook.github.retry", meta)
        deps.stats.bump(
            deps.stats_key("github", None),
            inc_total_received=1,
            inc_total_queued=1,
            last_received_at=deps.now_iso(),
            last_goal_id=goal_id,
            last_error=None,
        )
        deps.emit_event("webhook.retried", {"provider": "github", "goal_id": goal_id, "event_id": event_id})
        return _response(status="queued", goal_id=goal_id)

    if provider == "stripe":
        payload = deps.require_json_object(body_bytes)
        event_type = payload.get("type")
        if event_type != "payment_intent.succeeded":
            raise HTTPException(status_code=400, detail="Retry only supports payment_intent.succeeded.")
        goal_text, currency = _stripe_payment_goal(payload, format_stripe_amount=deps.format_stripe_amount)
        meta = {
            "provider": "stripe",
            "event": event_type,
            "currency": currency,
            "retry_of_event_id": event_id,
            "body_sha256": rec.get("body_sha256"),
        }
        if deps.store_raw_payload:
            meta["raw"] = payload
        goal_id = deps.queue_goal(goal_text, "webhook.stripe.retry", meta)
        deps.stats.bump(
            deps.stats_key("stripe", None),
            inc_total_received=1,
            inc_total_queued=1,
            last_received_at=deps.now_iso(),
            last_goal_id=goal_id,
            last_error=None,
        )
        deps.emit_event("webhook.retried", {"provider": "stripe", "goal_id": goal_id, "event_id": event_id})
        return _response(status="queued", goal_id=goal_id)

    raise HTTPException(status_code=400, detail=f"Unsupported provider for retry: {provider}")


async def test_webhook_impl(
    *,
    webhook_id: str,
    payload: Dict[str, Any],
    x_admin_token: Optional[str],
    deps: WebhookDeliveryDeps,
) -> Dict[str, Any]:
    deps.require_admin(x_admin_token)
    wid = webhook_id.strip()
    rec = deps.store.get(wid)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Webhook '{wid}' not registered.")

    import hashlib
    import hmac
    import json

    body = json.dumps(payload).encode("utf-8")
    signature = None
    if rec.secret:
        sig = hmac.new(rec.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        signature = "sha256=" + sig

    goal_text = deps.interpolate_template(rec.goal_template, payload)
    meta: Dict[str, Any] = {"webhook_id": wid, "test": True}
    if deps.store_raw_payload:
        meta["raw"] = payload
    goal_id = deps.queue_goal(goal_text, "webhook.generic.test", meta)
    deps.stats.bump(
        deps.stats_key("generic", wid),
        inc_total_received=1,
        inc_total_queued=1,
        last_received_at=deps.now_iso(),
        last_goal_id=goal_id,
        last_error=None,
    )
    return {"status": "queued", "goal_id": goal_id, "signature": signature}


async def receive_github_webhook_impl(
    *,
    request: Request,
    x_hub_signature_256: Optional[str],
    x_github_event: Optional[str],
    x_github_delivery: Optional[str],
    deps: WebhookDeliveryDeps,
) -> Dict[str, str]:
    secrets = deps.split_secrets(os.getenv("THOMAS_GITHUB_WEBHOOK_SECRET")) or deps.split_secrets(
        os.getenv("THOMAS_GITHUB_WEBHOOK_SECRETS")
    )
    deps.require_provider_secrets_for_signature_enforcement(
        provider="GitHub",
        secrets=secrets,
        env_keys=["THOMAS_GITHUB_WEBHOOK_SECRET", "THOMAS_GITHUB_WEBHOOK_SECRETS"],
    )
    if not secrets:
        raise HTTPException(
            status_code=500,
            detail="GitHub webhook secret not configured (THOMAS_GITHUB_WEBHOOK_SECRET).",
        )

    body = await deps.read_body_limited(request)
    if x_github_delivery:
        existing = deps.receipts.get_goal_id(f"github:{x_github_delivery}")
        if existing:
            deps.stats.bump(
                deps.stats_key("github", None),
                inc_total_received=1,
                inc_total_duplicate=1,
                last_received_at=deps.now_iso(),
                last_goal_id=existing,
            )
            return _response(status="duplicate", goal_id=existing)

    deps.validate_simple_hmac_any(secrets, body, x_hub_signature_256, "X-Hub-Signature-256")
    payload = deps.require_json_object(body)
    event = (x_github_event or "").strip().lower()

    inbox_rec = deps.inbox_record_base(
        provider="github",
        webhook_id=None,
        request=request,
        body=body,
        signature_header=x_hub_signature_256,
        delivery_id=x_github_delivery,
        extra={"event": event},
    )

    try:
        if event == "ping":
            inbox_rec["status"] = "noop"
            deps.inbox.append(inbox_rec)
            deps.stats.bump(
                deps.stats_key("github", None),
                inc_total_received=1,
                inc_total_queued=1,
                last_received_at=deps.now_iso(),
                last_goal_id="noop",
                last_error=None,
            )
            return _response(status="queued", goal_id="noop")

        goal_text, repo = _github_goal_text(
            payload,
            event=event,
            max_commits_included=deps.max_commits_included,
        )
        meta: Dict[str, Any] = {"provider": "github", "event": event, "repo": repo}
        if x_github_delivery:
            meta["delivery"] = x_github_delivery
        if deps.store_raw_payload:
            meta["raw"] = payload

        goal_id = deps.queue_goal(goal_text, "webhook.github", meta)

        if x_github_delivery:
            deps.receipts.put(f"github:{x_github_delivery}", goal_id)

        inbox_rec["status"] = "queued"
        inbox_rec["goal_id"] = goal_id
        deps.inbox.append(inbox_rec)

        deps.stats.bump(
            deps.stats_key("github", None),
            inc_total_received=1,
            inc_total_queued=1,
            last_received_at=deps.now_iso(),
            last_goal_id=goal_id,
            last_error=None,
        )
        deps.emit_event(
            "webhook.received",
            {"provider": "github", "event": event, "repo": repo, "goal_id": goal_id},
        )
        return _response(status="queued", goal_id=goal_id)

    except HTTPException as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = str(e.detail)
        deps.inbox.append(inbox_rec)
        deps.stats.bump(
            deps.stats_key("github", None),
            inc_total_received=1,
            inc_total_failed=1,
            last_received_at=deps.now_iso(),
            last_error=str(e.detail),
        )
        raise
    except Exception as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = f"Unhandled error: {e}"
        deps.inbox.append(inbox_rec)
        deps.stats.bump(
            deps.stats_key("github", None),
            inc_total_received=1,
            inc_total_failed=1,
            last_received_at=deps.now_iso(),
            last_error=str(e),
        )
        raise HTTPException(status_code=500, detail="Unhandled error processing GitHub webhook.")


async def receive_stripe_webhook_impl(
    *,
    request: Request,
    stripe_signature: Optional[str],
    deps: WebhookDeliveryDeps,
) -> Dict[str, str]:
    body = await deps.read_body_limited(request)
    stripe_secrets = deps.split_secrets(os.getenv("THOMAS_STRIPE_WEBHOOK_SECRET")) or deps.split_secrets(
        os.getenv("THOMAS_STRIPE_WEBHOOK_SECRETS")
    )
    deps.require_provider_secrets_for_signature_enforcement(
        provider="Stripe",
        secrets=stripe_secrets,
        env_keys=["THOMAS_STRIPE_WEBHOOK_SECRET", "THOMAS_STRIPE_WEBHOOK_SECRETS"],
    )
    if stripe_secrets:
        deps.validate_stripe_signature_any(stripe_secrets, body, stripe_signature)

    payload = deps.require_json_object(body)
    event_id = payload.get("id") if isinstance(payload.get("id"), str) else None
    event_type = payload.get("type")

    inbox_rec = deps.inbox_record_base(
        provider="stripe",
        webhook_id=None,
        request=request,
        body=body,
        signature_header=stripe_signature,
        delivery_id=event_id,
        extra={"event": event_type},
    )

    if event_id:
        existing = deps.receipts.get_goal_id(f"stripe:{event_id}")
        if existing:
            inbox_rec["status"] = "duplicate"
            inbox_rec["goal_id"] = existing
            deps.inbox.append(inbox_rec)
            deps.stats.bump(
                deps.stats_key("stripe", None),
                inc_total_received=1,
                inc_total_duplicate=1,
                last_received_at=deps.now_iso(),
                last_goal_id=existing,
            )
            return _response(status="duplicate", goal_id=existing)

    try:
        if event_type != "payment_intent.succeeded":
            raise HTTPException(status_code=400, detail=f"Unsupported Stripe event: {event_type}")

        goal_text, currency = _stripe_payment_goal(payload, format_stripe_amount=deps.format_stripe_amount)
        meta: Dict[str, Any] = {"provider": "stripe", "event": event_type, "currency": currency}
        if event_id:
            meta["event_id"] = event_id
        if deps.store_raw_payload:
            meta["raw"] = payload

        goal_id = deps.queue_goal(goal_text, "webhook.stripe", meta)

        if event_id:
            deps.receipts.put(f"stripe:{event_id}", goal_id)

        inbox_rec["status"] = "queued"
        inbox_rec["goal_id"] = goal_id
        deps.inbox.append(inbox_rec)

        deps.stats.bump(
            deps.stats_key("stripe", None),
            inc_total_received=1,
            inc_total_queued=1,
            last_received_at=deps.now_iso(),
            last_goal_id=goal_id,
            last_error=None,
        )
        deps.emit_event("webhook.received", {"provider": "stripe", "event": event_type, "goal_id": goal_id})
        return _response(status="queued", goal_id=goal_id)

    except HTTPException as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = str(e.detail)
        deps.inbox.append(inbox_rec)
        deps.stats.bump(
            deps.stats_key("stripe", None),
            inc_total_received=1,
            inc_total_failed=1,
            last_received_at=deps.now_iso(),
            last_error=str(e.detail),
        )
        raise
    except Exception as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = f"Unhandled error: {e}"
        deps.inbox.append(inbox_rec)
        deps.stats.bump(
            deps.stats_key("stripe", None),
            inc_total_received=1,
            inc_total_failed=1,
            last_received_at=deps.now_iso(),
            last_error=str(e),
        )
        raise HTTPException(status_code=500, detail="Unhandled error processing Stripe webhook.")


async def receive_webhook_impl(
    *,
    webhook_id: str,
    request: Request,
    x_webhook_signature: Optional[str],
    x_webhook_delivery: Optional[str],
    deps: WebhookDeliveryDeps,
) -> Dict[str, str]:
    wid = webhook_id.strip()
    rec = deps.store.get(wid)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Webhook '{wid}' not registered.")
    deps.require_generic_secret_for_signature_enforcement(rec)

    rl_key = f"{wid}:{deps.client_ip(request)}"
    if not deps.rate_limiter.allow(rl_key, rec.rate_limit_per_min):
        deps.stats.bump(
            deps.stats_key("generic", wid),
            inc_total_received=1,
            inc_total_failed=1,
            last_received_at=deps.now_iso(),
            last_error="rate_limited",
        )
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    body = await deps.read_body_limited(request)

    if x_webhook_delivery:
        existing = deps.receipts.get_goal_id(f"generic:{wid}:{x_webhook_delivery}")
        if existing:
            deps.stats.bump(
                deps.stats_key("generic", wid),
                inc_total_received=1,
                inc_total_duplicate=1,
                last_received_at=deps.now_iso(),
                last_goal_id=existing,
            )
            inbox_rec = deps.inbox_record_base(
                provider="generic",
                webhook_id=wid,
                request=request,
                body=body,
                signature_header=x_webhook_signature,
                delivery_id=x_webhook_delivery,
                extra={"status": "duplicate", "goal_id": existing},
            )
            deps.inbox.append(inbox_rec)
            return _response(status="duplicate", goal_id=existing)

    inbox_rec = deps.inbox_record_base(
        provider="generic",
        webhook_id=wid,
        request=request,
        body=body,
        signature_header=x_webhook_signature,
        delivery_id=x_webhook_delivery,
        extra=None,
    )

    try:
        if rec.secret:
            deps.validate_simple_hmac_any([rec.secret], body, x_webhook_signature, "X-Webhook-Signature")

        payload = deps.require_json_object(body)
        goal_text = deps.interpolate_template(rec.goal_template, payload)

        meta: Dict[str, Any] = {"webhook_id": wid}
        if x_webhook_delivery:
            meta["delivery"] = x_webhook_delivery
        if deps.store_raw_payload:
            meta["raw"] = payload

        goal_id = deps.queue_goal(goal_text, "webhook.generic", meta)

        if x_webhook_delivery:
            deps.receipts.put(f"generic:{wid}:{x_webhook_delivery}", goal_id)

        inbox_rec["status"] = "queued"
        inbox_rec["goal_id"] = goal_id
        deps.inbox.append(inbox_rec)

        deps.stats.bump(
            deps.stats_key("generic", wid),
            inc_total_received=1,
            inc_total_queued=1,
            last_received_at=deps.now_iso(),
            last_goal_id=goal_id,
            last_error=None,
        )
        deps.emit_event("webhook.received", {"provider": "generic", "webhook_id": wid, "goal_id": goal_id})
        return _response(status="queued", goal_id=goal_id)

    except HTTPException as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = str(e.detail)
        deps.inbox.append(inbox_rec)
        deps.stats.bump(
            deps.stats_key("generic", wid),
            inc_total_received=1,
            inc_total_failed=1,
            last_received_at=deps.now_iso(),
            last_error=str(e.detail),
        )
        raise
    except Exception as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = f"Unhandled error: {e}"
        deps.inbox.append(inbox_rec)
        deps.stats.bump(
            deps.stats_key("generic", wid),
            inc_total_received=1,
            inc_total_failed=1,
            last_received_at=deps.now_iso(),
            last_error=str(e),
        )
        raise HTTPException(status_code=500, detail="Unhandled error processing webhook.")
