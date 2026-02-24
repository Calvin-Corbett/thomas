# thomas/server/routes/webhooks.py
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from thomas.core.persistence import get_persistence
from thomas.server.routes.webhooks_delivery import (
    WebhookDeliveryDeps,
    inbox_retry_impl,
    receive_github_webhook_impl,
    receive_stripe_webhook_impl,
    receive_webhook_impl,
    test_webhook_impl,
)
from thomas.server.routes.webhooks_utils import (
    emit_webhook_event as _emit_event,
    file_lock as _file_lock,
)

# Module-level router for easy inclusion in main app
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# ======================================================================================
# "Consumer-grade" improvements:
# - Friendly templating: {payload.name}, {payload.customer.email}, etc (in addition to {payload})
# - Replay protection + receipts (GitHub delivery / Stripe event / generic delivery)
# - Audit inbox (append-only JSONL) with admin endpoints to inspect + retry
# - Stats per webhook/provider for transparency
# - Admin auth for management endpoints
# - Secret rotation (comma-separated secrets) for GitHub/Stripe verification
# - Optional Stripe signature verification (no stripe SDK required)
# - Rate limiting (simple in-memory token bucket), per-webhook configurable
# - Raw payload storage toggles to reduce sensitive data retention
# ======================================================================================

# ---- constants / config ----

MAX_WEBHOOK_BODY_BYTES = int(os.getenv("THOMAS_WEBHOOK_MAX_BODY_BYTES", str(1_000_000)))  # 1MB default
MAX_GOAL_PAYLOAD_CHARS = int(os.getenv("THOMAS_WEBHOOK_MAX_GOAL_PAYLOAD_CHARS", "20000"))
MAX_COMMITS_INCLUDED = int(os.getenv("THOMAS_GITHUB_MAX_COMMITS", "20"))

# receipts (idempotency)
MAX_RECEIPTS = int(os.getenv("THOMAS_WEBHOOK_MAX_RECEIPTS", "5000"))
RECEIPT_TTL_SECONDS = int(os.getenv("THOMAS_WEBHOOK_RECEIPT_TTL_SECONDS", str(7 * 24 * 3600)))  # 7 days

# Stripe signature verification
STRIPE_TOLERANCE_SECONDS = int(os.getenv("THOMAS_STRIPE_TOLERANCE_SECONDS", "300"))

# Store raw provider payloads in persistence metadata (can be large / sensitive)
STORE_RAW_PAYLOAD = os.getenv("THOMAS_WEBHOOK_STORE_RAW_PAYLOAD", "0").strip() not in ("0", "false", "False")

# Admin token for management endpoints (register/list/delete/patch/inbox)
ADMIN_TOKEN = os.getenv("THOMAS_WEBHOOK_ADMIN_TOKEN", "").strip() or None

# Rate limiting defaults (requests per minute); can be overridden per webhook in registration
DEFAULT_RATE_LIMIT_PER_MIN = int(os.getenv("THOMAS_WEBHOOK_RATE_LIMIT_PER_MIN", "120"))

# Inbox audit log
INBOX_STORE_BODY = os.getenv("THOMAS_WEBHOOK_INBOX_STORE_BODY", "1").strip() not in ("0", "false", "False")
INBOX_BODY_MAX_BYTES = int(os.getenv("THOMAS_WEBHOOK_INBOX_BODY_MAX_BYTES", "16384"))  # store up to 16KB preview
INBOX_TAIL_MAX_LINES = int(os.getenv("THOMAS_WEBHOOK_INBOX_TAIL_MAX_LINES", "5000"))  # for recent/retry lookups

# Thread lock for in-process concurrency (file stores also use cross-process lock)
_STORE_LOCK = threading.Lock()

_ENV_TRUE = {"1", "true", "yes", "on"}
_ENV_FALSE = {"0", "false", "no", "off"}
_RUNTIME_SIGNATURE_ENFORCEMENT_DEFAULT: Optional[bool] = None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _unix_now() -> int:
    return int(time.time())


def _parse_env_flag(name: str) -> Optional[bool]:
    raw = os.getenv(name)
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in _ENV_TRUE:
        return True
    if text in _ENV_FALSE:
        return False
    return None


def _is_production_environment() -> bool:
    for key in ("THOMAS_ENV", "ENV", "PYTHON_ENV"):
        value = str(os.getenv(key) or "").strip().lower()
        if value in {"prod", "production"}:
            return True
    return False


def configure_webhook_signature_enforcement_default(enabled: Optional[bool]) -> None:
    global _RUNTIME_SIGNATURE_ENFORCEMENT_DEFAULT
    if enabled is None:
        _RUNTIME_SIGNATURE_ENFORCEMENT_DEFAULT = None
    else:
        _RUNTIME_SIGNATURE_ENFORCEMENT_DEFAULT = bool(enabled)


def _webhook_signature_enforcement_enabled() -> bool:
    explicit = _parse_env_flag("THOMAS_WEBHOOK_REQUIRE_SIGNATURES")
    if explicit is not None:
        return explicit
    if _RUNTIME_SIGNATURE_ENFORCEMENT_DEFAULT is not None:
        return bool(_RUNTIME_SIGNATURE_ENFORCEMENT_DEFAULT)
    return _is_production_environment()


def _require_provider_secrets_for_signature_enforcement(
    *,
    provider: str,
    secrets: List[str],
    env_keys: List[str],
) -> None:
    if secrets or not _webhook_signature_enforcement_enabled():
        return
    joined = ", ".join(str(key).strip() for key in env_keys if str(key).strip())
    raise HTTPException(
        status_code=503,
        detail=(
            f"{provider} webhook signature enforcement is enabled; configure "
            f"{joined or 'provider secrets'}."
        ),
    )


def _require_generic_secret_for_signature_enforcement(rec: WebhookRecord) -> None:
    if rec.secret or not _webhook_signature_enforcement_enabled():
        return
    raise HTTPException(
        status_code=503,
        detail=(
            f"Webhook '{rec.id}' must have a secret when webhook signature enforcement is enabled "
            "(set THOMAS_WEBHOOK_REQUIRE_SIGNATURES=0 to disable for local development)."
        ),
    )


# -----------------------------
# Paths
# -----------------------------

def _default_store_path() -> Path:
    env = os.getenv("THOMAS_WEBHOOKS_FILE")
    if env:
        return Path(env).expanduser().resolve()

    p = get_persistence()
    for attr in ("runtime_dir", "data_dir", "storage_dir", "base_dir"):
        base = getattr(p, attr, None)
        if base:
            try:
                base_path = Path(base).expanduser().resolve()
                return base_path / "thomas_webhooks.json"
            except Exception:
                pass

    thomas_pkg_dir = Path(__file__).resolve().parents[3]
    return thomas_pkg_dir / "thomas_webhooks.json"


def _default_receipts_path(webhooks_path: Path) -> Path:
    env = os.getenv("THOMAS_WEBHOOK_RECEIPTS_FILE")
    if env:
        return Path(env).expanduser().resolve()
    return webhooks_path.with_name("thomas_webhook_receipts.json")


def _default_stats_path(webhooks_path: Path) -> Path:
    env = os.getenv("THOMAS_WEBHOOK_STATS_FILE")
    if env:
        return Path(env).expanduser().resolve()
    return webhooks_path.with_name("thomas_webhook_stats.json")


def _default_inbox_path(webhooks_path: Path) -> Path:
    env = os.getenv("THOMAS_WEBHOOK_INBOX_FILE")
    if env:
        return Path(env).expanduser().resolve()
    return webhooks_path.with_name("thomas_webhook_inbox.jsonl")


# -----------------------------
# JSON Stores
# -----------------------------

@dataclass(frozen=True)
class WebhookRecord:
    id: str
    secret: Optional[str]
    goal_template: str
    created_at: str
    rate_limit_per_min: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "secret": self.secret,
            "goal_template": self.goal_template,
            "created_at": self.created_at,
            "rate_limit_per_min": self.rate_limit_per_min,
        }


class WebhookStore:
    def __init__(self, path: Optional[Path] = None):
        self._path_override = path
        self._resolved_path: Optional[Path] = None

    def path(self) -> Path:
        if self._path_override is not None:
            return self._path_override
        if self._resolved_path is None:
            self._resolved_path = _default_store_path()
        return self._resolved_path

    def _lock_path(self) -> Path:
        return self.path().with_suffix(self.path().suffix + ".lock")

    def _load_unlocked(self) -> Dict[str, Any]:
        p = self.path()
        if not p.exists():
            return {"version": 2, "webhooks": {}}

        try:
            raw = p.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {"version": 2, "webhooks": {}}
        except Exception:
            raise HTTPException(status_code=500, detail="Webhook store is unreadable or corrupted.")

        if not isinstance(data, dict):
            raise HTTPException(status_code=500, detail="Webhook store is unreadable or corrupted.")
        if "webhooks" not in data or not isinstance(data["webhooks"], dict):
            return {"version": 2, "webhooks": {}}
        return data

    def _save_unlocked(self, data: Dict[str, Any]) -> None:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def list(self) -> List[WebhookRecord]:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            out: List[WebhookRecord] = []
            for wid, rec in data["webhooks"].items():
                if not isinstance(rec, dict):
                    continue
                out.append(
                    WebhookRecord(
                        id=str(wid),
                        secret=rec.get("secret"),
                        goal_template=str(rec.get("goal_template", "")),
                        created_at=str(rec.get("created_at", "")),
                        rate_limit_per_min=int(rec.get("rate_limit_per_min") or DEFAULT_RATE_LIMIT_PER_MIN),
                    )
                )
            out.sort(key=lambda r: r.id)
            return out

    def get(self, wid: str) -> Optional[WebhookRecord]:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            rec = data["webhooks"].get(wid)
            if not isinstance(rec, dict):
                return None
            return WebhookRecord(
                id=wid,
                secret=rec.get("secret"),
                goal_template=str(rec.get("goal_template", "")),
                created_at=str(rec.get("created_at", "")),
                rate_limit_per_min=int(rec.get("rate_limit_per_min") or DEFAULT_RATE_LIMIT_PER_MIN),
            )

    def upsert(self, rec: WebhookRecord) -> None:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            data["webhooks"][rec.id] = rec.to_dict()
            self._save_unlocked(data)

    def register(self, rec: WebhookRecord) -> None:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            if rec.id in data["webhooks"]:
                raise HTTPException(status_code=409, detail=f"Webhook '{rec.id}' already exists.")
            data["webhooks"][rec.id] = rec.to_dict()
            self._save_unlocked(data)

    def delete(self, wid: str) -> None:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            if wid not in data["webhooks"]:
                raise HTTPException(status_code=404, detail=f"Webhook '{wid}' not found.")
            del data["webhooks"][wid]
            self._save_unlocked(data)


class ReceiptStore:
    def __init__(self, path: Path):
        self.path = path

    def _lock_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".lock")

    def _load_unlocked(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "receipts": {}}
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {"version": 1, "receipts": {}}
        except Exception:
            raise HTTPException(status_code=500, detail="Webhook receipt store is unreadable or corrupted.")
        if not isinstance(data, dict) or "receipts" not in data or not isinstance(data["receipts"], dict):
            return {"version": 1, "receipts": {}}
        return data

    def _save_unlocked(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def _gc_unlocked(self, data: Dict[str, Any]) -> None:
        now = _unix_now()
        receipts = data.get("receipts", {})
        if not isinstance(receipts, dict):
            data["receipts"] = {}
            return

        dead = []
        for k, v in receipts.items():
            if not isinstance(v, dict):
                dead.append(k)
                continue
            ts = v.get("ts")
            if not isinstance(ts, int):
                dead.append(k)
                continue
            if now - ts > RECEIPT_TTL_SECONDS:
                dead.append(k)
        for k in dead:
            receipts.pop(k, None)

        if len(receipts) > MAX_RECEIPTS:
            items = []
            for k, v in receipts.items():
                ts = v.get("ts")
                if isinstance(ts, int):
                    items.append((ts, k))
            items.sort()
            drop = len(receipts) - MAX_RECEIPTS
            for _ts, k in items[:drop]:
                receipts.pop(k, None)

    def get_goal_id(self, key: str) -> Optional[str]:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            self._gc_unlocked(data)
            rec = data["receipts"].get(key)
            if isinstance(rec, dict) and isinstance(rec.get("goal_id"), str):
                self._save_unlocked(data)
                return rec["goal_id"]
            self._save_unlocked(data)
            return None

    def put(self, key: str, goal_id: str) -> None:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            self._gc_unlocked(data)
            data["receipts"][key] = {"goal_id": goal_id, "ts": _unix_now()}
            self._save_unlocked(data)


class StatsStore:
    """
    Transparent stats consumers love:
      - total_received, total_queued, total_duplicate, total_failed
      - last_received_at, last_goal_id, last_error
    """
    def __init__(self, path: Path):
        self.path = path

    def _lock_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".lock")

    def _load_unlocked(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "stats": {}}
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {"version": 1, "stats": {}}
        except Exception:
            return {"version": 1, "stats": {}}
        if not isinstance(data, dict) or "stats" not in data or not isinstance(data["stats"], dict):
            return {"version": 1, "stats": {}}
        return data

    def _save_unlocked(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def bump(self, key: str, **updates: Any) -> None:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            stats = data["stats"].setdefault(key, {})
            if not isinstance(stats, dict):
                stats = {}
                data["stats"][key] = stats

            for k, v in updates.items():
                if k.startswith("inc_"):
                    field = k[len("inc_"):]
                    stats[field] = int(stats.get(field) or 0) + int(v)
                else:
                    stats[k] = v
            self._save_unlocked(data)

    def get(self, key: str) -> Dict[str, Any]:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            stats = data["stats"].get(key)
            return stats if isinstance(stats, dict) else {}

    def all(self) -> Dict[str, Any]:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            return data["stats"] if isinstance(data.get("stats"), dict) else {}


class InboxLog:
    """
    Append-only audit log as JSONL.
    Helps operators answer: what hit my webhook? why did it fail? can I retry it?
    """
    def __init__(self, path: Path):
        self.path = path

    def _lock_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".lock")

    def append(self, record: Dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with _STORE_LOCK, _file_lock(self._lock_path()):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def tail(self, limit: int) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        if not self.path.exists():
            return []
        # Read up to INBOX_TAIL_MAX_LINES lines and then return last `limit`
        with _STORE_LOCK, _file_lock(self._lock_path()):
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except Exception:
                return []
        if len(lines) > INBOX_TAIL_MAX_LINES:
            lines = lines[-INBOX_TAIL_MAX_LINES:]
        out = []
        for ln in lines[-limit:]:
            try:
                obj = json.loads(ln)
                if isinstance(obj, dict):
                    out.append(obj)
            except Exception:
                continue
        return out

    def find_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        if not self.path.exists():
            return None
        with _STORE_LOCK, _file_lock(self._lock_path()):
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except Exception:
                return None
        if len(lines) > INBOX_TAIL_MAX_LINES:
            lines = lines[-INBOX_TAIL_MAX_LINES:]
        for ln in reversed(lines):
            try:
                obj = json.loads(ln)
                if isinstance(obj, dict) and obj.get("event_id") == event_id:
                    return obj
            except Exception:
                continue
        return None


_STORE = WebhookStore()
_RECEIPTS = ReceiptStore(_default_receipts_path(_STORE.path()))
_STATS = StatsStore(_default_stats_path(_STORE.path()))
_INBOX = InboxLog(_default_inbox_path(_STORE.path()))


# -----------------------------
# Rate limiter (in-memory token bucket)
# -----------------------------

class TokenBucket:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Dict[str, Tuple[float, float]] = {}  # key -> (tokens, last_ts)

    def allow(self, key: str, rate_per_min: int) -> bool:
        rate_per_min = max(1, int(rate_per_min))
        capacity = float(rate_per_min)
        refill_per_sec = float(rate_per_min) / 60.0

        now = time.time()
        with self._lock:
            tokens, last = self._state.get(key, (capacity, now))
            # refill
            tokens = min(capacity, tokens + (now - last) * refill_per_sec)
            if tokens < 1.0:
                self._state[key] = (tokens, now)
                return False
            tokens -= 1.0
            self._state[key] = (tokens, now)
            # opportunistic cleanup
            if len(self._state) > 5000:
                cutoff = now - 600
                self._state = {k: v for k, v in self._state.items() if v[1] >= cutoff}
            return True


_RATE_LIMITER = TokenBucket()


# -----------------------------
# Persistence adapter (goal queueing)
# -----------------------------

def _queue_goal(goal_text: str, source: str, metadata: Dict[str, Any]) -> str:
    p = get_persistence()
    goal_id = str(uuid.uuid4())

    methods = ("create_goal", "insert_goal", "add_goal", "queue_goal")
    text_kw_candidates = ("goal_text", "text", "goal")

    for m in methods:
        fn = getattr(p, m, None)
        if not callable(fn):
            continue

        for text_kw in text_kw_candidates:
            try:
                out = fn(**{text_kw: goal_text}, source=source, metadata=metadata, goal_id=goal_id)  # type: ignore[misc]
                return str(out) if out is not None else goal_id
            except TypeError:
                pass

        try:
            out = fn(goal_text, source=source, metadata=metadata, goal_id=goal_id)  # type: ignore[misc]
            return str(out) if out is not None else goal_id
        except TypeError:
            pass

    for fallback in ("put", "insert", "append"):
        fn = getattr(p, fallback, None)
        if callable(fn):
            record = {
                "id": goal_id,
                "text": goal_text,
                "source": source,
                "metadata": metadata,
                "status": "queued",
                "created_at": _now_iso(),
            }
            try:
                try:
                    fn("goals", record)  # type: ignore[misc]
                except TypeError:
                    fn(table="goals", value=record)  # type: ignore[misc]
                return goal_id
            except Exception:
                break

    raise HTTPException(
        status_code=500,
        detail="Persistence engine does not expose a goal insertion method (expected create_goal/insert_goal/add_goal/queue_goal).",
    )


# -----------------------------
# Helpers
# -----------------------------

def _split_secrets(env_value: Optional[str]) -> List[str]:
    if not env_value:
        return []
    out = []
    for s in env_value.split(","):
        s = s.strip()
        if s:
            out.append(s)
    return out


def _require_admin(x_admin_token: Optional[str]) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Webhook admin token is not configured. Set THOMAS_WEBHOOK_ADMIN_TOKEN.",
        )
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Missing X-Admin-Token.")
    if not hmac.compare_digest(ADMIN_TOKEN, x_admin_token):
        raise HTTPException(status_code=401, detail="Invalid X-Admin-Token.")


def _require_json_object(body: bytes) -> Dict[str, Any]:
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object.")
    return obj


def _payload_string(payload: Dict[str, Any]) -> str:
    s = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(s) > MAX_GOAL_PAYLOAD_CHARS:
        s = s[:MAX_GOAL_PAYLOAD_CHARS] + "\n…(truncated)"
    return s


async def _read_body_limited(request: Request) -> bytes:
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large.")
    return body


def _client_ip(request: Request) -> str:
    try:
        if request.client and request.client.host:
            return request.client.host
    except Exception:
        pass
    return "unknown"


# -----------------------------
# Signature helpers
# -----------------------------

def _hmac_sha256_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _normalize_sig(sig_header: str) -> Tuple[Optional[str], str]:
    sig_header = (sig_header or "").strip()
    if "=" in sig_header:
        algo, hexsig = sig_header.split("=", 1)
        return algo.strip().lower(), hexsig.strip().lower()
    return None, sig_header.lower()


def _validate_simple_hmac_any(secrets: List[str], body: bytes, signature_header: Optional[str], header_name: str) -> None:
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


def _validate_stripe_signature_any(secrets: List[str], body: bytes, stripe_sig_header: Optional[str]) -> None:
    if not stripe_sig_header:
        raise HTTPException(status_code=401, detail="Missing Stripe-Signature header.")

    parts = [p.strip() for p in stripe_sig_header.split(",") if p.strip()]
    kv: Dict[str, str] = {}
    v1s: List[str] = []
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

    signed = (f"{ts}.".encode("utf-8") + body)

    for secret in secrets:
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        for sig in v1s:
            if hmac.compare_digest(expected, sig):
                return

    raise HTTPException(status_code=401, detail="Invalid Stripe signature.")


# -----------------------------
# Stripe currency formatting
# -----------------------------

_ZERO_DECIMAL_CURRENCIES = {
    "BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG",
    "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
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


# -----------------------------
# Templating: {payload} and {payload.path.to.value}
# -----------------------------

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


def _interpolate_template(template: str, payload: Dict[str, Any]) -> str:
    # Fast path for classic {payload}
    full_payload_str = _payload_string(payload)

    def repl(match: re.Match) -> str:
        tok = match.group(0).strip("{}")
        if tok == "payload":
            return full_payload_str
        v = _get_by_path(payload, tok)
        return _stringify_value(v)

    return _PLACEHOLDER_RE.sub(repl, template)


# -----------------------------
# Inbox / stats updates
# -----------------------------

def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _inbox_record_base(
    *,
    provider: str,
    webhook_id: Optional[str],
    request: Optional[Request],
    body: bytes,
    signature_header: Optional[str],
    delivery_id: Optional[str],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rec: Dict[str, Any] = {
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


def _stats_key(provider: str, webhook_id: Optional[str]) -> str:
    return f"{provider}:{webhook_id or '-'}"


# -----------------------------
# Models
# -----------------------------

class RegisterWebhookRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    secret: Optional[str] = Field(default=None, max_length=2048)
    goal_template: str = Field(..., min_length=1, max_length=100_000)
    rate_limit_per_min: Optional[int] = Field(default=None, ge=1, le=100000)


class RegisterWebhookResponse(BaseModel):
    status: str
    id: str


class PatchWebhookRequest(BaseModel):
    secret: Optional[str] = Field(default=None, max_length=2048)
    goal_template: Optional[str] = Field(default=None, min_length=1, max_length=100_000)
    rate_limit_per_min: Optional[int] = Field(default=None, ge=1, le=100000)


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
    signature: Optional[str] = None


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


# -----------------------------
# Management routes
# -----------------------------

@webhook_router.post("/register", response_model=RegisterWebhookResponse)
async def register_webhook(
    body: RegisterWebhookRequest,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
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
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> Dict[str, Any]:
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
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> Dict[str, str]:
    _require_admin(x_admin_token)

    wid = id.strip()
    _STORE.delete(wid)
    _emit_event("webhook.deleted", {"id": wid})
    return {"status": "deleted", "id": wid}


@webhook_router.get("", response_model=List[Dict[str, Any]])
async def list_webhooks(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> List[Dict[str, Any]]:
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
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> Dict[str, Any]:
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
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> Dict[str, Any]:
    _require_admin(x_admin_token)
    return _STATS.all()


@webhook_router.get("/inbox/recent")
async def inbox_recent(
    limit: int = 50,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> List[Dict[str, Any]]:
    _require_admin(x_admin_token)
    return _INBOX.tail(limit)


@webhook_router.post("/inbox/retry/{event_id}", response_model=ReceiveWebhookResponse)
async def inbox_retry(
    event_id: str,
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
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
    payload: Dict[str, Any],
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> TestWebhookResponse:
    out = await test_webhook_impl(
        webhook_id=id,
        payload=payload,
        x_admin_token=x_admin_token,
        deps=_delivery_deps(),
    )
    return TestWebhookResponse(**out)


# -----------------------------
# Provider routes (must be declared before /receive/{id})
# -----------------------------

@webhook_router.post("/receive/github", response_model=ReceiveWebhookResponse)
async def receive_github_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: Optional[str] = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(default=None, alias="X-GitHub-Delivery"),
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
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
) -> ReceiveWebhookResponse:
    payload = await receive_stripe_webhook_impl(
        request=request,
        stripe_signature=stripe_signature,
        deps=_delivery_deps(),
    )
    return ReceiveWebhookResponse(**payload)


# -----------------------------
# Generic inbound endpoint
# -----------------------------

@webhook_router.post("/receive/{id}", response_model=ReceiveWebhookResponse)
async def receive_webhook(
    id: str,
    request: Request,
    x_webhook_signature: Optional[str] = Header(default=None, alias="X-Webhook-Signature"),
    x_webhook_delivery: Optional[str] = Header(default=None, alias="X-Webhook-Delivery"),
) -> ReceiveWebhookResponse:
    payload = await receive_webhook_impl(
        webhook_id=id,
        request=request,
        x_webhook_signature=x_webhook_signature,
        x_webhook_delivery=x_webhook_delivery,
        deps=_delivery_deps(),
    )
    return ReceiveWebhookResponse(**payload)
