"""Background curator pipeline for durable memory promotion.

Curator responsibilities:
- Promote high-confidence profile hints/facts from new chat episodes.
- Promote durable research/library entries into global semantic facts.
- Keep incremental checkpoints so each run is idempotent and bounded.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from thomas.library import ResearchLibrary
from thomas.memory.v2.fabric import MemoryFabricV2
from thomas.memory.v2.profile_hints import extract_profile_hints

log = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")
_SAFE_KEY_RE = re.compile(r"[^a-z0-9_]+")

_RE_MY_FACT = re.compile(
    r"\bmy (?P<pred>[a-z][a-z0-9 _-]{1,40}) is (?P<obj>[^.!?\n]{2,160})",
    re.IGNORECASE,
)
_RE_BUILDING = re.compile(
    r"\bi (?:am building|build(?:ing)?|work(?:ing)? on)\s+(?P<obj>[^.!?\n]{2,180})",
    re.IGNORECASE,
)
_RE_USES = re.compile(
    r"\bi use (?P<obj>[^.!?\n]{2,120})",
    re.IGNORECASE,
)
_RE_TECH_STACK = re.compile(
    r"\bour (?:stack|tech stack) is (?P<obj>[^.!?\n]{2,180})",
    re.IGNORECASE,
)

_STATE_LAST_RUN_MS = "curator.last_run_ms"
_STATE_LAST_EPISODE_ID = "curator.last_episode_id"
_STATE_LAST_LIBRARY_TS = "curator.last_library_ts_utc"

_SOURCE_TRUST_BONUS = {
    "openai.com": 0.10,
    "docs.python.org": 0.10,
    "developer.mozilla.org": 0.09,
    "github.com": 0.07,
    "wikipedia.org": 0.05,
}

_SOURCE_LOW_TRUST = {
    "reddit.com",
    "x.com",
    "twitter.com",
    "t.co",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _norm_text(text: str, *, max_len: int = 240) -> str:
    s = _WS_RE.sub(" ", str(text or "").strip())
    s = s.strip(" \t\r\n.;,")
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return s


def _safe_key(text: str, *, fallback: str = "fact") -> str:
    s = _SAFE_KEY_RE.sub("_", str(text or "").strip().lower()).strip("_")
    if not s:
        return fallback
    return s[:64]


def _fingerprint(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(_norm_text(p, max_len=1200).lower().encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def extract_episode_facts(text: str) -> list[tuple[str, str, str, float]]:
    src = str(text or "")
    out: list[tuple[str, str, str, float]] = []

    for m in _RE_MY_FACT.finditer(src):
        raw_pred = _norm_text(m.group("pred"), max_len=48)
        raw_obj = _norm_text(m.group("obj"), max_len=180)
        if len(raw_pred) < 2 or len(raw_obj) < 2:
            continue
        out.append(("user", _safe_key(raw_pred, fallback="attribute"), raw_obj, 0.74))

    for m in _RE_BUILDING.finditer(src):
        raw_obj = _norm_text(m.group("obj"), max_len=180)
        if len(raw_obj) < 3:
            continue
        out.append(("user", "current_project", raw_obj, 0.66))

    for m in _RE_USES.finditer(src):
        raw_obj = _norm_text(m.group("obj"), max_len=140)
        if len(raw_obj) < 2:
            continue
        out.append(("user", "uses", raw_obj, 0.64))

    for m in _RE_TECH_STACK.finditer(src):
        raw_obj = _norm_text(m.group("obj"), max_len=180)
        if len(raw_obj) < 2:
            continue
        out.append(("project", "tech_stack", raw_obj, 0.67))

    deduped: list[tuple[str, str, str, float]] = []
    seen: set[tuple[str, str, str]] = set()
    for subject, predicate, obj, conf in out:
        key = (subject.lower(), predicate.lower(), obj.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((subject, predicate, obj, conf))
    return deduped


@dataclass
class CuratorConfig:
    enabled: bool = True
    min_interval_seconds: int = 180
    max_episode_scan: int = 120
    max_library_scan: int = 40
    max_promotions_per_run: int = 120
    min_profile_confidence: float = 0.72
    min_fact_confidence: float = 0.62
    approval_enabled: bool = True
    approval_auto_apply_confidence: float = 0.70
    approval_require_for_library: bool = True


@dataclass
class CuratorRunResult:
    ran: bool
    reason: str
    episodes_scanned: int = 0
    library_entries_scanned: int = 0
    hints_promoted: int = 0
    facts_promoted: int = 0
    queued_for_approval: int = 0
    duplicates_skipped: int = 0
    last_episode_id: int = 0
    last_library_ts_utc: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": bool(self.ran),
            "reason": self.reason,
            "episodes_scanned": int(self.episodes_scanned),
            "library_entries_scanned": int(self.library_entries_scanned),
            "hints_promoted": int(self.hints_promoted),
            "facts_promoted": int(self.facts_promoted),
            "queued_for_approval": int(self.queued_for_approval),
            "duplicates_skipped": int(self.duplicates_skipped),
            "last_episode_id": int(self.last_episode_id),
            "last_library_ts_utc": int(self.last_library_ts_utc),
        }


class MemoryCurator:
    """Promotes durable knowledge into Memory Fabric v2."""

    def __init__(
        self,
        fabric: MemoryFabricV2,
        *,
        library: ResearchLibrary | None = None,
        config: CuratorConfig | None = None,
    ) -> None:
        self._fabric = fabric
        self._library = library
        self._config = config or CuratorConfig()
        self._lock = threading.RLock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._fabric.db.transact() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS curator_state (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL,
                  updated_at_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS curator_promotions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_kind TEXT NOT NULL,
                  source_ref TEXT NOT NULL,
                  promotion_kind TEXT NOT NULL,
                  fingerprint TEXT NOT NULL,
                  created_at_ms INTEGER NOT NULL,
                  UNIQUE(source_kind, source_ref, promotion_kind, fingerprint)
                );

                CREATE INDEX IF NOT EXISTS idx_curator_promotions_source
                  ON curator_promotions(source_kind, source_ref, promotion_kind);

                CREATE TABLE IF NOT EXISTS curator_approval_queue (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_kind TEXT NOT NULL,
                  source_ref TEXT NOT NULL,
                  promotion_kind TEXT NOT NULL,
                  fingerprint TEXT NOT NULL UNIQUE,
                  thread_id TEXT,
                  payload_json TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  risk_level TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'pending',
                  decision_actor TEXT,
                  decision_reason TEXT,
                  created_at_ms INTEGER NOT NULL,
                  decided_at_ms INTEGER,
                  applied_at_ms INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_curator_approval_status
                  ON curator_approval_queue(status, risk_level, created_at_ms DESC);
                """
            )

    def _state_int(self, key: str, default: int = 0) -> int:
        row = self._fabric.db.execute(
            "SELECT value FROM curator_state WHERE key=?",
            (str(key),),
        ).fetchone()
        if row is None:
            return int(default)
        try:
            return int(row["value"])
        except (ValueError, TypeError):
            return int(default)

    def _set_state_int(self, key: str, value: int) -> None:
        now = self._fabric.db.now_ms()
        with self._fabric.db.transact() as conn:
            conn.execute(
                """
                INSERT INTO curator_state(key, value, updated_at_ms)
                VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                  value=excluded.value,
                  updated_at_ms=excluded.updated_at_ms
                """,
                (str(key), str(int(value)), now),
            )

    def _reserve_promotion(
        self,
        *,
        source_kind: str,
        source_ref: str,
        promotion_kind: str,
        fingerprint: str,
    ) -> bool:
        try:
            with self._fabric.db.transact() as conn:
                conn.execute(
                    """
                    INSERT INTO curator_promotions(
                      source_kind, source_ref, promotion_kind, fingerprint, created_at_ms
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        str(source_kind),
                        str(source_ref),
                        str(promotion_kind),
                        str(fingerprint),
                        self._fabric.db.now_ms(),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def _fact_exists(
        self,
        *,
        thread_id: str | None,
        subject: str,
        predicate: str,
        obj: str,
    ) -> bool:
        row = self._fabric.db.execute(
            """
            SELECT id FROM semantic_facts
            WHERE subject=? AND predicate=? AND obj=?
              AND ((thread_id IS NULL AND ? IS NULL) OR thread_id=?)
            LIMIT 1
            """,
            (subject, predicate, obj, thread_id, thread_id),
        ).fetchone()
        return row is not None

    def _domain_from_source(self, source: str) -> str:
        src = str(source or "").strip()
        if not src:
            return ""
        try:
            host = str(urlparse(src).hostname or "").strip().lower()
        except (ValueError, TypeError):
            host = ""
        if host.startswith("www."):
            host = host[4:]
        return host

    def _source_trust_score(self, source: str) -> float:
        src = str(source or "").strip().lower()
        if not src:
            return 0.48
        if src.startswith(("thomas:", "assistant:", "chat:")):
            return 0.42
        if src.startswith("file://"):
            return 0.50

        score = 0.56
        if src.startswith("https://"):
            score += 0.09
        elif src.startswith("http://"):
            score += 0.04

        host = self._domain_from_source(src)
        if host:
            if host in _SOURCE_TRUST_BONUS:
                score += float(_SOURCE_TRUST_BONUS[host])
            elif any(host.endswith(f".{key}") for key in _SOURCE_TRUST_BONUS):
                score += 0.04

            if host in _SOURCE_LOW_TRUST:
                score -= 0.08

        return max(0.35, min(0.95, score))

    def _recency_factor(self, updated_ts_utc: int | None) -> float:
        try:
            ts = int(updated_ts_utc or 0)
        except (ValueError, TypeError):
            ts = 0
        if ts <= 0:
            return 0.92
        now_s = int(time.time())
        age_days = max(0.0, float(now_s - ts) / 86400.0)
        half_life_days = 120.0
        decay = 0.5 ** (age_days / half_life_days)
        return max(0.72, min(1.06, 0.74 + (0.32 * decay)))

    def _promotion_risk_level(
        self,
        *,
        confidence: float,
        source_kind: str,
        promotion_kind: str,
    ) -> str:
        conf = float(max(0.0, min(1.0, confidence)))
        source = str(source_kind or "").strip().lower()
        p_kind = str(promotion_kind or "").strip().lower()
        if conf < 0.58:
            return "high"
        if source == "library" and conf < 0.72:
            return "high"
        if source == "library":
            return "medium"
        if p_kind == "hint" and conf >= 0.82:
            return "low"
        if conf >= 0.74:
            return "low"
        return "medium"

    def _requires_approval(
        self,
        *,
        source_kind: str,
        confidence: float,
        risk_level: str,
    ) -> bool:
        if not bool(self._config.approval_enabled):
            return False
        conf = float(max(0.0, min(1.0, confidence)))
        risk = str(risk_level or "").strip().lower()
        src = str(source_kind or "").strip().lower()
        if src == "library" and bool(self._config.approval_require_for_library):
            return True
        if risk == "high":
            return True
        return conf < float(self._config.approval_auto_apply_confidence)

    def _queue_promotion(
        self,
        *,
        source_kind: str,
        source_ref: str,
        promotion_kind: str,
        fingerprint: str,
        thread_id: str | None,
        confidence: float,
        risk_level: str,
        payload: dict[str, Any],
    ) -> bool:
        try:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except (ValueError, TypeError):
            return False
        try:
            with self._fabric.db.transact() as conn:
                conn.execute(
                    """
                    INSERT INTO curator_approval_queue(
                      source_kind,
                      source_ref,
                      promotion_kind,
                      fingerprint,
                      thread_id,
                      payload_json,
                      confidence,
                      risk_level,
                      status,
                      created_at_ms
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(source_kind),
                        str(source_ref),
                        str(promotion_kind),
                        str(fingerprint),
                        thread_id,
                        encoded,
                        float(confidence),
                        str(risk_level or "medium"),
                        "pending",
                        self._fabric.db.now_ms(),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def _is_payload_duplicate(self, payload: dict[str, Any]) -> bool:
        kind = str(payload.get("kind") or "").strip().lower()
        if kind == "hint":
            key = str(payload.get("key") or "").strip()
            value = _norm_text(str(payload.get("value") or ""), max_len=120)
            if not key or not value:
                return True
            row = self._fabric.db.execute(
                "SELECT value FROM profile_hints WHERE key=?",
                (key,),
            ).fetchone()
            return row is not None and _norm_text(str(row["value"]), max_len=120) == value

        if kind in ("fact", "tag_fact"):
            thread_id = payload.get("thread_id")
            thread = str(thread_id).strip() if thread_id is not None else None
            subject = _norm_text(str(payload.get("subject") or ""), max_len=80)
            predicate = _safe_key(str(payload.get("predicate") or ""), fallback="fact")
            obj = _norm_text(str(payload.get("obj") or ""), max_len=300)
            if not subject or not predicate or not obj:
                return True
            return self._fact_exists(thread_id=thread, subject=subject, predicate=predicate, obj=obj)

        return True

    def _apply_queued_payload(self, payload: dict[str, Any]) -> bool:
        kind = str(payload.get("kind") or "").strip().lower()
        if kind == "hint":
            key = _safe_key(str(payload.get("key") or ""), fallback="hint")
            value = _norm_text(str(payload.get("value") or ""), max_len=120)
            if not key or not value:
                return False
            thread_id = payload.get("thread_id")
            thread = str(thread_id).strip() if thread_id is not None else None
            try:
                episode_id = int(payload.get("source_episode_id") or 0)
            except (ValueError, TypeError):
                episode_id = 0
            self._fabric.upsert_profile_hints(
                thread_id=thread,
                hints=[
                    {
                        "key": key,
                        "value": value,
                        "confidence": float(payload.get("confidence", 0.5) or 0.5),
                    }
                ],
                source_episode_id=episode_id if episode_id > 0 else None,
                ts_ms=int(payload.get("ts_ms") or _now_ms()),
            )
            return True

        if kind in ("fact", "tag_fact"):
            thread_id = payload.get("thread_id")
            thread = str(thread_id).strip() if thread_id is not None else None
            subject = _norm_text(str(payload.get("subject") or ""), max_len=80)
            predicate = _safe_key(str(payload.get("predicate") or ""), fallback="fact")
            obj = _norm_text(str(payload.get("obj") or ""), max_len=300)
            if not subject or not predicate or not obj:
                return False
            if self._fact_exists(thread_id=thread, subject=subject, predicate=predicate, obj=obj):
                return True
            try:
                provenance_episode_id = int(payload.get("source_episode_id") or 0)
            except (ValueError, TypeError):
                provenance_episode_id = 0
            # `ts_ms` was dropped from upsert_fact's signature in v2 (the
            # function always uses `_now_ms()` internally for the
            # insert/update timestamp). Drop it from the call site rather
            # than re-adding it to the signature; tests don't care about
            # the exact ts.
            self._fabric.upsert_fact(
                thread_id=thread,
                subject=subject,
                predicate=predicate,
                obj=obj,
                confidence=float(payload.get("confidence", 0.5) or 0.5),
                provenance_episode_id=provenance_episode_id if provenance_episode_id > 0 else None,
                base_salience=float(payload.get("base_salience", 1.0) or 1.0),
            )
            return True

        return False

    def list_approval_queue(self, *, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
        lim = max(1, min(1000, int(limit)))
        st = str(status or "").strip().lower()
        if st:
            rows = self._fabric.db.execute(
                """
                SELECT * FROM curator_approval_queue
                WHERE status=?
                ORDER BY risk_level DESC, created_at_ms DESC
                LIMIT ?
                """,
                (st, lim),
            ).fetchall()
        else:
            rows = self._fabric.db.execute(
                """
                SELECT * FROM curator_approval_queue
                ORDER BY created_at_ms DESC
                LIMIT ?
                """,
                (lim,),
            ).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            rec = dict(row)
            payload_text = rec.get("payload_json")
            try:
                rec["payload"] = json.loads(payload_text) if payload_text else {}
            except (ValueError, json.JSONDecodeError):
                rec["payload"] = {}
            rec.pop("payload_json", None)
            out.append(rec)
        return out

    def decide_approval(
        self,
        approval_id: int,
        *,
        approve: bool,
        actor: str = "system",
        reason: str = "",
    ) -> dict[str, Any]:
        aid = int(approval_id)
        row = self._fabric.db.execute(
            "SELECT * FROM curator_approval_queue WHERE id=?",
            (aid,),
        ).fetchone()
        if row is None:
            raise KeyError(aid)
        rec = dict(row)
        status = str(rec.get("status") or "").strip().lower()
        if status not in ("pending", "approved"):
            return {
                "ok": True,
                "id": aid,
                "status": status or "unknown",
                "applied": bool(rec.get("applied_at_ms")),
            }

        now = self._fabric.db.now_ms()
        next_status = "denied"
        applied = False

        if approve:
            payload_text = rec.get("payload_json")
            try:
                payload = json.loads(payload_text) if payload_text else {}
            except (ValueError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict) and payload:
                if not self._is_payload_duplicate(payload):
                    applied = self._apply_queued_payload(payload)
                else:
                    applied = True
            if applied:
                self._reserve_promotion(
                    source_kind=str(rec.get("source_kind") or ""),
                    source_ref=str(rec.get("source_ref") or ""),
                    promotion_kind=str(rec.get("promotion_kind") or ""),
                    fingerprint=str(rec.get("fingerprint") or ""),
                )
            next_status = "applied" if applied else "approved"

        with self._fabric.db.transact() as conn:
            conn.execute(
                """
                UPDATE curator_approval_queue
                SET status=?,
                    decision_actor=?,
                    decision_reason=?,
                    decided_at_ms=?,
                    applied_at_ms=CASE WHEN ? THEN ? ELSE applied_at_ms END
                WHERE id=?
                """,
                (
                    next_status,
                    str(actor or "system"),
                    str(reason or ""),
                    now,
                    1 if applied else 0,
                    now,
                    aid,
                ),
            )

        return {
            "ok": True,
            "id": aid,
            "status": next_status,
            "applied": bool(applied),
        }

    def _extract_episode_facts(self, text: str) -> list[tuple[str, str, str, float]]:
        return extract_episode_facts(text)

    def _library_confidence(
        self,
        *,
        source: str,
        auto_captured: bool,
        updated_ts_utc: int | None,
    ) -> float:
        conf = self._source_trust_score(source)
        if auto_captured:
            conf -= 0.07
        conf *= self._recency_factor(updated_ts_utc)
        return max(0.40, min(0.92, conf))

    def _library_entry_excerpt(self, row: dict[str, Any], *, max_chars: int = 280) -> str:
        lib = self._library
        if lib is None:
            return ""
        rel = Path(str(row.get("path", "")).strip())
        if not rel:
            return ""
        abs_path = (lib.root / rel).resolve()
        try:
            abs_path.relative_to(lib.root)
        except ValueError:
            return ""
        if not abs_path.exists():
            return ""
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return ""
        return _norm_text(text, max_len=max_chars)

    def _curate_episode_row(
        self,
        row: dict[str, Any],
        *,
        remaining_promotions: int,
    ) -> tuple[int, int, int, int, int]:
        if remaining_promotions <= 0:
            return 0, 0, 0, 0, 0

        role = str(row.get("role", "")).strip().lower()
        if role != "user":
            return 0, 0, 0, 0, 0

        episode_id = int(row.get("id") or 0)
        thread_id = str(row.get("thread_id", "")).strip() or None
        ts_ms = int(row.get("ts_ms") or _now_ms())
        content = str(row.get("content") or "")

        scanned = 1
        hints_promoted = 0
        facts_promoted = 0
        queued = 0
        duplicates = 0

        hints = [
            h
            for h in extract_profile_hints(content)
            if float(h.confidence) >= float(self._config.min_profile_confidence)
        ]
        for hint in hints:
            if remaining_promotions <= 0:
                break
            h_key = _safe_key(hint.key, fallback="hint")
            h_val = _norm_text(hint.value, max_len=120)
            if not h_val:
                continue
            fp = _fingerprint("hint", h_key, h_val)
            payload = {
                "kind": "hint",
                "thread_id": thread_id,
                "key": h_key,
                "value": h_val,
                "confidence": float(hint.confidence),
                "source_episode_id": episode_id,
                "ts_ms": ts_ms,
            }
            if self._is_payload_duplicate(payload):
                duplicates += 1
                continue
            risk_level = self._promotion_risk_level(
                confidence=float(hint.confidence),
                source_kind="episode",
                promotion_kind="hint",
            )
            if self._requires_approval(
                source_kind="episode",
                confidence=float(hint.confidence),
                risk_level=risk_level,
            ):
                if self._queue_promotion(
                    source_kind="episode",
                    source_ref=str(episode_id),
                    promotion_kind="hint",
                    fingerprint=fp,
                    thread_id=thread_id,
                    confidence=float(hint.confidence),
                    risk_level=risk_level,
                    payload=payload,
                ):
                    queued += 1
                    remaining_promotions -= 1
                else:
                    duplicates += 1
                continue
            if not self._reserve_promotion(
                source_kind="episode",
                source_ref=str(episode_id),
                promotion_kind="hint",
                fingerprint=fp,
            ):
                duplicates += 1
                continue
            if self._apply_queued_payload(payload):
                hints_promoted += 1
                remaining_promotions -= 1
            else:
                duplicates += 1

        for subject, predicate, obj, conf in self._extract_episode_facts(content):
            if remaining_promotions <= 0:
                break
            confidence = float(max(0.0, min(1.0, conf)))
            if confidence < float(self._config.min_fact_confidence):
                continue
            s = _norm_text(subject, max_len=80)
            p = _safe_key(predicate, fallback="fact")
            o = _norm_text(obj, max_len=220)
            if not s or not p or not o:
                continue
            payload_thread_id = None if str(subject).strip().lower() in {"user", "project"} else thread_id
            fp = _fingerprint("fact", payload_thread_id or "global", s, p, o)
            payload = {
                "kind": "fact",
                "thread_id": payload_thread_id,
                "subject": s,
                "predicate": p,
                "obj": o,
                "confidence": confidence,
                "source_episode_id": episode_id,
                "ts_ms": ts_ms,
                "base_salience": 1.05,
            }
            if self._is_payload_duplicate(payload):
                duplicates += 1
                continue
            risk_level = self._promotion_risk_level(
                confidence=confidence,
                source_kind="episode",
                promotion_kind="fact",
            )
            if self._requires_approval(
                source_kind="episode",
                confidence=confidence,
                risk_level=risk_level,
            ):
                if self._queue_promotion(
                    source_kind="episode",
                    source_ref=str(episode_id),
                    promotion_kind="fact",
                    fingerprint=fp,
                    thread_id=thread_id,
                    confidence=confidence,
                    risk_level=risk_level,
                    payload=payload,
                ):
                    queued += 1
                    remaining_promotions -= 1
                else:
                    duplicates += 1
                continue
            if not self._reserve_promotion(
                source_kind="episode",
                source_ref=str(episode_id),
                promotion_kind="fact",
                fingerprint=fp,
            ):
                duplicates += 1
                continue
            if self._apply_queued_payload(payload):
                facts_promoted += 1
                remaining_promotions -= 1
            else:
                duplicates += 1

        return scanned, hints_promoted, facts_promoted, queued, duplicates

    def _curate_library_row(
        self,
        row: dict[str, Any],
        *,
        remaining_promotions: int,
    ) -> tuple[int, int, int, int]:
        if self._library is None or remaining_promotions <= 0:
            return 0, 0, 0, 0

        entry_id = str(row.get("id", "")).strip()
        if not entry_id:
            return 0, 0, 0, 0

        title = _norm_text(str(row.get("title", "")), max_len=110)
        category = _safe_key(str(row.get("category", "uncategorized")), fallback="uncategorized")
        summary = _norm_text(str(row.get("summary", "")), max_len=240)
        source = _norm_text(str(row.get("source", "")), max_len=220)
        query = _norm_text(str(row.get("query", "")), max_len=140)
        auto_captured = bool(row.get("auto_captured"))
        try:
            updated_ts_utc = int(row.get("updated_ts_utc", 0) or 0)
        except (ValueError, TypeError):
            updated_ts_utc = 0
        excerpt = self._library_entry_excerpt(row, max_chars=260)

        evidence = summary or excerpt or query
        if not evidence:
            return 1, 0, 0, 0

        confidence = self._library_confidence(
            source=source,
            auto_captured=auto_captured,
            updated_ts_utc=updated_ts_utc,
        )
        if confidence < float(self._config.min_fact_confidence):
            return 1, 0, 0, 0

        subject = title or f"library:{category}"
        predicate = f"library_{category}"
        obj_parts = [evidence]
        if source:
            obj_parts.append(f"source={source}")
        obj = _norm_text(" | ".join(obj_parts), max_len=300)

        facts_promoted = 0
        queued = 0
        duplicates = 0
        main_payload = {
            "kind": "fact",
            "thread_id": None,
            "subject": subject,
            "predicate": predicate,
            "obj": obj,
            "confidence": confidence,
            "source_episode_id": None,
            "ts_ms": _now_ms(),
            "base_salience": 1.03,
        }
        if self._is_payload_duplicate(main_payload):
            duplicates += 1
        else:
            fp = _fingerprint("library_fact", subject, predicate, obj)
            risk_level = self._promotion_risk_level(
                confidence=confidence,
                source_kind="library",
                promotion_kind="fact",
            )
            if self._requires_approval(
                source_kind="library",
                confidence=confidence,
                risk_level=risk_level,
            ):
                if self._queue_promotion(
                    source_kind="library",
                    source_ref=entry_id,
                    promotion_kind="fact",
                    fingerprint=fp,
                    thread_id=None,
                    confidence=confidence,
                    risk_level=risk_level,
                    payload=main_payload,
                ):
                    queued += 1
                    remaining_promotions -= 1
                else:
                    duplicates += 1
            elif self._reserve_promotion(
                source_kind="library",
                source_ref=entry_id,
                promotion_kind="fact",
                fingerprint=fp,
            ):
                if self._apply_queued_payload(main_payload):
                    facts_promoted += 1
                    remaining_promotions -= 1
                else:
                    duplicates += 1
            else:
                duplicates += 1

        tags = row.get("tags") or []
        if remaining_promotions > 0 and isinstance(tags, list):
            for raw_tag in tags[:3]:
                if remaining_promotions <= 0:
                    break
                tag = _safe_key(str(raw_tag), fallback="")
                if not tag:
                    continue
                t_subj = f"topic:{tag}"
                t_pred = "library_reference"
                t_obj = _norm_text(subject, max_len=120)
                tag_confidence = max(0.45, confidence - 0.06)
                tag_payload = {
                    "kind": "tag_fact",
                    "thread_id": None,
                    "subject": t_subj,
                    "predicate": t_pred,
                    "obj": t_obj,
                    "confidence": tag_confidence,
                    "source_episode_id": None,
                    "ts_ms": _now_ms(),
                    "base_salience": 0.98,
                }
                if self._is_payload_duplicate(tag_payload):
                    duplicates += 1
                    continue
                fp = _fingerprint("library_tag", t_subj, t_pred, t_obj)
                risk_level = self._promotion_risk_level(
                    confidence=tag_confidence,
                    source_kind="library",
                    promotion_kind="tag_fact",
                )
                if self._requires_approval(
                    source_kind="library",
                    confidence=tag_confidence,
                    risk_level=risk_level,
                ):
                    if self._queue_promotion(
                        source_kind="library",
                        source_ref=entry_id,
                        promotion_kind="tag_fact",
                        fingerprint=fp,
                        thread_id=None,
                        confidence=tag_confidence,
                        risk_level=risk_level,
                        payload=tag_payload,
                    ):
                        queued += 1
                        remaining_promotions -= 1
                    else:
                        duplicates += 1
                    continue
                if not self._reserve_promotion(
                    source_kind="library",
                    source_ref=entry_id,
                    promotion_kind="tag_fact",
                    fingerprint=fp,
                ):
                    duplicates += 1
                    continue
                if self._apply_queued_payload(tag_payload):
                    facts_promoted += 1
                    remaining_promotions -= 1
                else:
                    duplicates += 1

        return 1, facts_promoted, queued, duplicates

    def run(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if not self._config.enabled:
                return CuratorRunResult(ran=False, reason="disabled").to_dict()

            now = _now_ms()
            if not force:
                min_interval_ms = max(0, int(self._config.min_interval_seconds)) * 1000
                if min_interval_ms > 0:
                    last_run = self._state_int(_STATE_LAST_RUN_MS, 0)
                    if now - last_run < min_interval_ms:
                        return CuratorRunResult(ran=False, reason="interval_cooldown").to_dict()

            result = CuratorRunResult(ran=True, reason="ok")
            remaining = max(1, int(self._config.max_promotions_per_run))

            last_episode_id = self._state_int(_STATE_LAST_EPISODE_ID, 0)
            episode_rows = self._fabric.db.execute(
                """
                SELECT id, thread_id, ts_ms, role, content
                FROM episodes
                WHERE id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (int(last_episode_id), int(max(1, self._config.max_episode_scan))),
            ).fetchall()
            max_seen_episode = int(last_episode_id)
            for row in episode_rows:
                rec = dict(row)
                max_seen_episode = max(max_seen_episode, int(rec.get("id") or 0))
                scanned, hints, facts, queued, dup = self._curate_episode_row(
                    rec,
                    remaining_promotions=remaining,
                )
                result.episodes_scanned += scanned
                result.hints_promoted += hints
                result.facts_promoted += facts
                result.queued_for_approval += queued
                result.duplicates_skipped += dup
                remaining -= hints + facts + queued
                if remaining <= 0:
                    result.reason = "promotion_budget_reached"
                    break

            if max_seen_episode > last_episode_id:
                self._set_state_int(_STATE_LAST_EPISODE_ID, max_seen_episode)
                result.last_episode_id = max_seen_episode
            else:
                result.last_episode_id = last_episode_id

            last_library_ts = self._state_int(_STATE_LAST_LIBRARY_TS, 0)
            max_seen_library_ts = int(last_library_ts)
            if remaining > 0 and self._library is not None:
                lib_rows = self._library.scan_entries(
                    updated_after_ts_utc=last_library_ts,
                    limit=max(1, int(self._config.max_library_scan)),
                )
                for row in lib_rows:
                    max_seen_library_ts = max(
                        max_seen_library_ts,
                        int(row.get("updated_ts_utc", 0) or 0),
                    )
                    scanned, facts, queued, dup = self._curate_library_row(
                        row,
                        remaining_promotions=remaining,
                    )
                    result.library_entries_scanned += scanned
                    result.facts_promoted += facts
                    result.queued_for_approval += queued
                    result.duplicates_skipped += dup
                    remaining -= facts + queued
                    if remaining <= 0:
                        result.reason = "promotion_budget_reached"
                        break

            if max_seen_library_ts > last_library_ts:
                self._set_state_int(_STATE_LAST_LIBRARY_TS, max_seen_library_ts)
                result.last_library_ts_utc = max_seen_library_ts
            else:
                result.last_library_ts_utc = last_library_ts

            self._set_state_int(_STATE_LAST_RUN_MS, now)

            # Keep global pack fresh after curator promotions (best effort).
            if result.facts_promoted > 0 or result.hints_promoted > 0:
                try:
                    self._fabric.compact(thread_id=None)
                except (RuntimeError, OSError) as e:
                    log.debug("Curator global compact skipped: %s", e)

            return result.to_dict()

    def stats(self) -> dict[str, Any]:
        promotions = int(self._fabric.db.execute("SELECT COUNT(*) c FROM curator_promotions").fetchone()["c"])
        queue_rows = self._fabric.db.execute(
            """
            SELECT status, COUNT(*) AS c
            FROM curator_approval_queue
            GROUP BY status
            """
        ).fetchall()
        queue_counts: dict[str, int] = {}
        for row in queue_rows:
            status = str(row["status"] or "").strip().lower() or "unknown"
            queue_counts[status] = int(row["c"] or 0)
        return {
            "enabled": bool(self._config.enabled),
            "min_interval_seconds": int(self._config.min_interval_seconds),
            "max_episode_scan": int(self._config.max_episode_scan),
            "max_library_scan": int(self._config.max_library_scan),
            "max_promotions_per_run": int(self._config.max_promotions_per_run),
            "approval_enabled": bool(self._config.approval_enabled),
            "approval_auto_apply_confidence": float(self._config.approval_auto_apply_confidence),
            "approval_require_for_library": bool(self._config.approval_require_for_library),
            "last_run_ms": int(self._state_int(_STATE_LAST_RUN_MS, 0)),
            "last_episode_id": int(self._state_int(_STATE_LAST_EPISODE_ID, 0)),
            "last_library_ts_utc": int(self._state_int(_STATE_LAST_LIBRARY_TS, 0)),
            "promotions_total": promotions,
            "approval_queue": {
                "pending": int(queue_counts.get("pending", 0)),
                "approved": int(queue_counts.get("approved", 0)),
                "applied": int(queue_counts.get("applied", 0)),
                "denied": int(queue_counts.get("denied", 0)),
                "total": int(sum(queue_counts.values())),
            },
        }
