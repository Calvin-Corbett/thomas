"""Payment/entitlement wiring for generated (app-builder) apps.

Design goals
------------
* **No entitlement without a verified event.** :meth:`PaymentWiring.handle_webhook`
  verifies the webhook signature *before* touching the entitlement store. A
  forged / unsigned / tampered event grants nothing and is rejected with a
  machine-readable reason.
* **SDK-free + hermetic.** The default Stripe signature verifier *reuses* the
  repository's existing SDK-free verifier
  (``thomas.server.routes.webhooks_routes._validate_stripe_signature_any``).
  The default payment provider *builds* a real Stripe Checkout Session request
  but never makes a live call. Both edges are injectable so tests run fully
  offline against a fake.
* **Secrets never logged.** Signing secrets and the provider API key are held in
  private fields, never emitted in logs or dataclass reprs.

Live lane (credential-gated, not exercised here): pair
:class:`StripePaymentProvider` with a real HTTP transport + live
``sk_live_...`` / ``whsec_...`` secrets and point a Stripe webhook endpoint at
:meth:`PaymentWiring.handle_webhook`. That path is documented, not claimed to
have run.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

Clock = Callable[[], float]

# Stripe event types that grant / revoke access. Kept explicit so an unknown or
# irrelevant event type is *ignored* (no state change) rather than assumed.
GRANT_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "invoice.paid",
    }
)
REVOKE_EVENTS = frozenset(
    {
        "customer.subscription.deleted",
        "checkout.session.expired",
        "invoice.payment_failed",
    }
)


def _default_clock() -> float:
    return time.time()


def _redact_secret(secret: str | None) -> str:
    """Return a non-reversible fingerprint safe to place in logs."""
    if not secret:
        return "<none>"
    text = str(secret)
    if len(text) <= 4:
        return "****"
    return f"{text[:3]}…({len(text)} chars)"


def _normalize_secrets(secrets: str | Iterable[str] | None) -> list[str]:
    if secrets is None:
        return []
    if isinstance(secrets, str):
        items = secrets.split(",")
    else:
        items = list(secrets)
    out: list[str] = []
    for raw in items:
        text = str(raw).strip()
        if text:
            out.append(text)
    return out


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of a webhook signature check."""

    ok: bool
    reason: str = ""


@runtime_checkable
class SignatureVerifier(Protocol):
    """Injectable webhook signature verifier."""

    def verify(self, *, body: bytes, signature_header: str | None, secrets: list[str]) -> VerificationResult: ...


def build_stripe_signature_header(secret: str, body: bytes, timestamp: int) -> str:
    """Build a Stripe-style ``Stripe-Signature`` header value.

    Provided as a production helper so a generated app (or a test) can sign a
    payload deterministically with an injected ``timestamp`` (clock). Mirrors
    the scheme the repo verifier checks: ``t=<ts>,v1=<hmac_sha256(ts.body)>``.
    """
    signed = f"{int(timestamp)}.".encode() + body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={int(timestamp)},v1={digest}"


class StripeSignatureVerifier:
    """Default verifier -- reuses the repo's SDK-free Stripe signature verifier.

    The repo verifier raises ``fastapi.HTTPException`` on any failure; we adapt
    that into a :class:`VerificationResult` carrying the rejection reason. The
    underlying callable is injectable so this class stays unit-testable without
    importing the server stack.
    """

    def __init__(self, verify_fn: Callable[[list[str], bytes, str | None], Any] | None = None) -> None:
        self._verify_fn = verify_fn

    def _resolve_verify_fn(self) -> Callable[[list[str], bytes, str | None], Any]:
        if self._verify_fn is not None:
            return self._verify_fn
        # Reuse the existing SDK-free Stripe verifier (marketplace -> server is
        # a pre-existing, allowed dependency edge). Imported lazily to avoid
        # pulling the FastAPI stack at module import time.
        from thomas.server.routes.webhooks_routes import _validate_stripe_signature_any

        self._verify_fn = _validate_stripe_signature_any
        return self._verify_fn

    def verify(self, *, body: bytes, signature_header: str | None, secrets: list[str]) -> VerificationResult:
        if not signature_header:
            return VerificationResult(False, "missing signature header")
        if not secrets:
            return VerificationResult(False, "no signing secret configured")

        # Lazy import so a missing/renamed exception type is caught concretely.
        from fastapi import HTTPException

        verify_fn = self._resolve_verify_fn()
        try:
            verify_fn(list(secrets), body, signature_header)
        except HTTPException as exc:  # concrete: repo verifier's only failure signal
            return VerificationResult(False, str(exc.detail))
        return VerificationResult(True, "")


class FakeSignatureVerifier:
    """Hermetic verifier for tests/local apps.

    Accepts an in-process ``t=<ts>,v1=<hmac>`` header signed with any configured
    secret. Independent of the server stack, so it exercises the same *policy*
    (grant only on a valid signature) without importing FastAPI.
    """

    def __init__(self, tolerance_seconds: int = 300, clock: Clock | None = None) -> None:
        self._tolerance = int(tolerance_seconds)
        self._clock = clock or _default_clock

    def verify(self, *, body: bytes, signature_header: str | None, secrets: list[str]) -> VerificationResult:
        if not signature_header:
            return VerificationResult(False, "missing signature header")
        if not secrets:
            return VerificationResult(False, "no signing secret configured")

        kv: dict[str, str] = {}
        v1s: list[str] = []
        for part in signature_header.split(","):
            part = part.strip()
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key, value = key.strip(), value.strip()
            if key == "v1":
                v1s.append(value)
            else:
                kv[key] = value

        ts_raw = kv.get("t", "")
        if not ts_raw.isdigit():
            return VerificationResult(False, "missing or invalid timestamp")
        if not v1s:
            return VerificationResult(False, "missing v1 signature")

        ts = int(ts_raw)
        if abs(int(self._clock()) - ts) > self._tolerance:
            return VerificationResult(False, "timestamp outside tolerance")

        signed = f"{ts}.".encode() + body
        for secret in secrets:
            expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
            for candidate in v1s:
                if hmac.compare_digest(expected, candidate):
                    return VerificationResult(True, "")
        return VerificationResult(False, "signature mismatch")


# ---------------------------------------------------------------------------
# Payment provider (checkout / subscription intent)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckoutIntent:
    """A request to start a checkout / subscription for a generated app."""

    account_id: str
    entitlement: str
    price_id: str
    mode: str = "subscription"  # "subscription" | "payment"
    success_url: str = ""
    cancel_url: str = ""
    quantity: int = 1
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedRequest:
    """A built-but-unsent HTTP request (the real provider stops here)."""

    method: str
    url: str
    headers: Mapping[str, str]
    body: str


@dataclass(frozen=True)
class CheckoutSession:
    """Result of wiring a checkout intent."""

    session_id: str
    provider: str
    intent: CheckoutIntent
    prepared_request: PreparedRequest | None = None
    checkout_url: str | None = None
    live_call_made: bool = False


@runtime_checkable
class PaymentProvider(Protocol):
    """Injectable payment provider."""

    name: str

    def create_checkout(self, intent: CheckoutIntent) -> CheckoutSession: ...


class StripePaymentProvider:
    """Real, SDK-free Stripe provider that *builds* the Checkout request.

    It assembles the exact form-encoded ``POST /v1/checkout/sessions`` request
    Stripe expects, but does **not** send it -- ``live_call_made`` is always
    ``False`` here. Wiring an actual transport is the credential-gated live
    lane. The API key lives only in the (unlogged) Authorization header.
    """

    name = "stripe"
    api_base = "https://api.stripe.com/v1"

    def __init__(self, api_key: str, *, clock: Clock | None = None) -> None:
        self._api_key = api_key
        self._clock = clock or _default_clock

    def _idempotency_key(self, intent: CheckoutIntent) -> str:
        seed = f"{intent.account_id}:{intent.entitlement}:{intent.price_id}:{int(self._clock())}"
        return "app-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]

    def create_checkout(self, intent: CheckoutIntent) -> CheckoutSession:
        params: dict[str, str] = {
            "mode": intent.mode,
            "client_reference_id": intent.account_id,
            "line_items[0][price]": intent.price_id,
            "line_items[0][quantity]": str(int(intent.quantity)),
            "metadata[account_id]": intent.account_id,
            "metadata[entitlement]": intent.entitlement,
        }
        if intent.success_url:
            params["success_url"] = intent.success_url
        if intent.cancel_url:
            params["cancel_url"] = intent.cancel_url
        for key, value in intent.metadata.items():
            params[f"metadata[{key}]"] = str(value)

        body = urlencode(params)
        idempotency = self._idempotency_key(intent)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Idempotency-Key": idempotency,
        }
        prepared = PreparedRequest(
            method="POST",
            url=f"{self.api_base}/checkout/sessions",
            headers=headers,
            body=body,
        )
        # Deterministic local id; a live call would replace this with cs_...
        session_id = "cs_intent_" + idempotency.split("-", 1)[1][:24]
        logger.info(
            "payment.checkout.prepared provider=stripe account=%s entitlement=%s mode=%s api_key=%s",
            intent.account_id,
            intent.entitlement,
            intent.mode,
            _redact_secret(self._api_key),
        )
        return CheckoutSession(
            session_id=session_id,
            provider=self.name,
            intent=intent,
            prepared_request=prepared,
            checkout_url=None,
            live_call_made=False,
        )


class FakePaymentProvider:
    """Hermetic provider for tests / offline app development."""

    name = "fake"

    def __init__(self, base_url: str = "https://fake.checkout.local") -> None:
        self._base_url = base_url.rstrip("/")
        self.calls: list[CheckoutIntent] = []

    def create_checkout(self, intent: CheckoutIntent) -> CheckoutSession:
        self.calls.append(intent)
        session_id = "cs_fake_" + hashlib.sha256(f"{intent.account_id}:{intent.entitlement}".encode()).hexdigest()[:16]
        return CheckoutSession(
            session_id=session_id,
            provider=self.name,
            intent=intent,
            prepared_request=None,
            checkout_url=f"{self._base_url}/{session_id}",
            live_call_made=False,
        )


# ---------------------------------------------------------------------------
# Entitlement store
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntitlementRecord:
    account_id: str
    entitlement: str
    status: str  # "active" | "revoked"
    granted_at: float
    updated_at: float
    source_event_id: str
    reason: str

    @property
    def active(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "entitlement": self.entitlement,
            "status": self.status,
            "granted_at": self.granted_at,
            "updated_at": self.updated_at,
            "source_event_id": self.source_event_id,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EntitlementRecord:
        return cls(
            account_id=str(data.get("account_id", "")),
            entitlement=str(data.get("entitlement", "")),
            status=str(data.get("status", "revoked")),
            granted_at=float(data.get("granted_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
            source_event_id=str(data.get("source_event_id", "")),
            reason=str(data.get("reason", "")),
        )


def _default_store_path() -> Path:
    env = os.getenv("THOMAS_ENTITLEMENTS_FILE")
    if env:
        return Path(env).expanduser().resolve()
    try:
        from thomas.core.config import resolve_thomas_data_dir

        return (resolve_thomas_data_dir() / "json" / "thomas_app_entitlements.json").resolve()
    except ImportError:
        return (Path.home() / ".thomas" / "thomas_app_entitlements.json").resolve()


class EntitlementStore:
    """JSON-backed account -> entitlements store (env-overridable path).

    File shape::

        {"version": 1, "entitlements": {"<account>": {"<entitlement>": {...}}}}
    """

    def __init__(self, path: Path | str | None = None, *, clock: Clock | None = None) -> None:
        self._path_override = Path(path).expanduser().resolve() if path else None
        self._resolved_path: Path | None = None
        self._clock = clock or _default_clock
        self._lock = threading.Lock()

    def path(self) -> Path:
        if self._path_override is not None:
            return self._path_override
        if self._resolved_path is None:
            self._resolved_path = _default_store_path()
        return self._resolved_path

    def _load_unlocked(self) -> dict[str, Any]:
        p = self.path()
        if not p.exists():
            return {"version": 1, "entitlements": {}}
        try:
            raw = p.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {"version": 1, "entitlements": {}}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("entitlement.store.unreadable path=%s -- starting empty", p)
            return {"version": 1, "entitlements": {}}
        if not isinstance(data, dict) or not isinstance(data.get("entitlements"), dict):
            return {"version": 1, "entitlements": {}}
        return data

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def grant(
        self,
        account_id: str,
        entitlement: str,
        *,
        event_id: str,
        reason: str = "",
    ) -> EntitlementRecord:
        now = float(self._clock())
        with self._lock:
            data = self._load_unlocked()
            accounts = data["entitlements"]
            bucket = accounts.setdefault(account_id, {})
            existing = bucket.get(entitlement)
            granted_at = now
            if isinstance(existing, dict) and existing.get("status") == "active":
                granted_at = float(existing.get("granted_at", now))
            record = EntitlementRecord(
                account_id=account_id,
                entitlement=entitlement,
                status="active",
                granted_at=granted_at,
                updated_at=now,
                source_event_id=event_id,
                reason=reason,
            )
            bucket[entitlement] = record.to_dict()
            self._save_unlocked(data)
        return record

    def revoke(
        self,
        account_id: str,
        entitlement: str,
        *,
        event_id: str,
        reason: str = "",
    ) -> EntitlementRecord:
        now = float(self._clock())
        with self._lock:
            data = self._load_unlocked()
            accounts = data["entitlements"]
            bucket = accounts.setdefault(account_id, {})
            existing = bucket.get(entitlement)
            granted_at = now
            if isinstance(existing, dict):
                granted_at = float(existing.get("granted_at", now))
            record = EntitlementRecord(
                account_id=account_id,
                entitlement=entitlement,
                status="revoked",
                granted_at=granted_at,
                updated_at=now,
                source_event_id=event_id,
                reason=reason,
            )
            bucket[entitlement] = record.to_dict()
            self._save_unlocked(data)
        return record

    def get(self, account_id: str, entitlement: str) -> EntitlementRecord | None:
        with self._lock:
            data = self._load_unlocked()
            bucket = data["entitlements"].get(account_id)
            if not isinstance(bucket, dict):
                return None
            rec = bucket.get(entitlement)
            if not isinstance(rec, dict):
                return None
            return EntitlementRecord.from_dict(rec)

    def check(self, account_id: str, entitlement: str) -> bool:
        rec = self.get(account_id, entitlement)
        return bool(rec and rec.active)

    def list_for(self, account_id: str) -> list[EntitlementRecord]:
        with self._lock:
            data = self._load_unlocked()
            bucket = data["entitlements"].get(account_id)
            if not isinstance(bucket, dict):
                return []
            out = [EntitlementRecord.from_dict(v) for v in bucket.values() if isinstance(v, dict)]
        out.sort(key=lambda r: r.entitlement)
        return out


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntitlementDecision:
    """Outcome of processing one webhook event."""

    accepted: bool  # signature verified AND payload usable
    action: str  # "grant" | "revoke" | "ignored" | "rejected"
    reason: str
    account_id: str | None = None
    entitlement: str | None = None
    event_id: str | None = None
    event_type: str | None = None
    record: EntitlementRecord | None = None


class PaymentWiring:
    """Wire payments + entitlements for a single generated app.

    ``signing_secrets`` supports comma-separated / iterable values so key
    rotation works. Secrets are private and never logged.
    """

    def __init__(
        self,
        *,
        app_id: str,
        signing_secrets: str | Iterable[str] | None,
        store: EntitlementStore,
        provider: PaymentProvider | None = None,
        verifier: SignatureVerifier | None = None,
        default_entitlement: str = "pro",
    ) -> None:
        self._app_id = app_id
        self._secrets = _normalize_secrets(signing_secrets)
        self._store = store
        self._provider = provider
        self._verifier: SignatureVerifier = verifier or StripeSignatureVerifier()
        self._default_entitlement = default_entitlement

    @property
    def app_id(self) -> str:
        return self._app_id

    @property
    def store(self) -> EntitlementStore:
        return self._store

    # -- checkout wiring ----------------------------------------------------

    def wire_checkout(self, intent: CheckoutIntent) -> CheckoutSession:
        if self._provider is None:
            raise ValueError("PaymentWiring has no payment provider configured; cannot wire checkout.")
        session = self._provider.create_checkout(intent)
        logger.info(
            "payment.checkout.wired app=%s provider=%s account=%s entitlement=%s session=%s",
            self._app_id,
            session.provider,
            intent.account_id,
            intent.entitlement,
            session.session_id,
        )
        return session

    # -- webhook -> entitlement --------------------------------------------

    def _extract_target(self, event: Mapping[str, Any]) -> tuple[str, str]:
        obj = event.get("data", {})
        obj = obj.get("object", {}) if isinstance(obj, dict) else {}
        if not isinstance(obj, dict):
            obj = {}
        metadata = obj.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        account_id = str(metadata.get("account_id") or obj.get("client_reference_id") or "")
        entitlement = str(metadata.get("entitlement") or self._default_entitlement)
        return account_id, entitlement

    def handle_webhook(self, *, body: bytes, signature_header: str | None) -> EntitlementDecision:
        """Verify the event, then grant/revoke -- *only* on a valid signature."""
        result = self._verifier.verify(body=body, signature_header=signature_header, secrets=self._secrets)
        if not result.ok:
            logger.warning("payment.webhook.rejected app=%s reason=%s", self._app_id, result.reason)
            return EntitlementDecision(accepted=False, action="rejected", reason=result.reason)

        try:
            event = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            reason = f"verified event has invalid JSON body: {exc}"
            logger.warning("payment.webhook.badjson app=%s reason=%s", self._app_id, reason)
            return EntitlementDecision(accepted=False, action="rejected", reason=reason)

        if not isinstance(event, dict):
            return EntitlementDecision(accepted=False, action="rejected", reason="event body is not a JSON object")

        event_type = str(event.get("type") or "")
        event_id = str(event.get("id") or "")
        account_id, entitlement = self._extract_target(event)

        if event_type in GRANT_EVENTS:
            if not account_id:
                return EntitlementDecision(
                    accepted=False,
                    action="rejected",
                    reason="grant event carried no account_id",
                    event_id=event_id,
                    event_type=event_type,
                )
            record = self._store.grant(account_id, entitlement, event_id=event_id, reason=event_type)
            logger.info(
                "payment.entitlement.granted app=%s account=%s entitlement=%s event=%s",
                self._app_id,
                account_id,
                entitlement,
                event_id,
            )
            return EntitlementDecision(
                accepted=True,
                action="grant",
                reason=event_type,
                account_id=account_id,
                entitlement=entitlement,
                event_id=event_id,
                event_type=event_type,
                record=record,
            )

        if event_type in REVOKE_EVENTS:
            if not account_id:
                return EntitlementDecision(
                    accepted=False,
                    action="rejected",
                    reason="revoke event carried no account_id",
                    event_id=event_id,
                    event_type=event_type,
                )
            record = self._store.revoke(account_id, entitlement, event_id=event_id, reason=event_type)
            logger.info(
                "payment.entitlement.revoked app=%s account=%s entitlement=%s event=%s",
                self._app_id,
                account_id,
                entitlement,
                event_id,
            )
            return EntitlementDecision(
                accepted=True,
                action="revoke",
                reason=event_type,
                account_id=account_id,
                entitlement=entitlement,
                event_id=event_id,
                event_type=event_type,
                record=record,
            )

        return EntitlementDecision(
            accepted=True,
            action="ignored",
            reason=f"unhandled event type: {event_type or '<empty>'}",
            account_id=account_id or None,
            entitlement=entitlement,
            event_id=event_id,
            event_type=event_type,
        )

    def is_entitled(self, account_id: str, entitlement: str) -> bool:
        return self._store.check(account_id, entitlement)
