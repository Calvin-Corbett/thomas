"""OSV enrichment with disk cache + TTL."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _cache_dir() -> Path:
    env = str(os.environ.get("THOMAS_RUNTIME_DIR", "")).strip()
    if env:
        return Path(env).expanduser().resolve() / "cache"
    try:
        from thomas.core.config import resolve_thomas_data_dir

        return (resolve_thomas_data_dir() / "runtime" / "cache").resolve()
    except Exception:
        return (Path.home() / ".thomas" / "cache").resolve()


def _osv_cache_path() -> Path:
    return _cache_dir() / "osv_vuln_cache.json"


_OSV_CACHE_MEM: dict[str, dict[str, Any] | None] = {}
_OSV_CACHE_META: dict[str, float] = {}  # id -> fetched_ts
_OSV_CACHE_LOADED = False


def _load_osv_cache_disk() -> None:
    global _OSV_CACHE_LOADED
    if _OSV_CACHE_LOADED:
        return
    _OSV_CACHE_LOADED = True
    p = _osv_cache_path()
    try:
        if not p.exists():
            return
        obj = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            return
        items = obj.get("items")
        meta = obj.get("meta")
        if isinstance(items, dict):
            for k, v in items.items():
                if isinstance(k, str) and (v is None or isinstance(v, dict)):
                    _OSV_CACHE_MEM[k] = v
        if isinstance(meta, dict):
            for k, ts in meta.items():
                if isinstance(k, str):
                    try:
                        _OSV_CACHE_META[k] = float(ts)
                    except Exception:
                        pass
    except Exception:
        return


def _save_osv_cache_disk() -> None:
    try:
        d = _cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        p = _osv_cache_path()
        payload = {"items": _OSV_CACHE_MEM, "meta": _OSV_CACHE_META, "schema": 1}
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


def _osv_enabled(cfg: dict[str, Any]) -> bool:
    if str(os.environ.get("THOMAS_DEP_SCANNER_NO_OSV", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return False
    v = cfg.get("osv_enabled")
    if v is None:
        return True
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in {"0", "false", "no", "off"}


def _osv_cache_fresh(vuln_id: str, ttl_s: int) -> bool:
    ts = _OSV_CACHE_META.get(vuln_id)
    if ts is None:
        return False
    return (time.time() - ts) <= ttl_s


def _osv_get_vuln(cfg: dict[str, Any], vuln_id: str, timeout_s: int = 8) -> dict[str, Any] | None:
    if not vuln_id or not _osv_enabled(cfg):
        return None

    from .dep_scanner_core import DEFAULT_OSV_TTL_S, _cfg_int

    ttl_s = _cfg_int(cfg, "osv_ttl_s", DEFAULT_OSV_TTL_S)

    _load_osv_cache_disk()

    if vuln_id in _OSV_CACHE_MEM and _osv_cache_fresh(vuln_id, ttl_s):
        return _OSV_CACHE_MEM[vuln_id]

    url = f"https://api.osv.dev/v1/vulns/{vuln_id}"
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "thomas-dep-scanner/4.0"})
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            obj = json.loads(body)
            _OSV_CACHE_MEM[vuln_id] = obj
            _OSV_CACHE_META[vuln_id] = time.time()
            _save_osv_cache_disk()
            return obj
    except (HTTPError, URLError, Exception):
        _OSV_CACHE_MEM[vuln_id] = None
        _OSV_CACHE_META[vuln_id] = time.time()
        _save_osv_cache_disk()
        return None


def _osv_query(
    cfg: dict[str, Any], ecosystem: str, package: str, version: str, timeout_s: int = 8
) -> dict[str, Any] | None:
    if not _osv_enabled(cfg):
        return None
    if not ecosystem or not package or not version or version == "unknown":
        return None

    url = "https://api.osv.dev/v1/query"
    payload = {"package": {"name": package, "ecosystem": ecosystem}, "version": version}
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "thomas-dep-scanner/4.0",
        },
    )
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body)
    except Exception:
        return None


def _cvss_score_from_osv(osv_obj: dict[str, Any]) -> float | None:
    severity = osv_obj.get("severity") or []
    scores: list[float] = []
    for item in severity:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("score", "")).strip()
        if not raw:
            continue
        try:
            scores.append(float(raw))
            continue
        except Exception:
            pass
        m = re.search(r"(\d+(?:\.\d+)?)", raw)
        if m:
            try:
                scores.append(float(m.group(1)))
            except Exception:
                pass
    return max(scores) if scores else None


def _severity_from_cvss(score: float | None) -> str:
    if score is None:
        return "medium"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    if score > 0.0:
        return "low"
    return "low"


def _severity_from_osv_obj(osv_obj: dict[str, Any] | None) -> str:
    if not osv_obj:
        return "medium"
    return _severity_from_cvss(_cvss_score_from_osv(osv_obj))


def _fixed_versions_from_osv_obj(osv_obj: dict[str, Any], package_name: str) -> list[str]:
    fixed: list[str] = []
    affected = osv_obj.get("affected")
    if not isinstance(affected, list):
        return fixed
    for a in affected:
        if not isinstance(a, dict):
            continue
        pkg = a.get("package")
        if isinstance(pkg, dict):
            name = str(pkg.get("name", "") or "")
            if name and name.lower() != package_name.lower():
                continue
        ranges = a.get("ranges")
        if not isinstance(ranges, list):
            continue
        for r in ranges:
            if not isinstance(r, dict):
                continue
            events = r.get("events")
            if not isinstance(events, list):
                continue
            for ev in events:
                if isinstance(ev, dict) and isinstance(ev.get("fixed"), str) and ev["fixed"].strip():
                    fixed.append(ev["fixed"].strip())
    return fixed
