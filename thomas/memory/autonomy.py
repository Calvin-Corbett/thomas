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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from thomas.core.config import AppConfig

log = logging.getLogger(__name__)


@dataclass
class _MemoryText:
    text: str


class AutonomyMemoryEngine:
    """Runtime memory facade with v2-first retrieval policy."""

    def __init__(
        self,
        config: AppConfig,
        *,
        enable_legacy: bool = True,
        enable_v2: bool = True,
    ) -> None:
        self._config = config
        self._enable_legacy = bool(enable_legacy)
        self._enable_v2 = bool(enable_v2)
        self._started = False

        self._legacy: Optional[Any] = None
        self._fabric_v2: Optional[Any] = None
        self._curator: Optional[Any] = None
        self._curator_last_result: Dict[str, Any] = {}

        self._curator_enabled = str(
            os.environ.get("THOMAS_MEMORY_CURATOR_ENABLED", "1")
        ).strip().lower() in ("1", "true", "yes", "on")
        try:
            self._curator_min_interval_s = max(
                0, int(os.environ.get("THOMAS_MEMORY_CURATOR_MIN_INTERVAL_SECONDS", "180") or 180)
            )
        except Exception:
            self._curator_min_interval_s = 180
        try:
            self._curator_max_episode_scan = max(
                10, int(os.environ.get("THOMAS_MEMORY_CURATOR_MAX_EPISODE_SCAN", "120") or 120)
            )
        except Exception:
            self._curator_max_episode_scan = 120
        try:
            self._curator_max_library_scan = max(
                10, int(os.environ.get("THOMAS_MEMORY_CURATOR_MAX_LIBRARY_SCAN", "40") or 40)
            )
        except Exception:
            self._curator_max_library_scan = 40
        try:
            self._curator_max_promotions = max(
                10, int(os.environ.get("THOMAS_MEMORY_CURATOR_MAX_PROMOTIONS_PER_RUN", "120") or 120)
            )
        except Exception:
            self._curator_max_promotions = 120

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
            except Exception as e:
                log.warning("Legacy memory backend unavailable: %s", e)

        if self._enable_v2:
            try:
                from thomas.memory.v2 import MemoryFabricV2

                root_path = str(self._config.memory.root_path / ".thomas")
                self._fabric_v2 = MemoryFabricV2(root_path=root_path)
                v2_ok = True
                log.info("Memory Fabric v2 backend started at %s", root_path)
            except Exception as e:
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
            except Exception as e:
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

    def _budget_for_mode(self, budget: Optional[int], mode: str) -> int:
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
        metadata: Optional[Dict[str, Any]] = None,
        blob_id: Optional[str] = None,
    ) -> int:
        self._require_started()

        thread_id = str(thread or "default").strip() or "default"
        payload = str(text or "")
        if len(payload) > 120_000:
            payload = payload[:120_000] + "\n... (truncated)"

        out_id = 0

        if self._legacy is not None:
            try:
                out_id = int(self._legacy.add_event(thread_id, etype, payload, metadata, blob_id))
            except Exception as e:
                log.warning("Legacy memory add_event failed: %s", e)

        if self._fabric_v2 is not None and payload:
            try:
                source = f"agent.{str(etype or 'event').strip().lower()}"
                v2_id = self._fabric_v2.ingest_episode(
                    thread_id=thread_id,
                    role=self._event_role(etype),
                    content=payload,
                    source=source,
                    also_extract_profile=True,
                )
                if out_id <= 0:
                    out_id = int(v2_id)
            except Exception as e:
                log.warning("Memory Fabric v2 add_event failed: %s", e)

        return int(out_id)

    def retrieve(
        self,
        query: str,
        thread: Optional[str] = None,
        budget: Optional[int] = None,
        mode: str = "auto",
    ) -> _MemoryText:
        self._require_started()

        query_text = str(query or "").strip()
        thread_id = str(thread or "default").strip() or "default"

        if self._fabric_v2 is not None and query_text:
            try:
                budget_tokens = self._budget_for_mode(budget, mode)
                pack = self._fabric_v2.retrieve(
                    thread_id=thread_id,
                    query=query_text,
                    budget_tokens=budget_tokens,
                )
                text = str(getattr(pack, "pack_text", "") or "").strip()
                if text:
                    return _MemoryText(text=text)
            except Exception as e:
                log.warning("Memory Fabric v2 retrieval failed: %s", e)

        if self._legacy is not None:
            try:
                return self._legacy.retrieve(query=query_text, thread=thread, budget=budget, mode=mode)
            except Exception as e:
                log.warning("Legacy memory retrieval failed: %s", e)

        return _MemoryText(text="")

    def ingest_pending(self) -> Dict[str, Any]:
        self._require_started()
        if self._legacy is not None:
            try:
                return dict(self._legacy.ingest_pending())
            except Exception as e:
                log.warning("Legacy memory ingestion failed: %s", e)
        return {"indexed": 0}

    def run_curator(self, *, force: bool = False) -> Dict[str, Any]:
        """Run one curator pass (best effort)."""
        self._require_started()
        if self._curator is None:
            return {"ran": False, "reason": "curator_unavailable"}
        try:
            out = dict(self._curator.run(force=bool(force)))
            self._curator_last_result = out
            return out
        except Exception as e:
            log.warning("Memory curator run failed: %s", e)
            return {"ran": False, "reason": f"error:{type(e).__name__}"}

    def curator_stats(self) -> Dict[str, Any]:
        """Curator status and checkpoint data."""
        self._require_started()
        if self._curator is None:
            return {"enabled": False}
        try:
            out = dict(self._curator.stats())
            if self._curator_last_result:
                out["last_result"] = dict(self._curator_last_result)
            return out
        except Exception as e:
            log.warning("Memory curator stats failed: %s", e)
            return {"enabled": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Policy controls (used by integrations like Telegram)
    # ------------------------------------------------------------------

    def set_thread_memory_policy(
        self,
        thread_id: str,
        *,
        enabled: Optional[bool] = None,
        include_global: Optional[bool] = None,
        include_profile: Optional[bool] = None,
        pins_only: Optional[bool] = None,
        max_pack_tokens: Optional[int] = None,
        max_results: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._require_started()
        if self._fabric_v2 is None:
            return {}

        tid = str(thread_id or "").strip()
        if not tid:
            raise ValueError("thread_id is required")

        patch: Dict[str, Any] = {}
        if enabled is not None:
            patch["enabled"] = bool(enabled)
        if include_global is not None:
            patch["include_global"] = bool(include_global)
        if include_profile is not None:
            patch["include_profile"] = bool(include_profile)
        if pins_only is not None:
            patch["pins_only"] = bool(pins_only)
        if max_pack_tokens is not None:
            patch["max_pack_tokens"] = int(max_pack_tokens)
        if max_results is not None:
            patch["max_results"] = int(max_results)

        settings = (
            self._fabric_v2.update_thread_settings(tid, patch)
            if patch
            else self._fabric_v2.get_thread_settings(tid)
        )
        return dict(getattr(settings, "__dict__", {}))

    def thread_memory_policy(self, thread_id: str) -> Dict[str, Any]:
        self._require_started()
        if self._fabric_v2 is None:
            return {}
        tid = str(thread_id or "").strip()
        if not tid:
            raise ValueError("thread_id is required")
        settings = self._fabric_v2.get_thread_settings(tid)
        return dict(getattr(settings, "__dict__", {}))

    def list_contradictions(self, *, only_open: bool = True, limit: int = 50) -> List[Dict[str, Any]]:
        """List memory contradictions from Fabric v2 (if available)."""
        self._require_started()
        if self._fabric_v2 is None:
            return []
        try:
            lim = max(1, min(500, int(limit)))
        except Exception:
            lim = 50
        try:
            return list(self._fabric_v2.list_contradictions(only_open=bool(only_open), limit=lim))
        except Exception as e:
            log.warning("Memory Fabric v2 list_contradictions failed: %s", e)
            return []

    def resolve_contradiction(self, cid: int, *, resolved: bool = True) -> bool:
        """Resolve/reopen a contradiction entry by id."""
        self._require_started()
        if self._fabric_v2 is None:
            return False
        try:
            cid_i = int(cid)
        except Exception:
            return False
        if cid_i <= 0:
            return False
        try:
            self._fabric_v2.resolve_contradiction(cid_i, resolved=bool(resolved))
            return True
        except Exception as e:
            log.warning("Memory Fabric v2 resolve_contradiction failed: %s", e)
            return False

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
            except Exception as e:
                log.warning("Legacy memory pin failed: %s", e)

        if self._fabric_v2 is not None:
            try:
                self._fabric_v2.upsert_profile_hints(
                    thread_id=None,
                    hints=[{"key": k, "value": v, "confidence": 1.0}],
                    source_episode_id=None,
                )
                self._fabric_v2.pin_profile_hint(k, pinned=True)
            except Exception as e:
                log.warning("Memory Fabric v2 pin failed: %s", e)

    def unpin(self, key: str) -> None:
        self._require_started()
        k = str(key or "").strip()
        if not k:
            return

        if self._legacy is not None:
            try:
                self._legacy.unpin(k)
            except Exception as e:
                log.warning("Legacy memory unpin failed: %s", e)

        if self._fabric_v2 is not None:
            try:
                self._fabric_v2.pin_profile_hint(k, pinned=False)
            except Exception as e:
                log.warning("Memory Fabric v2 unpin failed: %s", e)

    def list_pins(self) -> List[Tuple[str, str, int]]:
        self._require_started()

        if self._legacy is not None:
            try:
                return list(self._legacy.list_pins())
            except Exception as e:
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
        except Exception as e:
            log.warning("Memory Fabric v2 list_pins fallback failed: %s", e)
            return []

    def stats(self) -> Dict[str, Any]:
        self._require_started()

        out: Dict[str, Any]
        if self._legacy is not None:
            try:
                out = dict(self._legacy.stats())
            except Exception as e:
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
                        "v2_contradictions_open": int(
                            health.get("contradictions_open", 0) or 0
                        ),
                        "v2_pack_waste_avg_30": float(
                            health.get("pack_waste_avg_30", 0.0) or 0.0
                        ),
                    }
                )
            except Exception as e:
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
            except Exception as e:
                log.debug("Curator stats unavailable: %s", e)
        else:
            out["curator_enabled"] = False

        return out

    def recent_traces(
        self, thread: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        self._require_started()
        out: List[Dict[str, Any]] = []
        lim = max(1, int(limit))

        if self._legacy is not None:
            try:
                legacy_traces = self._legacy.recent_traces(thread=thread, limit=lim)
                if isinstance(legacy_traces, list):
                    out.extend(legacy_traces)
            except Exception as e:
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
            except Exception as e:
                log.warning("Memory Fabric v2 recent_traces failed: %s", e)

        return out[:lim]

    def diagnostics(
        self, thread: Optional[str] = None, trace_limit: int = 8
    ) -> Dict[str, Any]:
        self._require_started()

        pins = self.list_pins()
        payload: Dict[str, Any] = {
            "stats": self.stats(),
            "pins": [
                {"key": k, "text": t, "created_ts_utc": int(ts)}
                for k, t, ts in pins
            ],
            "traces": self.recent_traces(thread=thread, limit=trace_limit),
        }

        if self._fabric_v2 is not None:
            try:
                payload["v2_health"] = self._fabric_v2.health()
                if thread:
                    payload["v2_thread_settings"] = self.thread_memory_policy(thread)
            except Exception as e:
                log.warning("Memory Fabric v2 diagnostics failed: %s", e)

        if self._curator is not None:
            try:
                payload["curator"] = self.curator_stats()
            except Exception as e:
                log.warning("Curator diagnostics failed: %s", e)

        return payload

    def close(self) -> None:
        if not self._started:
            return

        if self._legacy is not None:
            try:
                self._legacy.close()
            except Exception as e:
                log.debug("Legacy memory close failed: %s", e)

        if self._fabric_v2 is not None:
            try:
                db = getattr(self._fabric_v2, "db", None)
                close_fn = getattr(db, "close", None)
                if callable(close_fn):
                    close_fn()
            except Exception as e:
                log.debug("Memory Fabric v2 close failed: %s", e)

        self._curator = None
        self._started = False
