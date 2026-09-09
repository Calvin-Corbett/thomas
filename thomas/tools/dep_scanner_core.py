"""Core analysis, configuration, and severity ranking."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ----------------------------
# Config defaults
# ----------------------------

DEFAULT_MIN_SEVERITY = "low"
DEFAULT_OSV_TTL_S = 7 * 24 * 3600


# ----------------------------
# Exceptions
# ----------------------------


class DepScanError(RuntimeError):
    pass


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
# Config (policy/ignore) — optional, no required setup
# ----------------------------


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
# Severity scoring
# ----------------------------


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


# ----------------------------
# Version and CVE extraction
# ----------------------------


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
# Command execution
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
    import shlex

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
# De-dup, filter, remediation plan
# ----------------------------


def _dedup(vulns: list[VulnRecord]) -> list[VulnRecord]:
    """
    De-duplicate by (ecosystem, package, cve, version, fix_version). Keep max severity.
    """
    best: dict[tuple[str, str, str, str, str], VulnRecord] = {}
    for v in vulns:
        key = (v.ecosystem, v.package, v.cve, v.version, v.fix_version)
        if key not in best:
            best[key] = v
            continue
        cur = best[key]
        if _severity_rank(v.severity) < _severity_rank(cur.severity):
            best[key] = v
    return list(best.values())


def _apply_policy_filters(cfg: dict[str, Any], vulns: list[VulnRecord]) -> list[VulnRecord]:
    ignore_pkgs = {p.lower() for p in _cfg_list(cfg, "ignore_packages")}
    ignore_cves = {c.lower() for c in _cfg_list(cfg, "ignore_cves")}
    min_sev = _cfg_str(cfg, "min_severity", DEFAULT_MIN_SEVERITY)
    min_rank = _min_severity_rank(min_sev)

    out: list[VulnRecord] = []
    for v in vulns:
        if v.package.lower() in ignore_pkgs:
            continue
        if v.cve.lower() in ignore_cves:
            continue
        if _severity_rank(v.severity) > min_rank:
            # lower priority than minimum severity threshold
            continue
        out.append(v)
    return out


def _stable_sort(vulns: list[VulnRecord]) -> list[VulnRecord]:
    vulns.sort(key=lambda r: (_severity_rank(r.severity), r.ecosystem, r.package.lower(), r.cve.lower(), r.version))
    return vulns


def _osv_fix_fallback(cfg: dict[str, Any], ecosystem: str, package: str, version: str) -> str:
    """
    If scan doesn't provide a fix version, try OSV query on package+version and
    infer a "fixed" version. We choose the highest fixed version we can find.
    """
    from .dep_scanner_osv import _fixed_versions_from_osv_obj, _osv_query

    q = _osv_query(cfg, ecosystem=ecosystem, package=package, version=version)
    if not isinstance(q, dict):
        return ""
    vulns = q.get("vulns")
    if not isinstance(vulns, list):
        return ""
    fixes: list[str] = []
    for v in vulns:
        if not isinstance(v, dict):
            continue
        fixes.extend(_fixed_versions_from_osv_obj(v, package) or [])
    return _pick_highest_version([f for f in fixes if isinstance(f, str) and f.strip()])


def _remediation_plan(cfg: dict[str, Any], vulns: list[VulnRecord]) -> dict[str, Any]:
    """
    Returns a remediation block users can actually act on.

    Example:
    {
      "packages": [
         {"ecosystem":"python","package":"requests","installed":"2.27.0","fix_version":"2.31.0",
          "severity":"high","advisories":["CVE-...","GHSA-..."], "command":"python -m pip install requests>=2.31.0"}
      ],
      "commands": [...],
      "notes": "..."
    }
    """
    by_pkg: dict[tuple[str, str], list[VulnRecord]] = {}
    for v in vulns:
        by_pkg.setdefault((v.ecosystem, v.package), []).append(v)

    pkg_entries: list[dict[str, Any]] = []
    commands: list[str] = []

    for (eco, pkg), items in by_pkg.items():
        installed = items[0].version if items else "unknown"
        # best fix: highest fix_version, else OSV fallback
        fixes = [i.fix_version for i in items if i.fix_version]
        fix = _pick_highest_version([f for f in fixes if f]) if fixes else ""
        if not fix:
            # best-effort OSV query fallback (only if OSV enabled)
            osv_eco = "PyPI" if eco == "python" else "npm"
            fix = _osv_fix_fallback(cfg, osv_eco, pkg, installed)

        worst = min(items, key=lambda x: _severity_rank(x.severity))
        advisories = sorted({i.cve for i in items if i.cve})

        if eco == "python" and fix:
            cmd = f"{sys.executable} -m pip install {pkg}>={fix}"
        elif eco == "npm" and fix:
            cmd = f"npm install {pkg}@{fix}"
        else:
            cmd = ""

        entry = {
            "ecosystem": eco,
            "package": pkg,
            "installed": installed,
            "fix_version": fix,
            "severity": worst.severity,
            "advisories": advisories,
            "command": cmd,
        }
        pkg_entries.append(entry)
        if cmd:
            commands.append(cmd)

    pkg_entries.sort(
        key=lambda e: (
            _severity_rank(str(e.get("severity", ""))),
            str(e.get("ecosystem", "")),
            str(e.get("package", "")).lower(),
        )
    )
    commands = list(dict.fromkeys(commands))  # dedup preserving order

    notes = (
        "Commands are best-effort. Some npm issues are transitive and may require bumping a parent dependency. "
        "For Python, constraints in your environment may prevent installing the suggested version."
    )
    return {"packages": pkg_entries, "commands": commands, "notes": notes}
