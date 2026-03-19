"""
FEATURE 13 — Dependency Vulnerability Scanner for Thomas (v4 "consumer-grade")

Tools:
- deps.scan
- deps.fix

Spec compliance (requested):
- deps.scan params: {"target": str (path to requirements.txt, package.json, or pyproject.toml. Default: auto-detect in cwd),
                     "ecosystem": "python"|"npm"|"auto" (default auto)}
- deps.fix params: {"package": str, "ecosystem": str}
- Python scan runs `pip-audit --format json` (auto-installs if missing via pip).
- npm scan runs `npm audit --json`.
- Parses output and returns at least:
    {
      "vulnerabilities": [{"package": str, "version": str, "severity": str, "cve": str, "fix_version": str}],
      "total": int, "critical": int, "high": int, "medium": int, "low": int
    }

"Meaningful" v4 upgrades (things humans actually love):
1) **Noise control**: stable sorted + de-duplicated output (same package/advisory collapses).
2) **Policy + ignore rules** without breaking the tool schema:
   - Optional config file read (no required setup):
       - thomas.toml -> [dep_scanner] ignore_packages, ignore_cves, min_severity, osv_enabled, osv_ttl_s
       - .thomas/dep_scanner.json -> same keys
   - Env overrides available.
3) **Actionable remediation plan**: returns an optional `remediation` block with grouped packages +
   suggested upgrade commands (still includes required keys for callers that ignore extras).
4) **Better fix_version coverage** using OSV as a fallback when pip-audit/npm don't provide one.
5) **Disk-backed OSV cache** (TTL) to keep scans fast and predictable.

Notes:
- Set THOMAS_DEP_SCANNER_NO_OSV=1 to disable OSV (offline/deterministic).
- Set THOMAS_DEP_SCANNER_INCLUDE_OPTIONAL=1 to include PEP 621 optional-dependencies when building reqs from pyproject.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ----------------------------
# Tool metadata (registry-friendly)
# ----------------------------

DEPS_SCAN_TOOL_NAME = "deps.scan"
DEPS_FIX_TOOL_NAME = "deps.fix"

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": DEPS_SCAN_TOOL_NAME,
        "description": "Scan a dependency manifest (Python or npm) for known vulnerabilities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Path to requirements.txt, package.json, or pyproject.toml. Default: auto-detect in cwd.",
                },
                "ecosystem": {"type": "string", "enum": ["python", "npm", "auto"], "default": "auto"},
            },
            "required": [],
            "additionalProperties": True,  # allow optional future knobs without breaking callers
        },
        "handler": "deps_scan",
    },
    {
        "name": DEPS_FIX_TOOL_NAME,
        "description": "Upgrade a specific package to its known fixed version (best-effort).",
        "input_schema": {
            "type": "object",
            "properties": {
                "package": {"type": "string"},
                "ecosystem": {"type": "string", "enum": ["python", "npm"]},
            },
            "required": ["package", "ecosystem"],
            "additionalProperties": True,
        },
        "handler": "deps_fix",
    },
]


def register_tools(registry: Any) -> None:
    """
    Best-effort hook to register tools with Thomas' registry.
    Supports common patterns:
      - registry.register(name, fn, schema=..., description=...)
      - registry.add_tool(name, fn, schema, description)
      - dict-like registry[name] = fn
    """
    for spec in TOOL_SPECS:
        name = spec["name"]
        fn = globals().get(spec["handler"])
        if fn is None:
            continue

        schema = spec.get("input_schema")
        desc = spec.get("description", "")

        if hasattr(registry, "register"):
            try:
                registry.register(name, fn, schema=schema, description=desc)
                continue
            except TypeError:
                try:
                    registry.register(name, fn, schema, desc)
                    continue
                except Exception:
                    pass
            except Exception:
                pass

        if hasattr(registry, "add_tool"):
            try:
                registry.add_tool(name, fn, schema, desc)
                continue
            except Exception:
                pass

        try:
            registry[name] = fn
        except Exception:
            pass


# ----------------------------
# Exceptions
# ----------------------------


class DepScanError(RuntimeError):
    pass


# ----------------------------
# Config (policy/ignore) — optional, no required setup
# ----------------------------

DEFAULT_MIN_SEVERITY = "low"
DEFAULT_OSV_TTL_S = 7 * 24 * 3600


def _read_thomas_toml_dep_scanner_section(toml_path: Path) -> dict[str, Any]:
    """
    Best-effort TOML parsing using tomllib (py3.11+).
    Returns dict for [dep_scanner] section.
    """
    try:
        import tomllib  # py3.11+
    except Exception:
        return {}
    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    section = data.get("dep_scanner")
    if not isinstance(section, dict):
        # allow nested under [tools] or similar? keep simple
        return {}
    return section


def _load_config(cwd: Path) -> dict[str, Any]:
    """
    Loads optional config from (first found):
    - ./thomas.toml  [dep_scanner]
    - ./.thomas/dep_scanner.json
    - ./dep_scanner.json

    Env overrides:
    - THOMAS_DEP_SCANNER_MIN_SEVERITY
    - THOMAS_DEP_SCANNER_NO_OSV / THOMAS_DEP_SCANNER_OSV_TTL_S
    - THOMAS_DEP_SCANNER_IGNORE_PACKAGES (comma-separated)
    - THOMAS_DEP_SCANNER_IGNORE_CVES (comma-separated)
    """
    cfg: dict[str, Any] = {}

    toml = cwd / "thomas.toml"
    if toml.exists():
        cfg.update(_read_thomas_toml_dep_scanner_section(toml))

    # JSON overrides (project-local)
    j1 = cwd / ".thomas" / "dep_scanner.json"
    j2 = cwd / "dep_scanner.json"
    for p in (j1, j2):
        if p.exists():
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    cfg.update(obj)
            except Exception:
                pass

    # env overrides
    if os.environ.get("THOMAS_DEP_SCANNER_MIN_SEVERITY"):
        cfg["min_severity"] = os.environ.get("THOMAS_DEP_SCANNER_MIN_SEVERITY")
    if os.environ.get("THOMAS_DEP_SCANNER_OSV_TTL_S"):
        cfg["osv_ttl_s"] = os.environ.get("THOMAS_DEP_SCANNER_OSV_TTL_S")
    if os.environ.get("THOMAS_DEP_SCANNER_IGNORE_PACKAGES"):
        cfg["ignore_packages"] = [
            x.strip() for x in os.environ["THOMAS_DEP_SCANNER_IGNORE_PACKAGES"].split(",") if x.strip()
        ]
    if os.environ.get("THOMAS_DEP_SCANNER_IGNORE_CVES"):
        cfg["ignore_cves"] = [x.strip() for x in os.environ["THOMAS_DEP_SCANNER_IGNORE_CVES"].split(",") if x.strip()]

    return cfg


def _cfg_list(cfg: dict[str, Any], key: str) -> list[str]:
    v = cfg.get(key)
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [x.strip() for x in v.split(",") if x.strip()]
    return []


def _cfg_str(cfg: dict[str, Any], key: str, default: str = "") -> str:
    v = cfg.get(key)
    if v is None:
        return default
    return str(v).strip() or default


def _cfg_int(cfg: dict[str, Any], key: str, default: int) -> int:
    v = cfg.get(key)
    try:
        return int(v)
    except Exception:
        return default


# ----------------------------
# Output schema
# ----------------------------


@dataclass(frozen=True)
class VulnRecord:
    package: str
    version: str
    severity: str
    cve: str
    fix_version: str
    ecosystem: str  # internal only; we don't add field to output to preserve spec

    def as_dict(self) -> dict[str, str]:
        return {
            "package": self.package,
            "version": self.version,
            "severity": self.severity,
            "cve": self.cve,
            "fix_version": self.fix_version,
        }


# ----------------------------
# Command execution (prefers Thomas shell tool if present)
# ----------------------------


def _get_thomas_shell_callable() -> Any | None:
    candidates = [
        ("thomas.tools.shell", "shell"),
        ("thomas.tools.shell_tool", "shell"),
        ("thomas.tools.shell", "run"),
        ("thomas.tools.shell_tool", "run"),
        ("thomas.tools.shell", "run_shell"),
        ("thomas.tools.shell", "shell_run"),
    ]
    for mod_name, fn_name in candidates:
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                return fn
        except Exception:
            continue
    return None


def _run_cmd(
    args: list[str],
    cwd: str | Path | None = None,
    timeout_s: int = 600,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    cwd_s = str(cwd) if cwd else None
    env = env or os.environ.copy()

    shell_fn = _get_thomas_shell_callable()
    if shell_fn is not None:
        cmd_str = " ".join(shlex.quote(a) for a in args)
        payload_variants = [
            {"cmd": cmd_str, "cwd": cwd_s, "timeout_s": timeout_s, "env": env},
            {"command": cmd_str, "cwd": cwd_s, "timeout_s": timeout_s, "env": env},
            {"cmd": cmd_str, "cwd": cwd_s},
            cmd_str,
        ]
        for payload in payload_variants:
            try:
                res = shell_fn(payload)  # type: ignore[misc]
                if isinstance(res, dict):
                    code = res.get("exit_code", res.get("code", res.get("returncode", 0)))
                    out = res.get("stdout", res.get("out", "")) or ""
                    err = res.get("stderr", res.get("err", "")) or ""
                    return int(code or 0), str(out), str(err)
                if isinstance(res, str):
                    return 0, res, ""
            except Exception:
                continue

    proc = subprocess.run(
        args,
        cwd=cwd_s,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# ----------------------------
# JSON parsing helpers
# ----------------------------


def _json_from_messy_text(text: str) -> Any:
    t = (text or "").strip()
    if not t:
        raise ValueError("empty text")
    try:
        return json.loads(t)
    except Exception:
        pass
    # find first object/array and decode from there
    first_obj = t.find("{")
    first_arr = t.find("[")
    starts = [p for p in (first_obj, first_arr) if p >= 0]
    if not starts:
        raise ValueError("no JSON start found")
    start = min(starts)
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(t[start:])
    return obj


def _parse_json_from_stdout_stderr(stdout: str, stderr: str) -> Any:
    for blob in (stdout, stderr):
        blob = (blob or "").strip()
        if not blob:
            continue
        try:
            return _json_from_messy_text(blob)
        except Exception:
            continue
    combined = ((stdout or "") + "\n" + (stderr or "")).strip()
    return _json_from_messy_text(combined)


# ----------------------------
# Target detection + ecosystem inference
# ----------------------------


def _auto_detect_target(cwd: str | Path) -> Path:
    base = Path(cwd).resolve()
    candidates = [
        base / "pyproject.toml",
        base / "requirements.txt",
        base / "package.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    for c in base.glob("requirements*.txt"):
        if c.is_file():
            return c
    raise DepScanError(f"Could not auto-detect a dependency manifest in: {base}")


def _resolve_target_path(target_raw: str) -> Path:
    p = Path(target_raw).expanduser()
    if p.is_dir():
        # allow directory targets for "consumer happiness": scan manifest inside.
        for c in (p / "pyproject.toml", p / "requirements.txt", p / "package.json"):
            if c.exists():
                return c
        for c in p.glob("requirements*.txt"):
            if c.is_file():
                return c
        raise DepScanError(f"Target directory has no supported manifests: {p}")
    return p


def _infer_ecosystem_from_target(target: Path) -> str:
    name = target.name.lower()
    if name == "package.json":
        return "npm"
    if name == "pyproject.toml":
        return "python"
    if name.endswith(".txt") and "requirements" in name:
        return "python"
    if target.suffix.lower() in (".toml", ".txt"):
        return "python"
    return "npm"


def _normalize_severity(s: str | None) -> str:
    if not s:
        return "medium"
    s = str(s).strip().lower()
    if s == "moderate":
        return "medium"
    if s not in {"critical", "high", "medium", "low"}:
        return "medium"
    return s


def _severity_rank(sev: str) -> int:
    s = _normalize_severity(sev)
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(s, 2)


def _min_severity_rank(min_sev: str) -> int:
    return _severity_rank(_normalize_severity(min_sev))


def _counts_from_vulns(vulns: list[VulnRecord]) -> dict[str, int]:
    counts = {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}
    for v in vulns:
        sev = _normalize_severity(v.severity)
        counts["total"] += 1
        counts[sev] += 1
    return counts


def _pick_highest_version(versions: list[str]) -> str:
    if not versions:
        return ""
    try:
        from packaging.version import Version  # type: ignore

        return str(max(versions, key=lambda x: Version(x)))
    except Exception:
        return sorted(versions)[-1]


def _extract_cve(aliases: list[str], fallback: str = "") -> str:
    for a in aliases or []:
        if isinstance(a, str) and a.upper().startswith("CVE-"):
            return a.upper()
    return fallback


def _extract_cve_from_text(text: str) -> str:
    m = re.search(r"\bCVE-\d{4}-\d{4,}\b", text or "", flags=re.IGNORECASE)
    return m.group(0).upper() if m else ""


# ----------------------------
# OSV enrichment with disk cache + TTL
# ----------------------------


def _osv_enabled(cfg: dict[str, Any]) -> bool:
    if str(os.environ.get("THOMAS_DEP_SCANNER_NO_OSV", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return False
    v = cfg.get("osv_enabled")
    if v is None:
        return True
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in {"0", "false", "no", "off"}


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


def _osv_cache_fresh(vuln_id: str, ttl_s: int) -> bool:
    ts = _OSV_CACHE_META.get(vuln_id)
    if ts is None:
        return False
    return (time.time() - ts) <= ttl_s


def _osv_get_vuln(cfg: dict[str, Any], vuln_id: str, timeout_s: int = 8) -> dict[str, Any] | None:
    if not vuln_id or not _osv_enabled(cfg):
        return None

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


# ----------------------------
# Python: pyproject -> temporary requirements file (best-effort)
# ----------------------------


def _poetry_spec_to_pip(name: str, s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if s.startswith("^"):
        base = s[1:].strip()
        parts = base.split(".")
        if parts and parts[0].isdigit():
            major = int(parts[0])
            upper = f"<{major+1}.0.0"
            return f"{name}>={base},{upper}"
        return f"{name}{s}"
    if re.fullmatch(r"\d+(\.\d+)*([a-zA-Z0-9\.\-\+]+)?", s):
        return f"{name}=={s}"
    if s[0] in "<>=":
        return f"{name}{s}"
    return f"{name}{s}"


def _build_requirements_from_pyproject(pyproject_path: Path) -> list[str]:
    """
    Best-effort extraction from:
    - PEP 621: [project].dependencies and (optionally) [project].optional-dependencies
    - Poetry:  [tool.poetry.dependencies] and [tool.poetry.group.*.dependencies]

    Env: THOMAS_DEP_SCANNER_INCLUDE_OPTIONAL=1 includes PEP 621 optional-dependencies too.
    """
    pyproject_path = pyproject_path.resolve()
    try:
        import tomllib  # py3.11+
    except Exception:
        return []
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    include_optional = str(os.environ.get("THOMAS_DEP_SCANNER_INCLUDE_OPTIONAL", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    reqs: list[str] = []

    proj = data.get("project")
    if isinstance(proj, dict):
        deps = proj.get("dependencies")
        if isinstance(deps, list):
            for d in deps:
                if isinstance(d, str) and d.strip():
                    reqs.append(d.strip())

        if include_optional:
            opt = proj.get("optional-dependencies")
            if isinstance(opt, dict):
                for _g, items in opt.items():
                    if isinstance(items, list):
                        for d in items:
                            if isinstance(d, str) and d.strip():
                                reqs.append(d.strip())

    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict):
            deps = poetry.get("dependencies")
            if isinstance(deps, dict):
                for name, spec in deps.items():
                    if not isinstance(name, str) or name.lower() == "python":
                        continue
                    if isinstance(spec, str):
                        req = _poetry_spec_to_pip(name, spec)
                        if req:
                            reqs.append(req)
                    elif isinstance(spec, dict):
                        ver = spec.get("version")
                        if isinstance(ver, str) and ver.strip():
                            req = _poetry_spec_to_pip(name, ver.strip())
                            if req:
                                reqs.append(req)

            group = poetry.get("group")
            if isinstance(group, dict):
                for _gname, gobj in group.items():
                    if not isinstance(gobj, dict):
                        continue
                    gdeps = gobj.get("dependencies")
                    if not isinstance(gdeps, dict):
                        continue
                    for name, spec in gdeps.items():
                        if not isinstance(name, str) or name.lower() == "python":
                            continue
                        if isinstance(spec, str):
                            req = _poetry_spec_to_pip(name, spec)
                            if req:
                                reqs.append(req)
                        elif isinstance(spec, dict):
                            ver = spec.get("version")
                            if isinstance(ver, str) and ver.strip():
                                req = _poetry_spec_to_pip(name, ver.strip())
                                if req:
                                    reqs.append(req)

    # dedup preserving order
    seen = set()
    out: list[str] = []
    for r in reqs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# ----------------------------
# Python scan (pip-audit) — robust PATH + module fallback
# ----------------------------


def _ensure_pip_audit_available() -> None:
    code, _, _ = _run_cmd(["pip-audit", "--version"], timeout_s=60)
    if code == 0:
        return

    code, _, _ = _run_cmd([sys.executable, "-m", "pip_audit", "--version"], timeout_s=60)
    if code == 0:
        return

    code, out, err = _run_cmd([sys.executable, "-m", "pip", "install", "--upgrade", "pip-audit"], timeout_s=600)
    if code != 0:
        raise DepScanError("pip-audit is not installed and auto-install failed.\n" f"stdout:\n{out}\n\nstderr:\n{err}")


def _run_pip_audit_json(args: list[str], cwd: Path) -> Any:
    # pip-audit exits non-zero when vulnerabilities exist; parse anyway.
    last_err: str | None = None
    for cmd in (["pip-audit"], [sys.executable, "-m", "pip_audit"]):
        code, out, err = _run_cmd(cmd + args, cwd=cwd, timeout_s=600)
        try:
            return _parse_json_from_stdout_stderr(out, err)
        except Exception as e:
            last_err = f"exit_code={code} parse_error={e} stdout={out[:2000]} stderr={err[:2000]}"
            continue
    raise DepScanError(f"Failed to parse pip-audit JSON output. {last_err or ''}")


def _python_scan(cfg: dict[str, Any], target: Path) -> list[VulnRecord]:
    _ensure_pip_audit_available()

    target = target.resolve()
    cwd = target.parent

    req_file: Path | None = None
    cleanup_req = False

    try:
        if target.name.lower() == "pyproject.toml":
            reqs = _build_requirements_from_pyproject(target)
            if reqs:
                fd, p = tempfile.mkstemp(prefix="thomas_pyproject_reqs_", suffix=".txt")
                os.close(fd)
                req_file = Path(p)
                req_file.write_text("\n".join(reqs) + "\n", encoding="utf-8")
                cleanup_req = True

        if req_file is not None:
            data = _run_pip_audit_json(["--format", "json", "-r", str(req_file)], cwd=cwd)
        elif target.name.lower().endswith(".txt") and target.is_file():
            data = _run_pip_audit_json(["--format", "json", "-r", str(target)], cwd=cwd)
        else:
            data = _run_pip_audit_json(["--format", "json"], cwd=cwd)

        if not isinstance(data, list):
            raise DepScanError(f"Unexpected pip-audit JSON structure (expected list), got: {type(data)}")

        out: list[VulnRecord] = []

        for dep in data:
            if not isinstance(dep, dict):
                continue
            pkg = str(dep.get("name", "")).strip()
            ver = str(dep.get("version", "")).strip() or "unknown"
            vulns = dep.get("vulns") or []
            if not pkg or not isinstance(vulns, list) or not vulns:
                continue

            for v in vulns:
                if not isinstance(v, dict):
                    continue
                vuln_id = str(v.get("id", "")).strip()
                aliases = v.get("aliases") or []
                aliases = [a for a in aliases if isinstance(a, str)]

                fix_versions = v.get("fix_versions") or []
                if isinstance(v.get("fix_version"), str) and v.get("fix_version"):
                    fix_versions = list(fix_versions) + [v.get("fix_version")]
                fix_versions = [fv for fv in fix_versions if isinstance(fv, str) and fv.strip()]
                fix_version = _pick_highest_version(fix_versions)

                osv_obj = _osv_get_vuln(cfg, vuln_id) or next(
                    (_osv_get_vuln(cfg, a) for a in aliases if a.upper().startswith("GHSA-")), None
                )

                severity = _normalize_severity(_severity_from_osv_obj(osv_obj))
                if not fix_version and osv_obj is not None:
                    fixes = _fixed_versions_from_osv_obj(osv_obj, pkg)
                    fix_version = _pick_highest_version([f for f in fixes if f])

                cve = _extract_cve(aliases, fallback=_extract_cve_from_text(vuln_id) or vuln_id or "unknown")

                out.append(VulnRecord(pkg, ver, severity, cve or "unknown", fix_version or "", "python"))

        return out

    finally:
        if cleanup_req and req_file and req_file.exists():
            try:
                req_file.unlink()
            except Exception:
                pass


# ----------------------------
# npm scan (npm audit) — handles v6 and v7+ formats + OSV fallback
# ----------------------------


def _ensure_npm_available(cwd: Path) -> None:
    code, out, err = _run_cmd(["npm", "--version"], cwd=cwd, timeout_s=60)
    if code != 0:
        raise DepScanError(f"npm is not available.\nstdout:\n{out}\n\nstderr:\n{err}")
