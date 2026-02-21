# thomas/server/routes/webhooks.py
from __future__ import annotations

import base64
import contextlib
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
from typing import Any, Dict, Iterator, List, Optional, Tuple

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from thomas.core.persistence import get_persistence

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
STORE_RAW_PAYLOAD = os.getenv("THOMAS_WEBHOOK_STORE_RAW_PAYLOAD", "1").strip() not in ("0", "false", "False")

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


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _unix_now() -> int:
    return int(time.time())


# -----------------------------
# Cross-process file lock (Windows + POSIX)
# -----------------------------

@contextlib.contextmanager
def _file_lock(lock_path: Path) -> Iterator[None]:
    """
    Cross-process lock using a companion lock file.

    - Windows: msvcrt.locking
    - POSIX: fcntl.flock
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt  # type: ignore

            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl  # type: ignore

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore

                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # type: ignore

                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            f.close()
        except Exception:
            pass


# -----------------------------
# Events (best-effort adapter)
# -----------------------------

def _emit_event(name: str, payload: Dict[str, Any]) -> None:
    """
    Best-effort hook into thomas/core/events.py without hard-binding to an API shape.
    This should never break webhook delivery.
    """
    try:
        from thomas.core import events as events_mod  # type: ignore

        for fn_name in ("emit", "publish", "send", "dispatch"):
            fn = getattr(events_mod, fn_name, None)
            if callable(fn):
                try:
                    fn(name, payload)  # type: ignore[misc]
                    return
                except TypeError:
                    try:
                        fn(event=name, payload=payload)  # type: ignore[misc]
                        return
                    except Exception:
                        return
    except Exception:
        return


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
    _require_admin(x_admin_token)
    rec = _INBOX.find_event(event_id)
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
        raise HTTPException(status_code=400, detail="Stored body not available for retry. Enable THOMAS_WEBHOOK_INBOX_STORE_BODY=1.")

    # For retry we bypass provider signature checks (we don't always have the original secret/header),
    # but we keep the original body hash + event id in metadata.
    if provider == "generic" and isinstance(webhook_id, str):
        payload = _require_json_object(body_bytes)
        goal_text = _interpolate_template(_STORE.get(webhook_id).goal_template, payload) if _STORE.get(webhook_id) else _payload_string(payload)
        meta: Dict[str, Any] = {"webhook_id": webhook_id, "retry_of_event_id": event_id, "body_sha256": rec.get("body_sha256")}
        if STORE_RAW_PAYLOAD:
            meta["raw"] = payload
        goal_id = _queue_goal(goal_text, "webhook.generic.retry", meta)
        _STATS.bump(_stats_key("generic", webhook_id), inc_total_received=1, inc_total_queued=1, last_received_at=_now_iso(), last_goal_id=goal_id, last_error=None)
        _emit_event("webhook.retried", {"provider": "generic", "webhook_id": webhook_id, "goal_id": goal_id, "event_id": event_id})
        return ReceiveWebhookResponse(status="queued", goal_id=goal_id)

    if provider == "github":
        payload = _require_json_object(body_bytes)
        repo = (
            payload.get("repository", {}).get("full_name")
            or payload.get("repository", {}).get("name")
            or "unknown-repo"
        )
        # Guess event from payload shape
        event = "push" if "commits" in payload and "ref" in payload else "pull_request" if "pull_request" in payload else "unknown"
        if event == "push":
            ref = payload.get("ref") or ""
            branch = ref.split("/")[-1] if isinstance(ref, str) and ref else "unknown"
            commits = payload.get("commits") or []
            messages: List[str] = []
            if isinstance(commits, list):
                for c in commits[:MAX_COMMITS_INCLUDED]:
                    if isinstance(c, dict):
                        m = c.get("message")
                        if isinstance(m, str) and m.strip():
                            messages.append(m.strip().replace("\n", " "))
            commit_messages = "; ".join(messages) if messages else "no commit messages"
            goal_text = f"Review and summarize the push to {repo} branch {branch}: {commit_messages}"
        elif event == "pull_request":
            pr = payload.get("pull_request") or {}
            number = payload.get("number") or pr.get("number") or "?"
            title = pr.get("title") or payload.get("title") or "Untitled"
            goal_text = f"Review PR #{number}: {title} in {repo}"
        else:
            raise HTTPException(status_code=400, detail="Retry could not infer GitHub event type from payload.")

        meta: Dict[str, Any] = {"provider": "github", "event": event, "repo": repo, "retry_of_event_id": event_id, "body_sha256": rec.get("body_sha256")}
        if STORE_RAW_PAYLOAD:
            meta["raw"] = payload
        goal_id = _queue_goal(goal_text, "webhook.github.retry", meta)
        _STATS.bump(_stats_key("github", None), inc_total_received=1, inc_total_queued=1, last_received_at=_now_iso(), last_goal_id=goal_id, last_error=None)
        _emit_event("webhook.retried", {"provider": "github", "goal_id": goal_id, "event_id": event_id})
        return ReceiveWebhookResponse(status="queued", goal_id=goal_id)

    if provider == "stripe":
        payload = _require_json_object(body_bytes)
        event_type = payload.get("type")
        if event_type != "payment_intent.succeeded":
            raise HTTPException(status_code=400, detail="Retry only supports payment_intent.succeeded.")
        obj = (((payload.get("data") or {}).get("object")) or {})
        if not isinstance(obj, dict):
            obj = {}
        amount = obj.get("amount_received") or obj.get("amount") or 0
        currency = (obj.get("currency") or "").upper() or "USD"
        customer = obj.get("customer") or obj.get("receipt_email") or obj.get("customer_email") or "unknown"
        amount_str = _format_stripe_amount(amount, currency)
        goal_text = f"Log successful payment of {amount_str} {currency} from {customer}"
        meta: Dict[str, Any] = {"provider": "stripe", "event": event_type, "retry_of_event_id": event_id, "body_sha256": rec.get("body_sha256")}
        if STORE_RAW_PAYLOAD:
            meta["raw"] = payload
        goal_id = _queue_goal(goal_text, "webhook.stripe.retry", meta)
        _STATS.bump(_stats_key("stripe", None), inc_total_received=1, inc_total_queued=1, last_received_at=_now_iso(), last_goal_id=goal_id, last_error=None)
        _emit_event("webhook.retried", {"provider": "stripe", "goal_id": goal_id, "event_id": event_id})
        return ReceiveWebhookResponse(status="queued", goal_id=goal_id)

    raise HTTPException(status_code=400, detail=f"Unsupported provider for retry: {provider}")


@webhook_router.post("/test/{id}", response_model=TestWebhookResponse)
async def test_webhook(
    id: str,
    payload: Dict[str, Any],
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
) -> TestWebhookResponse:
    """
    Consumers love this: a built-in "does my template work?" test.
    Generates the goal exactly like /receive/{id} and returns the goal_id.
    If the webhook has a secret, this also returns the signature value it expects.
    """
    _require_admin(x_admin_token)

    wid = id.strip()
    rec = _STORE.get(wid)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Webhook '{wid}' not registered.")

    body = json.dumps(payload).encode("utf-8")
    signature = None
    if rec.secret:
        signature = "sha256=" + _hmac_sha256_hex(rec.secret, body)

    # bypass rate limit for tests
    goal_text = _interpolate_template(rec.goal_template, payload)
    meta: Dict[str, Any] = {"webhook_id": wid, "test": True}
    if STORE_RAW_PAYLOAD:
        meta["raw"] = payload
    goal_id = _queue_goal(goal_text, "webhook.generic.test", meta)

    _STATS.bump(_stats_key("generic", wid), inc_total_received=1, inc_total_queued=1, last_received_at=_now_iso(), last_goal_id=goal_id, last_error=None)
    return TestWebhookResponse(status="queued", goal_id=goal_id, signature=signature)


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
    secrets = _split_secrets(os.getenv("THOMAS_GITHUB_WEBHOOK_SECRET")) or _split_secrets(os.getenv("THOMAS_GITHUB_WEBHOOK_SECRETS"))
    if not secrets:
        raise HTTPException(status_code=500, detail="GitHub webhook secret not configured (THOMAS_GITHUB_WEBHOOK_SECRET).")

    body = await _read_body_limited(request)

    # idempotency before work (GitHub retries are common)
    if x_github_delivery:
        existing = _RECEIPTS.get_goal_id(f"github:{x_github_delivery}")
        if existing:
            _STATS.bump(_stats_key("github", None), inc_total_received=1, inc_total_duplicate=1, last_received_at=_now_iso(), last_goal_id=existing)
            return ReceiveWebhookResponse(status="duplicate", goal_id=existing)

    # validate signature
    _validate_simple_hmac_any(secrets, body, x_hub_signature_256, "X-Hub-Signature-256")
    payload = _require_json_object(body)
    event = (x_github_event or "").strip().lower()

    inbox_rec = _inbox_record_base(
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
            _INBOX.append(inbox_rec)
            _STATS.bump(_stats_key("github", None), inc_total_received=1, inc_total_queued=1, last_received_at=_now_iso(), last_goal_id="noop", last_error=None)
            return ReceiveWebhookResponse(status="queued", goal_id="noop")

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
                for c in commits[:MAX_COMMITS_INCLUDED]:
                    if isinstance(c, dict):
                        m = c.get("message")
                        if isinstance(m, str) and m.strip():
                            messages.append(m.strip().replace("\n", " "))
            commit_messages = "; ".join(messages) if messages else "no commit messages"
            goal_text = f"Review and summarize the push to {repo} branch {branch}: {commit_messages}"

        elif event == "pull_request":
            pr = payload.get("pull_request") or {}
            number = payload.get("number") or pr.get("number") or "?"
            title = pr.get("title") or payload.get("title") or "Untitled"
            goal_text = f"Review PR #{number}: {title} in {repo}"

        else:
            raise HTTPException(status_code=400, detail=f"Unsupported GitHub event: {event or 'unknown'}")

        meta: Dict[str, Any] = {"provider": "github", "event": event, "repo": repo}
        if x_github_delivery:
            meta["delivery"] = x_github_delivery
        if STORE_RAW_PAYLOAD:
            meta["raw"] = payload

        goal_id = _queue_goal(goal_text, "webhook.github", meta)

        if x_github_delivery:
            _RECEIPTS.put(f"github:{x_github_delivery}", goal_id)

        inbox_rec["status"] = "queued"
        inbox_rec["goal_id"] = goal_id
        _INBOX.append(inbox_rec)

        _STATS.bump(_stats_key("github", None), inc_total_received=1, inc_total_queued=1, last_received_at=_now_iso(), last_goal_id=goal_id, last_error=None)
        _emit_event("webhook.received", {"provider": "github", "event": event, "repo": repo, "goal_id": goal_id})
        return ReceiveWebhookResponse(status="queued", goal_id=goal_id)

    except HTTPException as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = str(e.detail)
        _INBOX.append(inbox_rec)
        _STATS.bump(_stats_key("github", None), inc_total_received=1, inc_total_failed=1, last_received_at=_now_iso(), last_error=str(e.detail))
        raise
    except Exception as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = f"Unhandled error: {e}"
        _INBOX.append(inbox_rec)
        _STATS.bump(_stats_key("github", None), inc_total_received=1, inc_total_failed=1, last_received_at=_now_iso(), last_error=str(e))
        raise HTTPException(status_code=500, detail="Unhandled error processing GitHub webhook.")


@webhook_router.post("/receive/stripe", response_model=ReceiveWebhookResponse)
async def receive_stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
) -> ReceiveWebhookResponse:
    body = await _read_body_limited(request)
    stripe_secrets = _split_secrets(os.getenv("THOMAS_STRIPE_WEBHOOK_SECRET")) or _split_secrets(os.getenv("THOMAS_STRIPE_WEBHOOK_SECRETS"))

    # validate signature if configured
    if stripe_secrets:
        _validate_stripe_signature_any(stripe_secrets, body, stripe_signature)

    payload = _require_json_object(body)
    event_id = payload.get("id") if isinstance(payload.get("id"), str) else None
    event_type = payload.get("type")

    inbox_rec = _inbox_record_base(
        provider="stripe",
        webhook_id=None,
        request=request,
        body=body,
        signature_header=stripe_signature,
        delivery_id=event_id,
        extra={"event": event_type},
    )

    # idempotency
    if event_id:
        existing = _RECEIPTS.get_goal_id(f"stripe:{event_id}")
        if existing:
            inbox_rec["status"] = "duplicate"
            inbox_rec["goal_id"] = existing
            _INBOX.append(inbox_rec)
            _STATS.bump(_stats_key("stripe", None), inc_total_received=1, inc_total_duplicate=1, last_received_at=_now_iso(), last_goal_id=existing)
            return ReceiveWebhookResponse(status="duplicate", goal_id=existing)

    try:
        if event_type != "payment_intent.succeeded":
            raise HTTPException(status_code=400, detail=f"Unsupported Stripe event: {event_type}")

        obj = (((payload.get("data") or {}).get("object")) or {})
        if not isinstance(obj, dict):
            obj = {}

        amount = obj.get("amount_received") or obj.get("amount") or 0
        currency = (obj.get("currency") or "").upper() or "USD"
        customer = obj.get("customer") or obj.get("receipt_email") or obj.get("customer_email") or "unknown"

        amount_str = _format_stripe_amount(amount, currency)
        goal_text = f"Log successful payment of {amount_str} {currency} from {customer}"

        meta: Dict[str, Any] = {"provider": "stripe", "event": event_type, "currency": currency}
        if event_id:
            meta["event_id"] = event_id
        if STORE_RAW_PAYLOAD:
            meta["raw"] = payload

        goal_id = _queue_goal(goal_text, "webhook.stripe", meta)

        if event_id:
            _RECEIPTS.put(f"stripe:{event_id}", goal_id)

        inbox_rec["status"] = "queued"
        inbox_rec["goal_id"] = goal_id
        _INBOX.append(inbox_rec)

        _STATS.bump(_stats_key("stripe", None), inc_total_received=1, inc_total_queued=1, last_received_at=_now_iso(), last_goal_id=goal_id, last_error=None)
        _emit_event("webhook.received", {"provider": "stripe", "event": event_type, "goal_id": goal_id})
        return ReceiveWebhookResponse(status="queued", goal_id=goal_id)

    except HTTPException as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = str(e.detail)
        _INBOX.append(inbox_rec)
        _STATS.bump(_stats_key("stripe", None), inc_total_received=1, inc_total_failed=1, last_received_at=_now_iso(), last_error=str(e.detail))
        raise
    except Exception as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = f"Unhandled error: {e}"
        _INBOX.append(inbox_rec)
        _STATS.bump(_stats_key("stripe", None), inc_total_received=1, inc_total_failed=1, last_received_at=_now_iso(), last_error=str(e))
        raise HTTPException(status_code=500, detail="Unhandled error processing Stripe webhook.")


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
    wid = id.strip()
    rec = _STORE.get(wid)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Webhook '{wid}' not registered.")

    # rate limiting (per webhook + ip)
    rl_key = f"{wid}:{_client_ip(request)}"
    if not _RATE_LIMITER.allow(rl_key, rec.rate_limit_per_min):
        _STATS.bump(_stats_key("generic", wid), inc_total_received=1, inc_total_failed=1, last_received_at=_now_iso(), last_error="rate_limited")
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    body = await _read_body_limited(request)

    # idempotency
    if x_webhook_delivery:
        existing = _RECEIPTS.get_goal_id(f"generic:{wid}:{x_webhook_delivery}")
        if existing:
            _STATS.bump(_stats_key("generic", wid), inc_total_received=1, inc_total_duplicate=1, last_received_at=_now_iso(), last_goal_id=existing)
            inbox_rec = _inbox_record_base(provider="generic", webhook_id=wid, request=request, body=body, signature_header=x_webhook_signature, delivery_id=x_webhook_delivery, extra={"status": "duplicate", "goal_id": existing})
            _INBOX.append(inbox_rec)
            return ReceiveWebhookResponse(status="duplicate", goal_id=existing)

    inbox_rec = _inbox_record_base(
        provider="generic",
        webhook_id=wid,
        request=request,
        body=body,
        signature_header=x_webhook_signature,
        delivery_id=x_webhook_delivery,
        extra=None,
    )

    try:
        # Validate signature if secret is set
        if rec.secret:
            _validate_simple_hmac_any([rec.secret], body, x_webhook_signature, "X-Webhook-Signature")

        payload = _require_json_object(body)
        goal_text = _interpolate_template(rec.goal_template, payload)

        meta: Dict[str, Any] = {"webhook_id": wid}
        if x_webhook_delivery:
            meta["delivery"] = x_webhook_delivery
        if STORE_RAW_PAYLOAD:
            meta["raw"] = payload

        goal_id = _queue_goal(goal_text, "webhook.generic", meta)

        if x_webhook_delivery:
            _RECEIPTS.put(f"generic:{wid}:{x_webhook_delivery}", goal_id)

        inbox_rec["status"] = "queued"
        inbox_rec["goal_id"] = goal_id
        _INBOX.append(inbox_rec)

        _STATS.bump(_stats_key("generic", wid), inc_total_received=1, inc_total_queued=1, last_received_at=_now_iso(), last_goal_id=goal_id, last_error=None)
        _emit_event("webhook.received", {"provider": "generic", "webhook_id": wid, "goal_id": goal_id})
        return ReceiveWebhookResponse(status="queued", goal_id=goal_id)

    except HTTPException as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = str(e.detail)
        _INBOX.append(inbox_rec)
        _STATS.bump(_stats_key("generic", wid), inc_total_received=1, inc_total_failed=1, last_received_at=_now_iso(), last_error=str(e.detail))
        raise
    except Exception as e:
        inbox_rec["status"] = "failed"
        inbox_rec["error"] = f"Unhandled error: {e}"
        _INBOX.append(inbox_rec)
        _STATS.bump(_stats_key("generic", wid), inc_total_received=1, inc_total_failed=1, last_received_at=_now_iso(), last_error=str(e))
        raise HTTPException(status_code=500, detail="Unhandled error processing webhook.")
