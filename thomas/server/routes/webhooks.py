# thomas/server/routes/webhooks.py
from __future__ import annotations

import hmac
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from thomas.core.persistence import get_persistence
from thomas.server.routes.webhooks_utils import (
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
MAX_RECEIPTS = int(os.getenv("THOMAS_WEBHOOK_MAX_RECEIPTS", "5000"))
RECEIPT_TTL_SECONDS = int(os.getenv("THOMAS_WEBHOOK_RECEIPT_TTL_SECONDS", str(7 * 24 * 3600)))
STRIPE_TOLERANCE_SECONDS = int(os.getenv("THOMAS_STRIPE_TOLERANCE_SECONDS", "300"))
STORE_RAW_PAYLOAD = os.getenv("THOMAS_WEBHOOK_STORE_RAW_PAYLOAD", "0").strip() not in ("0", "false", "False")
ADMIN_TOKEN = os.getenv("THOMAS_WEBHOOK_ADMIN_TOKEN", "").strip() or None
DEFAULT_RATE_LIMIT_PER_MIN = int(os.getenv("THOMAS_WEBHOOK_RATE_LIMIT_PER_MIN", "120"))
INBOX_STORE_BODY = os.getenv("THOMAS_WEBHOOK_INBOX_STORE_BODY", "1").strip() not in ("0", "false", "False")
INBOX_BODY_MAX_BYTES = int(os.getenv("THOMAS_WEBHOOK_INBOX_BODY_MAX_BYTES", "16384"))
INBOX_TAIL_MAX_LINES = int(os.getenv("THOMAS_WEBHOOK_INBOX_TAIL_MAX_LINES", "5000"))
_STORE_LOCK = threading.Lock()

_ENV_TRUE = {"1", "true", "yes", "on"}
_ENV_FALSE = {"0", "false", "no", "off"}
_RUNTIME_SIGNATURE_ENFORCEMENT_DEFAULT: bool | None = None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _unix_now() -> int:
    return int(time.time())


def _parse_env_flag(name: str) -> bool | None:
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


def configure_webhook_signature_enforcement_default(enabled: bool | None) -> None:
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
    secrets: list[str],
    env_keys: list[str],
) -> None:
    if secrets or not _webhook_signature_enforcement_enabled():
        return
    joined = ", ".join(str(key).strip() for key in env_keys if str(key).strip())
    raise HTTPException(
        status_code=503,
        detail=(f"{provider} webhook signature enforcement is enabled; configure " f"{joined or 'provider secrets'}."),
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

    try:
        from thomas.core.config import resolve_thomas_data_dir

        return (resolve_thomas_data_dir() / "json" / "thomas_webhooks.json").resolve()
    except Exception:
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
    secret: str | None
    goal_template: str
    created_at: str
    rate_limit_per_min: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "secret": self.secret,
            "goal_template": self.goal_template,
            "created_at": self.created_at,
            "rate_limit_per_min": self.rate_limit_per_min,
        }


class WebhookStore:
    def __init__(self, path: Path | None = None):
        self._path_override = path
        self._resolved_path: Path | None = None

    def path(self) -> Path:
        if self._path_override is not None:
            return self._path_override
        if self._resolved_path is None:
            self._resolved_path = _default_store_path()
        return self._resolved_path

    def _lock_path(self) -> Path:
        return self.path().with_suffix(self.path().suffix + ".lock")

    def _load_unlocked(self) -> dict[str, Any]:
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

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def list(self) -> list[WebhookRecord]:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            out: list[WebhookRecord] = []
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

    def get(self, wid: str) -> WebhookRecord | None:
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

    def _load_unlocked(self) -> dict[str, Any]:
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

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def _gc_unlocked(self, data: dict[str, Any]) -> None:
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

    def get_goal_id(self, key: str) -> str | None:
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

    def _load_unlocked(self) -> dict[str, Any]:
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

    def _save_unlocked(self, data: dict[str, Any]) -> None:
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
                    field = k[len("inc_") :]
                    stats[field] = int(stats.get(field) or 0) + int(v)
                else:
                    stats[k] = v
            self._save_unlocked(data)

    def get(self, key: str) -> dict[str, Any]:
        with _STORE_LOCK, _file_lock(self._lock_path()):
            data = self._load_unlocked()
            stats = data["stats"].get(key)
            return stats if isinstance(stats, dict) else {}

    def all(self) -> dict[str, Any]:
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

    def append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with _STORE_LOCK, _file_lock(self._lock_path()):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def tail(self, limit: int) -> list[dict[str, Any]]:
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

    def find_event(self, event_id: str) -> dict[str, Any] | None:
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
        self._state: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)

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


def _queue_goal(goal_text: str, source: str, metadata: dict[str, Any]) -> str:
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


def _split_secrets(env_value: str | None) -> list[str]:
    if not env_value:
        return []
    out = []
    for s in env_value.split(","):
        s = s.strip()
        if s:
            out.append(s)
    return out


def _require_admin(x_admin_token: str | None) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Webhook admin token is not configured. Set THOMAS_WEBHOOK_ADMIN_TOKEN.",
        )
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Missing X-Admin-Token.")
    if not hmac.compare_digest(ADMIN_TOKEN, x_admin_token):
        raise HTTPException(status_code=401, detail="Invalid X-Admin-Token.")


def _require_json_object(body: bytes) -> dict[str, Any]:
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object.")
    return obj


def _payload_string(payload: dict[str, Any]) -> str:
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


def _emit_event(event_type: str, payload: dict[str, Any] | None = None) -> None:
    """Best-effort webhook audit event emission."""
    try:
        log_payload = dict(payload or {})
    except Exception:
        log_payload = {}
    try:
        import logging

        logging.getLogger(__name__).info("webhook.event %s %s", str(event_type or "").strip(), log_payload)
    except Exception:
        pass


from thomas.server.routes import webhooks_routes  # noqa: F401,E402
