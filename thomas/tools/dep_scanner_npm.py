"""npm dependency scanning via npm audit."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .dep_scanner_core import (
    DepScanError,
    VulnRecord,
    _extract_cve_from_text,
    _normalize_severity,
    _parse_json_from_stdout_stderr,
    _pick_highest_version,
    _run_cmd,
)
from .dep_scanner_osv import _fixed_versions_from_osv_obj, _osv_get_vuln

# ----------------------------
# npm scan (npm audit) — handles v6 and v7+ formats + OSV fallback
# ----------------------------


def _ensure_npm_available(cwd: Path) -> None:
    code, out, err = _run_cmd(["npm", "--version"], cwd=cwd, timeout_s=60)
    if code != 0:
        raise DepScanError(f"npm is not available.\nstdout:\n{out}\n\nstderr:\n{err}")


def _npm_ls_versions_map(cwd: Path) -> dict[str, str]:
    code, out, err = _run_cmd(["npm", "ls", "--all", "--json"], cwd=cwd, timeout_s=600)
    try:
        tree = _parse_json_from_stdout_stderr(out, err)
    except Exception:
        return {}

    versions: dict[str, str] = {}

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        name = node.get("name")
        ver = node.get("version")
        if isinstance(name, str) and isinstance(ver, str) and name and ver:
            versions.setdefault(name, ver)

        deps = node.get("dependencies")
        if isinstance(deps, dict):
            for _k, child in deps.items():
                walk(child)

    walk(tree)
    return versions


def _npm_advisory_id(item: dict[str, Any]) -> str:
    # npm advisory objects vary; try a stable identifier first, else URL/title
    for k in ("source", "id", "name"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    url = item.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    title = item.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return "unknown"


def _npm_scan(cfg: dict[str, Any], target: Path) -> list[VulnRecord]:
    target = target.resolve()
    cwd = target.parent
    _ensure_npm_available(cwd)

    code, out, err = _run_cmd(["npm", "audit", "--json"], cwd=cwd, timeout_s=600)
    try:
        report = _parse_json_from_stdout_stderr(out, err)
    except Exception as e:
        raise DepScanError(
            "Failed to parse npm audit JSON output.\n"
            f"exit_code={code}\nstdout:\n{out}\n\nstderr:\n{err}\n\nparse_error={e}"
        )

    versions_map = _npm_ls_versions_map(cwd)
    out_vulns: list[VulnRecord] = []

    # npm v7+: report["vulnerabilities"] is a map keyed by package name
    if isinstance(report, dict) and isinstance(report.get("vulnerabilities"), dict):
        vmap: dict[str, Any] = report["vulnerabilities"]
        for pkg_name, entry in vmap.items():
            if not isinstance(entry, dict):
                continue

            installed_version = versions_map.get(pkg_name, "unknown")
            base_sev = _normalize_severity(entry.get("severity"))

            fix_version = ""
            fix_available = entry.get("fixAvailable")
            if isinstance(fix_available, dict):
                fv = fix_available.get("version")
                if isinstance(fv, str) and fv.strip():
                    fix_version = fv.strip()

            via = entry.get("via")
            if isinstance(via, list) and via:
                for item in via:
                    if isinstance(item, dict):
                        title = str(item.get("title", "") or "")
                        url = str(item.get("url", "") or "")
                        cve = _extract_cve_from_text(title) or _extract_cve_from_text(url)
                        if not cve:
                            cve = _npm_advisory_id(item)
                        sev = _normalize_severity(item.get("severity") or base_sev)

                        if not fix_version:
                            adv_id = _npm_advisory_id(item)
                            osv_obj = None
                            if isinstance(adv_id, str) and re.match(r"^(GHSA-|CVE-)", adv_id, re.IGNORECASE):
                                osv_obj = _osv_get_vuln(cfg, adv_id)
                            if osv_obj:
                                fixes = _fixed_versions_from_osv_obj(osv_obj, pkg_name)
                                fix_version = _pick_highest_version([f for f in fixes if f])

                        out_vulns.append(
                            VulnRecord(pkg_name, installed_version, sev, cve or "unknown", fix_version, "npm")
                        )
                    else:
                        out_vulns.append(
                            VulnRecord(pkg_name, installed_version, base_sev, "unknown", fix_version, "npm")
                        )
            else:
                out_vulns.append(VulnRecord(pkg_name, installed_version, base_sev, "unknown", fix_version, "npm"))

        return out_vulns

    # npm v6 legacy: report["advisories"] map keyed by id
    if isinstance(report, dict) and isinstance(report.get("advisories"), dict):
        advisories: dict[str, Any] = report["advisories"]
        for _adv_id, adv in advisories.items():
            if not isinstance(adv, dict):
                continue
            pkg_name = str(adv.get("module_name", "") or "unknown").strip()
            sev = _normalize_severity(adv.get("severity"))
            title = str(adv.get("title", "") or "")
            cve = (
                _extract_cve_from_text(title)
                or str(adv.get("cves", "") or "").strip()
                or str(adv.get("id", "") or "").strip()
                or "unknown"
            )
            patched = str(adv.get("patched_versions", "") or "")
            installed_version = versions_map.get(pkg_name, "unknown")

            fix_version = ""
            m = re.search(r"\b(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z\.-]+)?)\b", patched)
            if m:
                fix_version = m.group(1)

            out_vulns.append(VulnRecord(pkg_name, installed_version, sev, cve, fix_version, "npm"))

        return out_vulns

    raise DepScanError(
        "Unexpected npm audit JSON structure. "
        f"type={type(report)} keys={list(report.keys()) if isinstance(report, dict) else 'n/a'}"
    )
