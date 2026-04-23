"""Service helpers for the autonomy memory runtime."""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


def list_curator_approvals(engine: Any, *, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
    engine._require_started()
    if engine._curator is None:
        return []
    list_fn = getattr(engine._curator, "list_approval_queue", None)
    if not callable(list_fn):
        return []
    try:
        return list(list_fn(status=str(status or "").strip(), limit=int(limit)))
    except (RuntimeError, OSError) as exc:
        log.warning("Memory curator approval queue listing failed: %s", exc)
        return []
def decide_curator_approval(engine: Any, approval_id: int, *, approve: bool, actor: str = "api", reason: str = "") -> dict[str, Any]:
    engine._require_started()
    if engine._curator is None:
        return {"ok": False, "error": "curator_unavailable"}
    decide_fn = getattr(engine._curator, "decide_approval", None)
    if not callable(decide_fn):
        return {"ok": False, "error": "curator_approval_api_unavailable"}
    try:
        return dict(
            decide_fn(
                int(approval_id),
                approve=bool(approve),
                actor=str(actor or "api"),
                reason=str(reason or ""),
            )
        )
    except KeyError:
        return {"ok": False, "error": "not_found"}
    except (RuntimeError, OSError) as exc:
        log.warning("Memory curator approval decision failed: %s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
def auto_compact_from_token_report(engine: Any, *, thread_id: str | None, token_report: dict[str, Any] | None) -> dict[str, Any]:
    engine._require_started()
    tid = str(thread_id or "").strip()
    if not tid:
        return {"checked": False, "triggered": False, "reason": "missing_thread_id"}
    if engine._fabric_v2 is None:
        return {"checked": False, "triggered": False, "reason": "fabric_v2_unavailable"}
    if not engine._token_report_compact_enabled:
        return {"checked": False, "triggered": False, "reason": "disabled"}
    if not isinstance(token_report, dict):
        return {"checked": False, "triggered": False, "reason": "token_report_missing"}

    reasons: list[str] = []
    prompt_tokens = int(token_report.get("prompt_tokens", 0) or 0)
    total_tokens = int(token_report.get("total_tokens", 0) or 0)
    memory_share = float(token_report.get("memory_share_of_context", 0.0) or 0.0)

    if prompt_tokens >= int(engine._token_report_prompt_threshold):
        reasons.append(f"prompt_tokens>={engine._token_report_prompt_threshold}")
    if total_tokens >= int(engine._token_report_total_threshold):
        reasons.append(f"total_tokens>={engine._token_report_total_threshold}")
    if memory_share >= float(engine._token_report_memory_share_threshold):
        reasons.append(f"memory_share>={engine._token_report_memory_share_threshold:.2f}")

    budget = token_report.get("run_budget")
    if isinstance(budget, dict):
        try:
            warn_cap = int(budget.get("iteration_prompt_warn_cap", 0) or 0)
            max_spend = int(budget.get("max_iteration_prompt_spend", 0) or 0)
        except (ValueError, TypeError):
            warn_cap = 0
            max_spend = 0
        if warn_cap > 0:
            pressure = float(max_spend) / float(max(1, warn_cap))
            if pressure >= float(engine._token_report_budget_pressure_threshold):
                reasons.append(f"iteration_budget_pressure>={engine._token_report_budget_pressure_threshold:.2f}")

    if not reasons:
        return {"checked": True, "triggered": False, "reasons": []}

    now_ms = int(time.time() * 1000)
    last_ms = int(engine._token_report_last_compact_ms.get(tid, 0) or 0)
    min_interval_ms = max(0, int(engine._token_report_min_interval_s)) * 1000
    if last_ms > 0 and (now_ms - last_ms) < min_interval_ms:
        return {
            "checked": True,
            "triggered": False,
            "reasons": reasons,
            "reason": "cooldown",
            "cooldown_remaining_ms": int(min_interval_ms - (now_ms - last_ms)),
        }

    try:
        compact_result = engine._fabric_v2.compact(thread_id=tid)
        engine._token_report_last_compact_ms[tid] = now_ms
        return {
            "checked": True,
            "triggered": True,
            "reasons": reasons,
            "compact": compact_result if isinstance(compact_result, dict) else {},
            "triggered_at_ms": now_ms,
        }
    except (RuntimeError, OSError) as exc:
        log.warning("Token-report-driven compaction failed for thread %s: %s", tid, exc)
        return {
            "checked": True,
            "triggered": False,
            "reasons": reasons,
            "reason": f"error:{type(exc).__name__}",
        }
def set_thread_memory_policy(
    engine: Any, thread_id: str, *, enabled: bool | None = None, include_thread: bool | None = None,
    include_global: bool | None = None, include_profile: bool | None = None, pins_only: bool | None = None,
    budget_tokens: int | None = None, max_pack_tokens: int | None = None, max_results: int | None = None,
    decay_half_life_hours: float | None = None, auto_compact_enabled: bool | None = None,
    auto_compact_episode_threshold: int | None = None, auto_compact_min_interval_hours: float | None = None,
    auto_optimize_enabled: bool | None = None, auto_optimize_waste_threshold: float | None = None,
    auto_optimize_min_interval_hours: float | None = None,
) -> dict[str, Any]:
    engine._require_started()
    if engine._fabric_v2 is None:
        return {}

    tid = str(thread_id or "").strip()
    if not tid:
        raise ValueError("thread_id is required")

    patch: dict[str, Any] = {}
    if enabled is not None:
        patch["enabled"] = bool(enabled)
    if include_thread is not None:
        patch["include_thread"] = bool(include_thread)
    if include_global is not None:
        patch["include_global"] = bool(include_global)
    if include_profile is not None:
        patch["include_profile"] = bool(include_profile)
    if pins_only is not None:
        patch["pins_only"] = bool(pins_only)
    if max_pack_tokens is not None:
        patch["max_pack_tokens"] = int(max_pack_tokens)
    elif budget_tokens is not None:
        patch["max_pack_tokens"] = int(budget_tokens)
    if max_results is not None:
        patch["max_results"] = int(max_results)
    if decay_half_life_hours is not None:
        patch["decay_half_life_hours"] = float(decay_half_life_hours)
    if auto_compact_enabled is not None:
        patch["auto_compact_enabled"] = bool(auto_compact_enabled)
    if auto_compact_episode_threshold is not None:
        patch["auto_compact_episode_threshold"] = int(auto_compact_episode_threshold)
    if auto_compact_min_interval_hours is not None:
        patch["auto_compact_min_interval_hours"] = float(auto_compact_min_interval_hours)
    if auto_optimize_enabled is not None:
        patch["auto_optimize_enabled"] = bool(auto_optimize_enabled)
    if auto_optimize_waste_threshold is not None:
        patch["auto_optimize_waste_threshold"] = float(auto_optimize_waste_threshold)
    if auto_optimize_min_interval_hours is not None:
        patch["auto_optimize_min_interval_hours"] = float(auto_optimize_min_interval_hours)

    settings = engine._fabric_v2.update_thread_settings(tid, patch) if patch else engine._fabric_v2.get_thread_settings(tid)
    return dict(getattr(settings, "__dict__", {}))


def thread_memory_policy(engine: Any, thread_id: str) -> dict[str, Any]:
    engine._require_started()
    if engine._fabric_v2 is None:
        return {}
    tid = str(thread_id or "").strip()
    if not tid:
        raise ValueError("thread_id is required")
    settings = engine._fabric_v2.get_thread_settings(tid)
    return dict(getattr(settings, "__dict__", {}))


def list_contradictions(engine: Any, *, only_open: bool = True, limit: int = 50) -> list[dict[str, Any]]:
    engine._require_started()
    if engine._fabric_v2 is None:
        return []
    try:
        lim = max(1, min(500, int(limit)))
    except (ValueError, TypeError):
        lim = 50
    try:
        return list(engine._fabric_v2.list_contradictions(only_open=bool(only_open), limit=lim))
    except (RuntimeError, OSError) as exc:
        log.warning("Memory Fabric v2 list_contradictions failed: %s", exc)
        return []
def list_contradictions_review(
    engine: Any, *, status: str | None = None, severity: str | None = None, route: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    engine._require_started()
    if engine._fabric_v2 is None:
        return []
    list_fn = getattr(engine._fabric_v2, "list_contradictions_for_review", None)
    if not callable(list_fn):
        return list_contradictions(engine, only_open=True, limit=limit)
    try:
        lim = max(1, min(500, int(limit)))
    except (ValueError, TypeError):
        lim = 50
    try:
        return list(
            list_fn(
                status=str(status or "").strip() or None,
                severity=str(severity or "").strip() or None,
                route=str(route or "").strip() or None,
                limit=lim,
            )
        )
    except (RuntimeError, OSError) as exc:
        log.warning("Memory Fabric v2 contradiction review listing failed: %s", exc)
        return []
def decide_contradiction_review(engine: Any, cid: int, *, decision: str, actor: str = "api", reason: str = "") -> bool:
    engine._require_started()
    if engine._fabric_v2 is None:
        return False
    review_fn = getattr(engine._fabric_v2, "review_contradiction", None)
    if not callable(review_fn):
        return False
    try:
        cid_i = int(cid)
    except (ValueError, TypeError):
        return False
    if cid_i <= 0:
        return False
    try:
        return bool(
            review_fn(
                cid_i,
                decision=str(decision or "").strip().lower(),
                actor=str(actor or "api"),
                reason=str(reason or ""),
            )
        )
    except (RuntimeError, OSError) as exc:
        log.warning("Memory Fabric v2 contradiction review decision failed: %s", exc)
        return False


def resolve_contradiction(engine: Any, cid: int, *, resolved: bool = True) -> bool:
    engine._require_started()
    if engine._fabric_v2 is None:
        return False
    try:
        cid_i = int(cid)
    except (ValueError, TypeError):
        return False
    if cid_i <= 0:
        return False
    try:
        review_fn = getattr(engine._fabric_v2, "review_contradiction", None)
        if callable(review_fn):
            decision = "approve" if bool(resolved) else "reopen"
            return bool(
                review_fn(
                    cid_i,
                    decision=decision,
                    actor="system.resolve_api",
                    reason="legacy_resolve_route",
                )
            )
        engine._fabric_v2.resolve_contradiction(cid_i, resolved=bool(resolved))
        return True
    except (RuntimeError, OSError) as exc:
        log.warning("Memory Fabric v2 resolve_contradiction failed: %s", exc)
        return False
