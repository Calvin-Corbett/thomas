"""Background curator pipeline for durable memory promotion.

Curator responsibilities:
- Promote high-confidence profile hints/facts from new chat episodes.
- Promote durable research/library entries into global semantic facts.
- Keep incremental checkpoints so each run is idempotent and bounded.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


@dataclass
class CuratorConfig:
    enabled: bool = True
    min_interval_seconds: int = 180
    max_episode_scan: int = 120
    max_library_scan: int = 40
    max_promotions_per_run: int = 120
    min_profile_confidence: float = 0.72
    min_fact_confidence: float = 0.62


@dataclass
class CuratorRunResult:
    ran: bool
    reason: str
    episodes_scanned: int = 0
    library_entries_scanned: int = 0
    hints_promoted: int = 0
    facts_promoted: int = 0
    duplicates_skipped: int = 0
    last_episode_id: int = 0
    last_library_ts_utc: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ran": bool(self.ran),
            "reason": self.reason,
            "episodes_scanned": int(self.episodes_scanned),
            "library_entries_scanned": int(self.library_entries_scanned),
            "hints_promoted": int(self.hints_promoted),
            "facts_promoted": int(self.facts_promoted),
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
        library: Optional[ResearchLibrary] = None,
        config: Optional[CuratorConfig] = None,
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
        except Exception:
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
        thread_id: Optional[str],
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

    def _extract_episode_facts(self, text: str) -> List[Tuple[str, str, str, float]]:
        src = str(text or "")
        out: List[Tuple[str, str, str, float]] = []

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

        deduped: List[Tuple[str, str, str, float]] = []
        seen: set[Tuple[str, str, str]] = set()
        for subject, predicate, obj, conf in out:
            key = (subject.lower(), predicate.lower(), obj.lower())
            if key in seen:
                continue
            seen.add(key)
            deduped.append((subject, predicate, obj, conf))
        return deduped

    def _library_confidence(self, *, source: str, auto_captured: bool) -> float:
        src = str(source or "").strip().lower()
        conf = 0.64
        if auto_captured:
            conf -= 0.08
        if src.startswith("https://") or src.startswith("http://"):
            conf += 0.10
        if src.startswith("thomas:") or src.startswith("assistant:"):
            conf -= 0.04
        return max(0.45, min(0.90, conf))

    def _library_entry_excerpt(self, row: Dict[str, Any], *, max_chars: int = 280) -> str:
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
        except Exception:
            return ""
        return _norm_text(text, max_len=max_chars)

    def _curate_episode_row(
        self,
        row: Dict[str, Any],
        *,
        remaining_promotions: int,
    ) -> Tuple[int, int, int, int]:
        if remaining_promotions <= 0:
            return 0, 0, 0, 0

        role = str(row.get("role", "")).strip().lower()
        if role != "user":
            return 0, 0, 0, 0

        episode_id = int(row.get("id") or 0)
        thread_id = str(row.get("thread_id", "")).strip() or None
        ts_ms = int(row.get("ts_ms") or _now_ms())
        content = str(row.get("content") or "")

        scanned = 1
        hints_promoted = 0
        facts_promoted = 0
        duplicates = 0

        hints = [
            h for h in extract_profile_hints(content)
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
            if not self._reserve_promotion(
                source_kind="episode",
                source_ref=str(episode_id),
                promotion_kind="hint",
                fingerprint=fp,
            ):
                duplicates += 1
                continue
            self._fabric.upsert_profile_hints(
                thread_id=thread_id,
                hints=[{"key": h_key, "value": h_val, "confidence": float(hint.confidence)}],
                source_episode_id=episode_id,
                ts_ms=ts_ms,
            )
            hints_promoted += 1
            remaining_promotions -= 1

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
            if self._fact_exists(thread_id=thread_id, subject=s, predicate=p, obj=o):
                duplicates += 1
                continue
            fp = _fingerprint("fact", thread_id or "global", s, p, o)
            if not self._reserve_promotion(
                source_kind="episode",
                source_ref=str(episode_id),
                promotion_kind="fact",
                fingerprint=fp,
            ):
                duplicates += 1
                continue
            self._fabric.upsert_fact(
                thread_id=thread_id,
                subject=s,
                predicate=p,
                obj=o,
                confidence=confidence,
                provenance_episode_id=episode_id,
                ts_ms=ts_ms,
                base_salience=1.05,
            )
            facts_promoted += 1
            remaining_promotions -= 1

        return scanned, hints_promoted, facts_promoted, duplicates

    def _curate_library_row(
        self,
        row: Dict[str, Any],
        *,
        remaining_promotions: int,
    ) -> Tuple[int, int, int]:
        if self._library is None or remaining_promotions <= 0:
            return 0, 0, 0

        entry_id = str(row.get("id", "")).strip()
        if not entry_id:
            return 0, 0, 0

        title = _norm_text(str(row.get("title", "")), max_len=110)
        category = _safe_key(str(row.get("category", "uncategorized")), fallback="uncategorized")
        summary = _norm_text(str(row.get("summary", "")), max_len=240)
        source = _norm_text(str(row.get("source", "")), max_len=220)
        query = _norm_text(str(row.get("query", "")), max_len=140)
        auto_captured = bool(row.get("auto_captured"))
        excerpt = self._library_entry_excerpt(row, max_chars=260)

        evidence = summary or excerpt or query
        if not evidence:
            return 1, 0, 0

        confidence = self._library_confidence(source=source, auto_captured=auto_captured)
        if confidence < float(self._config.min_fact_confidence):
            return 1, 0, 0

        subject = title or f"library:{category}"
        predicate = f"library_{category}"
        obj_parts = [evidence]
        if source:
            obj_parts.append(f"source={source}")
        obj = _norm_text(" | ".join(obj_parts), max_len=300)

        facts_promoted = 0
        duplicates = 0
        if not self._fact_exists(thread_id=None, subject=subject, predicate=predicate, obj=obj):
            fp = _fingerprint("library_fact", subject, predicate, obj)
            if self._reserve_promotion(
                source_kind="library",
                source_ref=entry_id,
                promotion_kind="fact",
                fingerprint=fp,
            ):
                self._fabric.upsert_fact(
                    thread_id=None,
                    subject=subject,
                    predicate=predicate,
                    obj=obj,
                    confidence=confidence,
                    provenance_episode_id=None,
                    base_salience=1.03,
                )
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
                if self._fact_exists(thread_id=None, subject=t_subj, predicate=t_pred, obj=t_obj):
                    duplicates += 1
                    continue
                fp = _fingerprint("library_tag", t_subj, t_pred, t_obj)
                if not self._reserve_promotion(
                    source_kind="library",
                    source_ref=entry_id,
                    promotion_kind="tag_fact",
                    fingerprint=fp,
                ):
                    duplicates += 1
                    continue
                self._fabric.upsert_fact(
                    thread_id=None,
                    subject=t_subj,
                    predicate=t_pred,
                    obj=t_obj,
                    confidence=max(0.45, confidence - 0.06),
                    provenance_episode_id=None,
                    base_salience=0.98,
                )
                facts_promoted += 1
                remaining_promotions -= 1

        return 1, facts_promoted, duplicates

    def run(self, *, force: bool = False) -> Dict[str, Any]:
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
                scanned, hints, facts, dup = self._curate_episode_row(
                    rec,
                    remaining_promotions=remaining,
                )
                result.episodes_scanned += scanned
                result.hints_promoted += hints
                result.facts_promoted += facts
                result.duplicates_skipped += dup
                remaining -= (hints + facts)
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
                    scanned, facts, dup = self._curate_library_row(
                        row,
                        remaining_promotions=remaining,
                    )
                    result.library_entries_scanned += scanned
                    result.facts_promoted += facts
                    result.duplicates_skipped += dup
                    remaining -= facts
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
                except Exception as e:
                    log.debug("Curator global compact skipped: %s", e)

            return result.to_dict()

    def stats(self) -> Dict[str, Any]:
        promotions = int(
            self._fabric.db.execute("SELECT COUNT(*) c FROM curator_promotions").fetchone()["c"]
        )
        return {
            "enabled": bool(self._config.enabled),
            "min_interval_seconds": int(self._config.min_interval_seconds),
            "max_episode_scan": int(self._config.max_episode_scan),
            "max_library_scan": int(self._config.max_library_scan),
            "max_promotions_per_run": int(self._config.max_promotions_per_run),
            "last_run_ms": int(self._state_int(_STATE_LAST_RUN_MS, 0)),
            "last_episode_id": int(self._state_int(_STATE_LAST_EPISODE_ID, 0)),
            "last_library_ts_utc": int(self._state_int(_STATE_LAST_LIBRARY_TS, 0)),
            "promotions_total": promotions,
        }
