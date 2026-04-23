"""UI workflow engine for design consistency, effects curation, and asset sourcing.

This engine is deterministic and low-risk:
- audits UI consistency (tokens, motion hygiene, focus states)
- publishes a curated effects registry with trusted references
- searches online asset providers with graceful fallback behavior
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.ui_effects_catalog import EFFECTS_CATALOG
from thomas.core.ui_review import review_ui_edits as run_ui_review

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path.home() / ".thomas"
DEFAULT_UI_ROOT = ROOT / "thomas" / "server" / "web"

_DEFAULT_IDLE_THRESHOLD_S = 5 * 60.0
_DEFAULT_POLL_INTERVAL_S = 60.0
_DEFAULT_CYCLE_INTERVAL_S = 15 * 60.0
_DEFAULT_MAX_CYCLES = 200
_DEFAULT_HTTP_TIMEOUT_S = 8.0

_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGB_COLOR_RE = re.compile(r"\brgba?\([^)]+\)")
_HSL_COLOR_RE = re.compile(r"\bhsla?\([^)]+\)")
_TOKEN_DECL_RE = re.compile(r"--([a-zA-Z0-9_-]+)\s*:")
_TOKEN_REF_RE = re.compile(r"var\(--([a-zA-Z0-9_-]+)")
_Z_INDEX_RE = re.compile(r"\bz-index\s*:\s*(-?\d+)")
_ANIMATION_RE = re.compile(r"\banimation(?:-name)?\s*:")
_TRANSITION_RE = re.compile(r"\btransition(?:-property)?\s*:")


def _env_float(name: str, default: float, *, min_value: float = 0.0, max_value: float = 86_400.0) -> float:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except Exception:
        return float(default)
    return float(max(min_value, min(max_value, value)))


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 10_000) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return int(default)
    try:
        value = int(raw)
    except Exception:
        return int(default)
    return int(max(min_value, min(max_value, value)))


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return bool(default)
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _to_provider_list(raw: Any, *, default: list[str]) -> list[str]:
    values: list[str]
    if raw is None:
        values = list(default)
    elif isinstance(raw, str):
        values = [part.strip().lower() for part in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(part or "").strip().lower() for part in raw]
    else:
        values = list(default)
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


class UIWorkflowEngine:
    """Background engine for UI polish consistency and asset/effects workflows."""

    def __init__(
        self,
        *,
        ui_root: Path | None = None,
        idle_threshold_s: float | None = None,
        poll_interval_s: float | None = None,
        cycle_interval_s: float | None = None,
        max_cycles_per_session: int | None = None,
        notify_fn: Callable[[str], None] | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._ui_root = Path(ui_root or DEFAULT_UI_ROOT)
        self._idle_threshold_s = float(
            _DEFAULT_IDLE_THRESHOLD_S if idle_threshold_s is None else max(0.0, float(idle_threshold_s))
        )
        self._poll_interval_s = float(
            _DEFAULT_POLL_INTERVAL_S if poll_interval_s is None else max(1.0, float(poll_interval_s))
        )
        self._cycle_interval_s = float(
            _DEFAULT_CYCLE_INTERVAL_S if cycle_interval_s is None else max(1.0, float(cycle_interval_s))
        )
        self._max_cycles_per_session = int(
            _DEFAULT_MAX_CYCLES if max_cycles_per_session is None else max(1, int(max_cycles_per_session))
        )
        self._http_timeout_s = _env_float(
            "THOMAS_UI_ENGINE_HTTP_TIMEOUT_S",
            _DEFAULT_HTTP_TIMEOUT_S,
            min_value=1.0,
            max_value=60.0,
        )
        self._default_asset_providers = _to_provider_list(
            os.environ.get("THOMAS_UI_ASSET_PROVIDERS", "openverse,unsplash,pexels"),
            default=["openverse", "unsplash", "pexels"],
        )
        self._notify_fn = notify_fn
        self._log_path = Path(log_path or (STATE_DIR / "ui_workflow_engine.jsonl"))

        self._running = False
        self._thread: threading.Thread | None = None
        self._active_cycle = False
        self._lock = threading.Lock()
        self._last_user_ts = time.monotonic()
        self._last_cycle_ts = 0.0
        self._cycle_count = 0
        self._last_report: dict[str, Any] = {}
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._enabled = _env_bool("THOMAS_UI_WORKFLOW_ENGINE_ENABLED", True)

    def start(self, *, notify_fn: Callable[[str], None] | None = None) -> None:
        if notify_fn is not None:
            self._notify_fn = notify_fn
        if self._running or not self._enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="thomas-ui-workflow")
        self._thread.start()
        log.info("UIWorkflowEngine started (idle threshold %.0fs).", self._idle_threshold_s)

    def stop(self) -> None:
        self._running = False

    def record_user_message(self) -> None:
        self._last_user_ts = time.monotonic()

    def is_idle(self) -> bool:
        return (time.monotonic() - self._last_user_ts) >= self._idle_threshold_s

    def status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            report = dict(self._last_report) if isinstance(self._last_report, dict) else {}
            return {
                "running": bool(self._running),
                "enabled": bool(self._enabled),
                "cycles_completed": int(self._cycle_count),
                "active_cycle": bool(self._active_cycle),
                "last_cycle_at": str(report.get("timestamp") or ""),
                "last_score": int(report.get("score") or 0) if report else None,
                "last_warning_count": int(report.get("warning_count") or 0) if report else 0,
                "last_review_verdict": str((report.get("review") or {}).get("verdict") or "") if report else "",
                "last_error": str(self._last_error or ""),
                "last_error_at": str(self._last_error_at or ""),
            }

    def last_report(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._last_report) if isinstance(self._last_report, dict) else {}

    def list_effects(self, *, category: str = "") -> list[dict[str, Any]]:
        key = str(category or "").strip().lower()
        rows = [dict(item) for item in EFFECTS_CATALOG]
        if key:
            rows = [row for row in rows if str(row.get("category") or "").strip().lower() == key]
        rows.sort(key=lambda row: (str(row.get("category") or ""), str(row.get("name") or "")))
        return rows

    def run_cycle_once(self, *, reason: str = "manual", force: bool = False) -> dict[str, Any]:
        if not force:
            if not self._enabled:
                return {"ok": False, "reason": "engine_disabled"}
            if not self.is_idle():
                return {"ok": False, "reason": "not_idle"}
        with self._lock:
            if self._active_cycle:
                return {"ok": False, "reason": "busy"}
            self._active_cycle = True
            self._last_cycle_ts = time.monotonic()
        try:
            return self._run_cycle_checked(reason=reason)
        finally:
            with self._lock:
                self._active_cycle = False

    def search_assets(
        self,
        query: str,
        *,
        limit: int = 12,
        providers: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        text = str(query or "").strip()
        if len(text) < 2:
            raise ValueError("query must be at least 2 characters")
        max_items = _clamp_int(limit, default=12, minimum=1, maximum=50)
        selected = _to_provider_list(
            list(providers) if providers is not None else None,
            default=list(self._default_asset_providers),
        )
        if not selected:
            selected = ["openverse"]

        per_provider_limit = _clamp_int(max_items, default=max_items, minimum=1, maximum=30)
        assets: list[dict[str, Any]] = []
        provider_status: list[dict[str, Any]] = []

        for provider in selected:
            if provider == "openverse":
                rows, status = self._search_openverse(text, limit=per_provider_limit)
            elif provider == "unsplash":
                rows, status = self._search_unsplash(text, limit=per_provider_limit)
            elif provider == "pexels":
                rows, status = self._search_pexels(text, limit=per_provider_limit)
            else:
                rows = []
                status = {"provider": provider, "ok": False, "skipped": True, "error": "unknown provider"}
            provider_status.append(status)
            assets.extend(rows)

        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in assets:
            key = str(row.get("asset_url") or row.get("source_url") or row.get("id") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(row)
            if len(deduped) >= max_items:
                break

        return {
            "ok": True,
            "query": text,
            "count": len(deduped),
            "assets": deduped,
            "providers": provider_status,
            "timestamp": _now_iso(),
        }

    def review_ui_edits(
        self,
        *,
        intent: str = "",
        changed_paths: Iterable[str] | None = None,
        strict: bool = True,
    ) -> dict[str, Any]:
        review_root = ROOT
        try:
            if self._ui_root.name == "web" and self._ui_root.parent.name == "server":
                candidate = self._ui_root.parents[2]
                if candidate.exists():
                    review_root = candidate
        except Exception:
            review_root = ROOT
        return run_ui_review(
            root=review_root,
            read_text=self._read_text,
            intent=intent,
            changed_paths=changed_paths,
            strict=strict,
            inferred_intent=self._infer_recent_intent(),
        )

    def _loop(self) -> None:
        while self._running:
            time.sleep(self._poll_interval_s)
            try:
                self._tick()
            except Exception as exc:
                log.warning("UIWorkflowEngine tick failed: %s", exc)

    def _tick(self) -> None:
        if not self._enabled:
            return
        if not self.is_idle():
            return
        now = time.monotonic()
        with self._lock:
            if self._active_cycle:
                return
            if self._cycle_count >= self._max_cycles_per_session:
                return
            if (now - self._last_cycle_ts) < self._cycle_interval_s:
                return
            self._active_cycle = True
            self._last_cycle_ts = now
        threading.Thread(
            target=self._run_cycle_threadsafe,
            args=("idle",),
            daemon=True,
            name="thomas-ui-workflow-cycle",
        ).start()

    def _run_cycle_threadsafe(self, reason: str) -> None:
        try:
            self._run_cycle_checked(reason=reason)
        finally:
            with self._lock:
                self._active_cycle = False

    def _run_cycle_checked(self, *, reason: str) -> dict[str, Any]:
        started = time.monotonic()
        try:
            report = self._run_cycle(reason=reason)
            self._clear_last_error()
            return report
        except Exception as exc:  # pragma: no cover - defensive path
            return self._error_report(reason=reason, exc=exc, started=started)

    def _run_cycle(self, *, reason: str) -> dict[str, Any]:
        started = time.monotonic()
        report = self.audit_ui_consistency()
        review = self.review_ui_edits(strict=False)

        with self._lock:
            self._cycle_count += 1
            cycle_id = int(self._cycle_count)

        report.update(
            {
                "ok": True,
                "cycle": cycle_id,
                "reason": str(reason or "manual"),
                "timestamp": _now_iso(),
                "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
                "review": review,
            }
        )
        self._write_cycle_log(report)
        with self._lock:
            self._last_report = dict(report)

        if self._notify_fn is not None:
            try:
                warnings = int(report.get("warning_count") or 0)
                score = int(report.get("score") or 0)
                self._notify_fn(f"[UIWorkflowEngine] cycle {cycle_id}: score={score} warnings={warnings}")
            except Exception:
                pass

        return report

    def _error_report(self, *, reason: str, exc: BaseException, started: float) -> dict[str, Any]:
        with self._lock:
            self._cycle_count += 1
            cycle_id = int(self._cycle_count)
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._last_error_at = _now_iso()

        report = {
            "ok": False,
            "cycle": cycle_id,
            "reason": "engine_error",
            "requested_reason": str(reason or "manual"),
            "error_type": type(exc).__name__,
            "error": f"{type(exc).__name__}: {exc}",
            "timestamp": _now_iso(),
            "elapsed_ms": round((time.monotonic() - started) * 1000.0, 1),
        }
        self._write_cycle_log(report)
        with self._lock:
            self._last_report = dict(report)
        if self._notify_fn is not None:
            try:
                self._notify_fn(f"[UIWorkflowEngine] cycle {cycle_id} failed: {type(exc).__name__}: {exc}")
            except Exception:
                pass
        return report

    def _clear_last_error(self) -> None:
        self._last_error = None
        self._last_error_at = None

    def audit_ui_consistency(self) -> dict[str, Any]:
        files: list[Path] = [
            self._ui_root / "css" / "tokens.css",
            self._ui_root / "css" / "layout.css",
            self._ui_root / "css" / "components.css",
            self._ui_root / "js" / "app.js",
            self._ui_root / "index.html",
            self._ui_root / "mission.html",
            self._ui_root / "settings.html",
            self._ui_root / "companion.html",
        ]

        css_bodies: list[str] = []
        js_bodies: list[str] = []
        html_bodies: list[str] = []
        scanned: list[str] = []

        for path in files:
            if not path.exists() or not path.is_file():
                continue
            text = self._read_text(path)
            scanned.append(str(path.relative_to(ROOT).as_posix()) if path.is_relative_to(ROOT) else str(path))
            suffix = path.suffix.lower()
            if suffix == ".css":
                css_bodies.append(text)
            elif suffix == ".js":
                js_bodies.append(text)
            elif suffix == ".html":
                html_bodies.append(text)

        css_all = "\n".join(css_bodies)
        js_all = "\n".join(js_bodies)
        html_all = "\n".join(html_bodies)
        joined = "\n".join([css_all, js_all, html_all])

        token_defs = set(_TOKEN_DECL_RE.findall(css_all))
        token_refs = set(_TOKEN_REF_RE.findall(css_all))
        unresolved = sorted(ref for ref in token_refs if ref not in token_defs)
        hardcoded_colors = (
            len(_HEX_COLOR_RE.findall(css_all))
            + len(_RGB_COLOR_RE.findall(css_all))
            + len(_HSL_COLOR_RE.findall(css_all))
        )
        animation_count = len(_ANIMATION_RE.findall(css_all)) + css_all.count("@keyframes")
        transition_count = len(_TRANSITION_RE.findall(css_all))
        reduced_motion_mentions = joined.lower().count("prefers-reduced-motion")
        focus_visible_mentions = css_all.count(":focus-visible")
        container_query_count = css_all.count("@container")
        view_transition_mentions = joined.count("startViewTransition") + joined.count("view-transition")
        scroll_timeline_mentions = joined.count("scroll-timeline") + joined.count("animation-timeline")
        landmark_count = (
            html_all.lower().count("<main")
            + html_all.lower().count("<nav")
            + html_all.lower().count("<header")
            + html_all.lower().count("<footer")
            + html_all.lower().count("<section")
        )
        z_values = [int(value) for value in _Z_INDEX_RE.findall(css_all)]
        max_z_index = max(z_values) if z_values else 0

        warnings: list[dict[str, Any]] = []
        if not token_defs:
            warnings.append({"id": "tokens.missing", "severity": "high", "message": "No CSS design tokens detected."})
        if unresolved:
            warnings.append(
                {
                    "id": "tokens.unresolved",
                    "severity": "high",
                    "message": f"Found {len(unresolved)} unresolved token references.",
                    "sample": unresolved[:8],
                }
            )
        if hardcoded_colors > 20:
            warnings.append(
                {
                    "id": "colors.hardcoded",
                    "severity": "medium",
                    "message": f"High hardcoded color usage ({hardcoded_colors}); migrate repeated values into tokens.",
                }
            )
        if animation_count > 0 and reduced_motion_mentions == 0:
            warnings.append(
                {
                    "id": "motion.reduced",
                    "severity": "medium",
                    "message": "Animations detected without reduced-motion fallback.",
                }
            )
        if focus_visible_mentions == 0:
            warnings.append(
                {
                    "id": "a11y.focus_visible",
                    "severity": "medium",
                    "message": "No :focus-visible rules detected in CSS.",
                }
            )
        if max_z_index > 3000:
            warnings.append(
                {
                    "id": "stacking.zindex",
                    "severity": "low",
                    "message": f"Max z-index {max_z_index} is high and can cause layering bugs.",
                }
            )

        score = 100
        score -= min(30, len(unresolved) * 4)
        score -= min(20, hardcoded_colors // 5)
        if animation_count > 0 and reduced_motion_mentions == 0:
            score -= 15
        if focus_visible_mentions == 0:
            score -= 10
        if max_z_index > 3000:
            score -= 5
        if container_query_count == 0:
            score -= 5
        if view_transition_mentions == 0:
            score -= 5
        if scroll_timeline_mentions == 0:
            score -= 5
        score = max(0, min(100, score))

        recommendations = self._build_recommendations(
            unresolved_count=len(unresolved),
            hardcoded_colors=hardcoded_colors,
            animation_count=animation_count,
            reduced_motion_mentions=reduced_motion_mentions,
            view_transition_mentions=view_transition_mentions,
            scroll_timeline_mentions=scroll_timeline_mentions,
            container_query_count=container_query_count,
        )

        return {
            "score": score,
            "warning_count": len(warnings),
            "warnings": warnings,
            "files_scanned": scanned,
            "token_count": len(token_defs),
            "token_reference_count": len(token_refs),
            "unresolved_token_count": len(unresolved),
            "hardcoded_color_count": hardcoded_colors,
            "animation_count": animation_count,
            "transition_count": transition_count,
            "reduced_motion_mentions": reduced_motion_mentions,
            "focus_visible_mentions": focus_visible_mentions,
            "container_query_count": container_query_count,
            "view_transition_mentions": view_transition_mentions,
            "scroll_timeline_mentions": scroll_timeline_mentions,
            "landmark_count": landmark_count,
            "max_z_index": max_z_index,
            "recommendations": recommendations,
            "effects": self.list_effects(),
        }

    def _build_recommendations(self, **metrics: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if int(metrics.get("unresolved_count") or 0) > 0:
            out.append(
                {
                    "id": "fix-unresolved-tokens",
                    "priority": "high",
                    "title": "Resolve all missing design tokens",
                    "impact": "Eliminates inconsistent colors/spacing and fallback glitches.",
                }
            )
        if int(metrics.get("hardcoded_colors") or 0) > 20:
            out.append(
                {
                    "id": "tokenize-colors",
                    "priority": "high",
                    "title": "Replace hardcoded colors with token variables",
                    "impact": "Makes theme-level polish changes predictable and global.",
                }
            )
        if int(metrics.get("animation_count") or 0) > 0 and int(metrics.get("reduced_motion_mentions") or 0) <= 0:
            out.append(
                {
                    "id": "add-reduced-motion-fallback",
                    "priority": "high",
                    "title": "Add prefers-reduced-motion guardrails",
                    "impact": "Improves accessibility and reduces motion sickness risk.",
                    "effect_id": "web-rendering-performance",
                }
            )
        if int(metrics.get("view_transition_mentions") or 0) <= 0:
            out.append(
                {
                    "id": "adopt-view-transitions",
                    "priority": "medium",
                    "title": "Adopt native View Transitions for route/panel swaps",
                    "impact": "Raises perceived polish with minimal runtime complexity.",
                    "effect_id": "view-transitions-native",
                }
            )
        if int(metrics.get("scroll_timeline_mentions") or 0) <= 0:
            out.append(
                {
                    "id": "add-scroll-timeline-effects",
                    "priority": "medium",
                    "title": "Use scroll-timeline for progressive reveal sections",
                    "impact": "Adds premium storytelling without heavy JS animation loops.",
                    "effect_id": "scroll-driven-animations",
                }
            )
        if int(metrics.get("container_query_count") or 0) <= 0:
            out.append(
                {
                    "id": "adopt-container-queries",
                    "priority": "medium",
                    "title": "Use container queries for component-level responsiveness",
                    "impact": "Keeps cards and tool panels consistent across studio modes.",
                    "effect_id": "container-query-layouts",
                }
            )
        return out

    def _infer_recent_intent(self) -> str:
        try:
            from thomas.core.persistence import get_persistence

            turns = list(get_persistence().recent_turns(n=8) or [])
            for turn in reversed(turns):
                text = str(getattr(turn, "user_msg", "") or "").strip()
                if text:
                    return text
        except Exception:
            return ""
        return ""

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            try:
                return path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return ""

    def _search_openverse(self, query: str, *, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        encoded = urllib.parse.urlencode({"q": query, "page_size": limit})
        url = f"https://api.openverse.org/v1/images/?{encoded}"
        payload, error = self._fetch_json(url, headers={})
        if error:
            return [], {"provider": "openverse", "ok": False, "error": error}
        results = payload.get("results")
        if not isinstance(results, list):
            return [], {"provider": "openverse", "ok": False, "error": "invalid response shape"}
        rows: list[dict[str, Any]] = []
        for item in results[:limit]:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "provider": "openverse",
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("title") or item.get("id") or "Openverse image"),
                    "thumbnail_url": str(item.get("thumbnail") or item.get("url") or ""),
                    "asset_url": str(item.get("url") or ""),
                    "source_url": str(
                        item.get("foreign_landing_url") or item.get("detail_url") or item.get("url") or ""
                    ),
                    "creator": str(item.get("creator") or ""),
                    "license": str(item.get("license") or ""),
                }
            )
        return rows, {"provider": "openverse", "ok": True, "count": len(rows)}

    def _search_unsplash(self, query: str, *, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        key = str(os.environ.get("THOMAS_UNSPLASH_ACCESS_KEY", "") or "").strip()
        if not key:
            return [], {
                "provider": "unsplash",
                "ok": False,
                "skipped": True,
                "error": "missing THOMAS_UNSPLASH_ACCESS_KEY",
            }
        encoded = urllib.parse.urlencode({"query": query, "per_page": limit, "page": 1})
        url = f"https://api.unsplash.com/search/photos?{encoded}"
        payload, error = self._fetch_json(url, headers={"Authorization": f"Client-ID {key}"})
        if error:
            return [], {"provider": "unsplash", "ok": False, "error": error}
        results = payload.get("results")
        if not isinstance(results, list):
            return [], {"provider": "unsplash", "ok": False, "error": "invalid response shape"}
        rows: list[dict[str, Any]] = []
        for item in results[:limit]:
            if not isinstance(item, dict):
                continue
            urls = item.get("urls") if isinstance(item.get("urls"), dict) else {}
            links = item.get("links") if isinstance(item.get("links"), dict) else {}
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            rows.append(
                {
                    "provider": "unsplash",
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("description") or item.get("alt_description") or "Unsplash image"),
                    "thumbnail_url": str(urls.get("small") or urls.get("thumb") or ""),
                    "asset_url": str(urls.get("regular") or urls.get("full") or ""),
                    "source_url": str(links.get("html") or ""),
                    "creator": str(user.get("name") or ""),
                    "license": "Unsplash License",
                }
            )
        return rows, {"provider": "unsplash", "ok": True, "count": len(rows)}

    def _search_pexels(self, query: str, *, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        key = str(os.environ.get("THOMAS_PEXELS_API_KEY", "") or "").strip()
        if not key:
            return [], {"provider": "pexels", "ok": False, "skipped": True, "error": "missing THOMAS_PEXELS_API_KEY"}
        encoded = urllib.parse.urlencode({"query": query, "per_page": limit, "page": 1})
        url = f"https://api.pexels.com/v1/search?{encoded}"
        payload, error = self._fetch_json(url, headers={"Authorization": key})
        if error:
            return [], {"provider": "pexels", "ok": False, "error": error}
        photos = payload.get("photos")
        if not isinstance(photos, list):
            return [], {"provider": "pexels", "ok": False, "error": "invalid response shape"}
        rows: list[dict[str, Any]] = []
        for item in photos[:limit]:
            if not isinstance(item, dict):
                continue
            src = item.get("src") if isinstance(item.get("src"), dict) else {}
            rows.append(
                {
                    "provider": "pexels",
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("alt") or "Pexels image"),
                    "thumbnail_url": str(src.get("small") or src.get("tiny") or ""),
                    "asset_url": str(src.get("large2x") or src.get("large") or src.get("original") or ""),
                    "source_url": str(item.get("url") or ""),
                    "creator": str(item.get("photographer") or ""),
                    "license": "Pexels License",
                }
            )
        return rows, {"provider": "pexels", "ok": True, "count": len(rows)}

    def _fetch_json(self, url: str, *, headers: dict[str, str]) -> tuple[dict[str, Any], str | None]:
        request_headers = {
            "User-Agent": "thomas-ui-workflow-engine/1.0",
            "Accept": "application/json",
        }
        request_headers.update(headers or {})
        req = urllib.request.Request(url=url, headers=request_headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._http_timeout_s) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            return {}, f"http {exc.code}"
        except urllib.error.URLError as exc:
            return {}, f"network error: {exc.reason}"
        except Exception as exc:
            return {}, f"request failed: {type(exc).__name__}: {exc}"
        try:
            data = json.loads(payload.decode("utf-8"))
        except Exception:
            return {}, "invalid json response"
        if not isinstance(data, dict):
            return {}, "json payload is not an object"
        return data, None

    def _write_cycle_log(self, report: dict[str, Any]) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(report, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.debug("UIWorkflowEngine failed to write log: %s", exc)


_engine: UIWorkflowEngine | None = None
_engine_lock = threading.Lock()


def get_ui_workflow_engine() -> UIWorkflowEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = UIWorkflowEngine()
    return _engine
