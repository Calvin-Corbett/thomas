"""Unified autonomy memory runtime for Thomas.

This module composes both memory backends:
- Legacy `MemoryEngine` for compatibility APIs and existing indexes.
- `MemoryFabricV2` for policy-driven retrieval (thread + global/profile memory).

The goal is a single memory surface used across all channels (web, REPL, CLI,
Telegram) so autonomy behavior stays consistent.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from thomas.core.config import AppConfig
from thomas.memory import autonomy_services

log = logging.getLogger(__name__)

_GLOBAL_RETRIEVAL_THREAD_ID = "__global__"
_GLOBAL_EPISODE_FACT_SUBJECTS = frozenset({"user", "project"})


@dataclass
class _MemoryText:
    text: str


class AutonomyMemoryEngine:
    """Runtime memory facade with v2-first retrieval policy."""

    def __init__(
        self,
        config: AppConfig,
        *,
        enable_legacy: bool = False,
        enable_v2: bool = True,
    ) -> None:
        self._config = config
        self._enable_legacy = bool(enable_legacy)
        self._enable_v2 = bool(enable_v2)
        self._started = False

        self._legacy: Any | None = None
        self._fabric_v2: Any | None = None
        self._curator: Any | None = None
        self._curator_last_result: dict[str, Any] = {}

        self._curator_enabled = str(os.environ.get("THOMAS_MEMORY_CURATOR_ENABLED", "1")).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        try:
            self._curator_min_interval_s = max(
                0, int(os.environ.get("THOMAS_MEMORY_CURATOR_MIN_INTERVAL_SECONDS", "180") or 180)
            )
        except (ValueError, TypeError):
            self._curator_min_interval_s = 180
        try:
            self._curator_max_episode_scan = max(
                10, int(os.environ.get("THOMAS_MEMORY_CURATOR_MAX_EPISODE_SCAN", "120") or 120)
            )
        except (ValueError, TypeError):
            self._curator_max_episode_scan = 120
        try:
            self._curator_max_library_scan = max(
                10, int(os.environ.get("THOMAS_MEMORY_CURATOR_MAX_LIBRARY_SCAN", "40") or 40)
            )
        except (ValueError, TypeError):
            self._curator_max_library_scan = 40
        try:
            self._curator_max_promotions = max(
                10, int(os.environ.get("THOMAS_MEMORY_CURATOR_MAX_PROMOTIONS_PER_RUN", "120") or 120)
            )
        except (ValueError, TypeError):
            self._curator_max_promotions = 120
        self._curator_approval_enabled = str(
            os.environ.get("THOMAS_MEMORY_CURATOR_APPROVAL_ENABLED", "1")
        ).strip().lower() in ("1", "true", "yes", "on")
        try:
            self._curator_approval_auto_apply_conf = float(
                os.environ.get("THOMAS_MEMORY_CURATOR_APPROVAL_AUTO_APPLY_CONFIDENCE", "0.70") or 0.70
            )
        except (ValueError, TypeError):
            self._curator_approval_auto_apply_conf = 0.70
        self._curator_approval_auto_apply_conf = max(
            0.0,
            min(1.0, float(self._curator_approval_auto_apply_conf)),
        )
        self._curator_approval_for_library = str(
            os.environ.get("THOMAS_MEMORY_CURATOR_APPROVAL_REQUIRE_LIBRARY", "1")
        ).strip().lower() in ("1", "true", "yes", "on")

        self._token_report_compact_enabled = str(
            os.environ.get("THOMAS_MEMORY_AUTO_COMPACT_FROM_TOKEN_REPORT", "1")
        ).strip().lower() in ("1", "true", "yes", "on")
        try:
            self._token_report_prompt_threshold = max(
                500, int(os.environ.get("THOMAS_MEMORY_AUTO_COMPACT_PROMPT_TOKENS", "12000") or 12000)
            )
        except (ValueError, TypeError):
            self._token_report_prompt_threshold = 12000
        try:
            self._token_report_total_threshold = max(
                1000, int(os.environ.get("THOMAS_MEMORY_AUTO_COMPACT_TOTAL_TOKENS", "18000") or 18000)
            )
        except (ValueError, TypeError):
            self._token_report_total_threshold = 18000
        try:
            self._token_report_memory_share_threshold = max(
                0.05,
                min(
                    1.0,
                    float(os.environ.get("THOMAS_MEMORY_AUTO_COMPACT_MEMORY_SHARE", "0.42") or 0.42),
                ),
            )
        except (ValueError, TypeError):
            self._token_report_memory_share_threshold = 0.42
        try:
            self._token_report_budget_pressure_threshold = max(
                0.10,
                min(
                    1.5,
                    float(os.environ.get("THOMAS_MEMORY_AUTO_COMPACT_BUDGET_PRESSURE", "0.90") or 0.90),
                ),
            )
        except (ValueError, TypeError):
            self._token_report_budget_pressure_threshold = 0.90
        try:
            self._token_report_min_interval_s = max(
                0, int(os.environ.get("THOMAS_MEMORY_AUTO_COMPACT_MIN_INTERVAL_SECONDS", "300") or 300)
            )
        except (ValueError, TypeError):
            self._token_report_min_interval_s = 300
        self._token_report_last_compact_ms: dict[str, int] = {}

        # Keep memory packs dense but bounded; the agent prompt has its own
        # larger budget and should not be monopolized by memory text.
        cfg_budget = int(getattr(config.memory, "context_budget", 1200) or 1200)
        self._pack_budget_default = max(400, min(cfg_budget, 1800))
        self._pack_budget_min = 250
        self._pack_budget_max = 2400

    @property
    def started(self) -> bool:
        return self._started

    @property
    def has_v2(self) -> bool:
        return self._fabric_v2 is not None

    def start(self) -> None:
        if self._started:
            return

        legacy_ok = False
        v2_ok = False

        if self._enable_legacy:
            try:
                from thomas.memory import MemoryEngine

                legacy = MemoryEngine(self._config)
                legacy.start()
                self._legacy = legacy
                legacy_ok = bool(getattr(legacy, "started", False))
                log.info("Legacy memory backend started.")
            except (ImportError, RuntimeError, OSError) as e:
                log.warning("Legacy memory backend unavailable: %s", e)

        if self._enable_v2:
            try:
                from thomas.memory.v2 import MemoryFabricV2

                root_path = str(self._config.memory.root_path / ".thomas")
                self._fabric_v2 = MemoryFabricV2(root_path=root_path)
                v2_ok = True
                log.info("Memory Fabric v2 backend started at %s", root_path)
            except (ImportError, RuntimeError, OSError) as e:
                log.warning("Memory Fabric v2 backend unavailable: %s", e)

        if self._fabric_v2 is not None and self._curator_enabled:
            try:
                from thomas.library import ResearchLibrary, default_library_root
                from thomas.memory.curator import CuratorConfig, MemoryCurator

                lib = ResearchLibrary(default_library_root(self._config))
                curator_cfg = CuratorConfig(
                    enabled=True,
                    min_interval_seconds=self._curator_min_interval_s,
                    max_episode_scan=self._curator_max_episode_scan,
                    max_library_scan=self._curator_max_library_scan,
                    max_promotions_per_run=self._curator_max_promotions,
                    approval_enabled=self._curator_approval_enabled,
                    approval_auto_apply_confidence=self._curator_approval_auto_apply_conf,
                    approval_require_for_library=self._curator_approval_for_library,
                )
                self._curator = MemoryCurator(
                    self._fabric_v2,
                    library=lib,
                    config=curator_cfg,
                )
                log.info(
                    "Memory curator enabled (interval=%ss, episode_scan=%s, library_scan=%s).",
                    self._curator_min_interval_s,
                    self._curator_max_episode_scan,
                    self._curator_max_library_scan,
                )
            except (ImportError, RuntimeError, OSError) as e:
                log.warning("Memory curator unavailable: %s", e)

        self._started = bool(legacy_ok or v2_ok)
        if not self._started:
            raise RuntimeError("No memory backend could be started.")

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("AutonomyMemoryEngine.start() must be called first")

    def _event_role(self, etype: str) -> str:
        e = str(etype or "").lower()
        if "user" in e:
            return "user"
        if "assistant" in e or "agent" in e:
            return "assistant"
        if "tool" in e:
            return "tool"
        return "system"

    def _budget_for_mode(self, budget: int | None, mode: str) -> int:
        b = int(budget or self._pack_budget_default)
        m = str(mode or "auto").strip().lower()
        if m == "fast":
            b = min(b, 700)
        elif m in ("thorough", "thinking"):
            b = min(max(b, 1400), self._pack_budget_max)
        else:
            b = min(b, self._pack_budget_default)
        return max(self._pack_budget_min, min(b, self._pack_budget_max))

    # ------------------------------------------------------------------
    # Core Memory API consumed by AgentLoop
    # ------------------------------------------------------------------

    def add_event(
        self,
        thread: str,
        etype: str,
        text: str,
        metadata: dict[str, Any] | None = None,
        blob_id: str | None = None,
    ) -> int:
        self._require_started()

        thread_id = str(thread or "default").strip() or "default"
        payload = str(text or "")
        if len(payload) > 120_000:
            payload = payload[:120_000] + "\n... (truncated)"

        role = self._event_role(etype)
        out_id = 0

        if self._legacy is not None:
            try:
                out_id = int(self._legacy.add_event(thread_id, etype, payload, metadata, blob_id))
            except (RuntimeError, OSError) as e:
                log.warning("Legacy memory add_event failed: %s", e)

        if self._fabric_v2 is not None and payload:
            try:
                source = f"agent.{str(etype or 'event').strip().lower()}"
                episode = self._fabric_v2.ingest_episode(
                    thread_id=thread_id,
                    role=role,
                    content=payload,
                    source=source,
                    also_extract_profile=(role == "user"),
                )
                episode_id = int((episode or {}).get("id") or 0)
                if out_id <= 0:
                    out_id = episode_id
                self.auto_promote_event_memory(
                    thread_id,
                    etype,
                    payload,
                    source_episode_id=episode_id or None,
                )
            except (RuntimeError, OSError) as e:
                log.warning("Memory Fabric v2 add_event failed: %s", e)

        return int(out_id)

    def auto_promote_event_memory(
        self,
        thread_id: str,
        etype: str,
        text: str,
        *,
        source_episode_id: int | None = None,
        ts_ms: int | None = None,
    ) -> dict[str, Any]:
        self._require_started()
        if self._fabric_v2 is None:
            return {"promoted": 0, "duplicates": 0, "reason": "fabric_v2_unavailable"}
        if self._event_role(etype) != "user":
            return {"promoted": 0, "duplicates": 0, "reason": "role_not_user"}

        payload = str(text or "").strip()
        if not payload:
            return {"promoted": 0, "duplicates": 0, "reason": "empty"}

        try:
            from thomas.memory.curator import extract_episode_facts
        except Exception as e:
            log.debug("Runtime fact promotion helper unavailable: %s", e)
            return {"promoted": 0, "duplicates": 0, "reason": "extractor_unavailable"}

        ts = int(ts_ms or time.time() * 1000)
        promoted = 0
        duplicates = 0
        for subject, predicate, obj, confidence in extract_episode_facts(payload):
            normalized_subject = str(subject or "").strip().lower()
            normalized_predicate = str(predicate or "").strip().lower()
            normalized_obj = str(obj or "").strip()
            if normalized_subject not in _GLOBAL_EPISODE_FACT_SUBJECTS:
                continue
            if not normalized_predicate or not normalized_obj:
                continue
            existing = self._fabric_v2.db.execute(
                """
                SELECT id FROM semantic_facts
                WHERE subject=? AND predicate=? AND obj=? AND thread_id IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (normalized_subject, normalized_predicate, normalized_obj),
            ).fetchone()
            if existing is not None:
                duplicates += 1
                continue
            self._fabric_v2.upsert_fact(
                thread_id=None,
                subject=normalized_subject,
                predicate=normalized_predicate,
                obj=normalized_obj,
                confidence=float(max(0.0, min(1.0, confidence))),
                provenance_episode_id=int(source_episode_id) if source_episode_id else None,
                ts_ms=ts,
                base_salience=1.15 if normalized_subject == "user" else 1.10,
            )
            promoted += 1

        return {"promoted": promoted, "duplicates": duplicates, "reason": "ok"}

    def retrieve(
        self,
        query: str,
        thread: str | None = None,
        budget: int | None = None,
        mode: str = "auto",
    ) -> _MemoryText:
        self._require_started()

        query_text = str(query or "").strip()
        if thread is None:
            thread_id = _GLOBAL_RETRIEVAL_THREAD_ID
        else:
            thread_id = str(thread).strip() or "default"

        if self._fabric_v2 is not None and query_text:
            try:
                budget_tokens = self._budget_for_mode(budget, mode)
                if thread is None:
                    self._fabric_v2.update_thread_settings(
                        thread_id,
                        {
                            "include_thread": False,
                            "include_global": True,
                            "include_profile": True,
                        },
                    )
                pack = self._fabric_v2.retrieve(
                    thread_id=thread_id,
                    query=query_text,
                    budget_tokens=budget_tokens,
                )
                text = str(getattr(pack, "pack_text", "") or "").strip()
                if text:
                    return _MemoryText(text=text)
            except (RuntimeError, OSError) as e:
                log.warning("Memory Fabric v2 retrieval failed: %s", e)

        if self._legacy is not None:
            try:
                return self._legacy.retrieve(query=query_text, thread=thread, budget=budget, mode=mode)
            except (RuntimeError, OSError) as e:
                log.warning("Legacy memory retrieval failed: %s", e)

        return _MemoryText(text="")

    def ingest_pending(self) -> dict[str, Any]:
        self._require_started()
        if self._legacy is not None:
            try:
                return dict(self._legacy.ingest_pending())
            except (RuntimeError, OSError) as e:
                log.warning("Legacy memory ingestion failed: %s", e)
        return {"indexed": 0}

    def run_curator(self, *, force: bool = False) -> dict[str, Any]:
        """Run one curator pass (best effort)."""
        self._require_started()
        if self._curator is None:
            return {"ran": False, "reason": "curator_unavailable"}
        try:
            out = dict(self._curator.run(force=bool(force)))
            self._curator_last_result = out
            return out
        except (RuntimeError, OSError) as e:
            log.warning("Memory curator run failed: %s", e)
            return {"ran": False, "reason": f"error:{type(e).__name__}"}

    def curator_stats(self) -> dict[str, Any]:
        """Curator status and checkpoint data."""
        self._require_started()
        if self._curator is None:
            return {"enabled": False}
        try:
            out = dict(self._curator.stats())
            if self._curator_last_result:
                out["last_result"] = dict(self._curator_last_result)
            return out
        except (RuntimeError, OSError) as e:
            log.warning("Memory curator stats failed: %s", e)
            return {"enabled": False, "error": str(e)}

    def list_curator_approvals(self, *, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
        return autonomy_services.list_curator_approvals(self, status=status, limit=limit)

    def decide_curator_approval(
        self,
        approval_id: int,
        *,
        approve: bool,
        actor: str = "api",
        reason: str = "",
    ) -> dict[str, Any]:
        return autonomy_services.decide_curator_approval(
            self,
            approval_id,
            approve=approve,
            actor=actor,
            reason=reason,
        )

    def auto_compact_from_token_report(
        self,
        *,
        thread_id: str | None,
        token_report: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return autonomy_services.auto_compact_from_token_report(
            self,
            thread_id=thread_id,
            token_report=token_report,
        )

    # ------------------------------------------------------------------
    # Policy controls (used by integrations like Telegram)
    # ------------------------------------------------------------------

    def set_thread_memory_policy(
        self,
        thread_id: str,
        *,
        enabled: bool | None = None,
        include_thread: bool | None = None,
        include_global: bool | None = None,
        include_profile: bool | None = None,
        pins_only: bool | None = None,
        budget_tokens: int | None = None,
        max_pack_tokens: int | None = None,
        max_results: int | None = None,
        decay_half_life_hours: float | None = None,
        auto_compact_enabled: bool | None = None,
        auto_compact_episode_threshold: int | None = None,
        auto_compact_min_interval_hours: float | None = None,
        auto_optimize_enabled: bool | None = None,
        auto_optimize_waste_threshold: float | None = None,
        auto_optimize_min_interval_hours: float | None = None,
    ) -> dict[str, Any]:
        return autonomy_services.set_thread_memory_policy(
            self,
            thread_id,
            enabled=enabled,
            include_thread=include_thread,
            include_global=include_global,
            include_profile=include_profile,
            pins_only=pins_only,
            budget_tokens=budget_tokens,
            max_pack_tokens=max_pack_tokens,
            max_results=max_results,
            decay_half_life_hours=decay_half_life_hours,
            auto_compact_enabled=auto_compact_enabled,
            auto_compact_episode_threshold=auto_compact_episode_threshold,
            auto_compact_min_interval_hours=auto_compact_min_interval_hours,
            auto_optimize_enabled=auto_optimize_enabled,
            auto_optimize_waste_threshold=auto_optimize_waste_threshold,
            auto_optimize_min_interval_hours=auto_optimize_min_interval_hours,
        )

    def thread_memory_policy(self, thread_id: str) -> dict[str, Any]:
        return autonomy_services.thread_memory_policy(self, thread_id)

    def list_contradictions(self, *, only_open: bool = True, limit: int = 50) -> list[dict[str, Any]]:
        """List memory contradictions from Fabric v2 (if available)."""
        return autonomy_services.list_contradictions(self, only_open=only_open, limit=limit)

    def list_contradictions_review(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        route: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return autonomy_services.list_contradictions_review(
            self,
            status=status,
            severity=severity,
            route=route,
            limit=limit,
        )

    def decide_contradiction_review(
        self,
        cid: int,
        *,
        decision: str,
        actor: str = "api",
        reason: str = "",
    ) -> bool:
        return autonomy_services.decide_contradiction_review(
            self,
            cid,
            decision=decision,
            actor=actor,
            reason=reason,
        )

    def resolve_contradiction(self, cid: int, *, resolved: bool = True) -> bool:
        """Resolve/reopen a contradiction entry by id."""
        return autonomy_services.resolve_contradiction(self, cid, resolved=resolved)

    # ------------------------------------------------------------------
    # Compatibility APIs consumed by UI/REPL
    # ------------------------------------------------------------------

    def pin(self, key: str, text: str) -> None:
        self._require_started()
        k = str(key or "").strip()
        v = str(text or "").strip()
        if not k or not v:
            return

        if self._legacy is not None:
            try:
                self._legacy.pin(k, v)
            except (RuntimeError, OSError) as e:
                log.warning("Legacy memory pin failed: %s", e)

        if self._fabric_v2 is not None:
            try:
                self._fabric_v2.upsert_profile_hints(
                    thread_id=None,
                    hints=[{"key": k, "value": v, "confidence": 1.0}],
                    source_episode_id=None,
                )
                self._fabric_v2.pin_profile_hint(k, pinned=True)
            except (RuntimeError, OSError) as e:
                log.warning("Memory Fabric v2 pin failed: %s", e)

    def unpin(self, key: str) -> None:
        self._require_started()
        k = str(key or "").strip()
        if not k:
            return

        if self._legacy is not None:
            try:
                self._legacy.unpin(k)
            except (RuntimeError, OSError) as e:
                log.warning("Legacy memory unpin failed: %s", e)

        if self._fabric_v2 is not None:
            try:
                self._fabric_v2.pin_profile_hint(k, pinned=False)
            except (RuntimeError, OSError) as e:
                log.warning("Memory Fabric v2 unpin failed: %s", e)

    def list_pins(self) -> list[tuple[str, str, int]]:
        self._require_started()

        if self._legacy is not None:
            try:
                return list(self._legacy.list_pins())
            except (RuntimeError, OSError) as e:
                log.warning("Legacy memory list_pins failed: %s", e)

        if self._fabric_v2 is None:
            return []

        try:
            rows = self._fabric_v2.db.execute(
                "SELECT key, value, last_seen_ts_ms FROM profile_hints "
                "WHERE pinned=1 ORDER BY last_seen_ts_ms DESC LIMIT 200"
            ).fetchall()
            return [
                (
                    str(r["key"]),
                    str(r["value"]),
                    int(int(r["last_seen_ts_ms"]) / 1000),
                )
                for r in rows
            ]
        except (RuntimeError, OSError) as e:
            log.warning("Memory Fabric v2 list_pins fallback failed: %s", e)
            return []

    def stats(self) -> dict[str, Any]:
        self._require_started()

        out: dict[str, Any]
        if self._legacy is not None:
            try:
                out = dict(self._legacy.stats())
            except (RuntimeError, OSError) as e:
                log.warning("Legacy memory stats failed: %s", e)
                out = {
                    "event_count": 0,
                    "has_dense": False,
                    "dense_dim": 0,
                    "root": str(self._config.memory.root_path),
                }
        else:
            out = {
                "event_count": 0,
                "has_dense": False,
                "dense_dim": 0,
                "root": str(self._config.memory.root_path),
            }

        if self._fabric_v2 is not None:
            try:
                health = self._fabric_v2.health()
                out.update(
                    {
                        "v2_enabled": True,
                        "v2_episodes": int(health.get("episodes", 0) or 0),
                        "v2_facts": int(health.get("facts", 0) or 0),
                        "v2_profile_hints": int(health.get("profile_hints", 0) or 0),
                        "v2_contradictions_open": int(health.get("contradictions_open", 0) or 0),
                        "v2_pack_waste_avg_30": float(health.get("pack_waste_avg_30", 0.0) or 0.0),
                    }
                )
            except (RuntimeError, OSError) as e:
                log.warning("Memory Fabric v2 stats failed: %s", e)
                out["v2_enabled"] = False
        else:
            out["v2_enabled"] = False

        if self._curator is not None:
            try:
                out["curator_enabled"] = True
                out["curator"] = self._curator.stats()
                if self._curator_last_result:
                    out["curator_last_run"] = dict(self._curator_last_result)
            except (RuntimeError, OSError) as e:
                log.debug("Curator stats unavailable: %s", e)
        else:
            out["curator_enabled"] = False

        return out

    def recent_traces(self, thread: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        self._require_started()
        out: list[dict[str, Any]] = []
        lim = max(1, int(limit))

        if self._legacy is not None:
            try:
                legacy_traces = self._legacy.recent_traces(thread=thread, limit=lim)
                if isinstance(legacy_traces, list):
                    out.extend(legacy_traces)
            except (RuntimeError, OSError) as e:
                log.warning("Legacy memory recent_traces failed: %s", e)

        if self._fabric_v2 is not None and thread:
            try:
                rows = self._fabric_v2.list_traces(thread, limit=lim)
                for row in rows:
                    out.append(
                        {
                            "thread": thread,
                            "mode": "v2",
                            "query": str(row.get("query", "")),
                            "ts_utc": int(int(row.get("ts_ms", 0)) / 1000),
                            "trace": {
                                "latency_ms": int(row.get("latency_ms", 0) or 0),
                            },
                        }
                    )
            except (RuntimeError, OSError) as e:
                log.warning("Memory Fabric v2 recent_traces failed: %s", e)

        return out[:lim]

    def diagnostics(self, thread: str | None = None, trace_limit: int = 8) -> dict[str, Any]:
        self._require_started()

        pins = self.list_pins()
        payload: dict[str, Any] = {
            "stats": self.stats(),
            "pins": [{"key": k, "text": t, "created_ts_utc": int(ts)} for k, t, ts in pins],
            "traces": self.recent_traces(thread=thread, limit=trace_limit),
        }

        if self._fabric_v2 is not None:
            try:
                payload["v2_health"] = self._fabric_v2.health()
                if thread:
                    payload["v2_thread_settings"] = self.thread_memory_policy(thread)
            except (RuntimeError, OSError) as e:
                log.warning("Memory Fabric v2 diagnostics failed: %s", e)

        if self._curator is not None:
            try:
                payload["curator"] = self.curator_stats()
            except (RuntimeError, OSError) as e:
                log.warning("Curator diagnostics failed: %s", e)

        return payload

    def close(self) -> None:
        if not self._started:
            return

        if self._legacy is not None:
            try:
                self._legacy.close()
            except (RuntimeError, OSError) as e:
                log.debug("Legacy memory close failed: %s", e)

        if self._fabric_v2 is not None:
            try:
                db = getattr(self._fabric_v2, "db", None)
                close_fn = getattr(db, "close", None)
                if callable(close_fn):
                    close_fn()
            except (RuntimeError, OSError) as e:
                log.debug("Memory Fabric v2 close failed: %s", e)

        self._curator = None
        self._started = False
