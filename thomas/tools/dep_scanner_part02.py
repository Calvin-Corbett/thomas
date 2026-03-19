def _npm_ls_versions_map(cwd: Path) -> Dict[str, str]:
    code, out, err = _run_cmd(["npm", "ls", "--all", "--json"], cwd=cwd, timeout_s=600)
    try:
        tree = _parse_json_from_stdout_stderr(out, err)
    except Exception:
        return {}

    versions: Dict[str, str] = {}

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


def _npm_advisory_id(item: Dict[str, Any]) -> str:
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


def _npm_scan(cfg: Dict[str, Any], target: Path) -> List[VulnRecord]:
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
    out_vulns: List[VulnRecord] = []

    # npm v7+: report["vulnerabilities"] is a map keyed by package name
    if isinstance(report, dict) and isinstance(report.get("vulnerabilities"), dict):
        vmap: Dict[str, Any] = report["vulnerabilities"]
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
        advisories: Dict[str, Any] = report["advisories"]
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


# ----------------------------
# De-dup, filter, remediation plan
# ----------------------------


def _dedup(vulns: List[VulnRecord]) -> List[VulnRecord]:
    """
    De-duplicate by (ecosystem, package, cve, version, fix_version). Keep max severity.
    """
    best: Dict[Tuple[str, str, str, str, str], VulnRecord] = {}
    for v in vulns:
        key = (v.ecosystem, v.package, v.cve, v.version, v.fix_version)
        if key not in best:
            best[key] = v
            continue
        cur = best[key]
        if _severity_rank(v.severity) < _severity_rank(cur.severity):
            best[key] = v
    return list(best.values())


def _apply_policy_filters(cfg: Dict[str, Any], vulns: List[VulnRecord]) -> List[VulnRecord]:
    ignore_pkgs = {p.lower() for p in _cfg_list(cfg, "ignore_packages")}
    ignore_cves = {c.lower() for c in _cfg_list(cfg, "ignore_cves")}
    min_sev = _cfg_str(cfg, "min_severity", DEFAULT_MIN_SEVERITY)
    min_rank = _min_severity_rank(min_sev)

    out: List[VulnRecord] = []
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


def _stable_sort(vulns: List[VulnRecord]) -> List[VulnRecord]:
    vulns.sort(key=lambda r: (_severity_rank(r.severity), r.ecosystem, r.package.lower(), r.cve.lower(), r.version))
    return vulns


def _osv_fix_fallback(cfg: Dict[str, Any], ecosystem: str, package: str, version: str) -> str:
    """
    If scan doesn't provide a fix version, try OSV query on package+version and
    infer a "fixed" version. We choose the highest fixed version we can find.
    """
    q = _osv_query(cfg, ecosystem=ecosystem, package=package, version=version)
    if not isinstance(q, dict):
        return ""
    vulns = q.get("vulns")
    if not isinstance(vulns, list):
        return ""
    fixes: List[str] = []
    for v in vulns:
        if not isinstance(v, dict):
            continue
        fixes.extend(_fixed_versions_from_osv_obj(v, package) or [])
    return _pick_highest_version([f for f in fixes if isinstance(f, str) and f.strip()])


def _remediation_plan(cfg: Dict[str, Any], vulns: List[VulnRecord]) -> Dict[str, Any]:
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
    by_pkg: Dict[Tuple[str, str], List[VulnRecord]] = {}
    for v in vulns:
        by_pkg.setdefault((v.ecosystem, v.package), []).append(v)

    pkg_entries: List[Dict[str, Any]] = []
    commands: List[str] = []

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


# ----------------------------
# Public tool handlers
# ----------------------------


def deps_scan(params: Optional[Dict[str, Any]] = None, ctx: Any = None) -> Dict[str, Any]:
    params = params or {}
    ecosystem = str(params.get("ecosystem", "auto") or "auto").strip().lower()
    target_raw = str(params.get("target", "") or "").strip()

    cwd = Path(os.getcwd())
    cfg = _load_config(cwd)

    target = _resolve_target_path(target_raw) if target_raw else _auto_detect_target(cwd)

    if ecosystem == "auto":
        ecosystem = _infer_ecosystem_from_target(target)

    if ecosystem not in {"python", "npm"}:
        raise DepScanError(f"Invalid ecosystem: {ecosystem}")

    if ecosystem == "python":
        vulns = _python_scan(cfg, target)
    else:
        vulns = _npm_scan(cfg, target)

    # consumer-grade cleanups
    vulns = _dedup(vulns)
    vulns = _apply_policy_filters(cfg, vulns)
    vulns = _stable_sort(vulns)

    counts = _counts_from_vulns(vulns)
    result: Dict[str, Any] = {"vulnerabilities": [v.as_dict() for v in vulns], **counts}

    # optional, additive: remediation plan (doesn't break callers that only read required keys)
    result["remediation"] = _remediation_plan(cfg, vulns)

    # optional, additive: policy that was applied (helps debugging)
    result["policy"] = {
        "min_severity": _cfg_str(cfg, "min_severity", DEFAULT_MIN_SEVERITY),
        "ignore_packages": _cfg_list(cfg, "ignore_packages"),
        "ignore_cves": _cfg_list(cfg, "ignore_cves"),
        "osv_enabled": _osv_enabled(cfg),
        "osv_ttl_s": _cfg_int(cfg, "osv_ttl_s", DEFAULT_OSV_TTL_S),
    }

    return result


def deps_fix(params: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    pkg = str(params.get("package") or "").strip()
    ecosystem = str(params.get("ecosystem") or "").strip().lower()

    if not pkg:
        raise DepScanError("Missing required param: package")
    if ecosystem not in {"python", "npm"}:
        raise DepScanError("ecosystem must be 'python' or 'npm'")

    cwd = Path(os.getcwd())
    cfg = _load_config(cwd)

    # Spec doesn't include "target" for fix, so operate against manifest in CWD.
    target = _auto_detect_target(cwd)
    workdir = target.parent.resolve()

    if ecosystem == "python":
        vulns = _python_scan(cfg, target)
        relevant = [v for v in vulns if v.package == pkg]
        if not relevant:
            return {"ok": False, "message": f"No vulnerabilities found for python package '{pkg}'."}

        fix_versions = [v.fix_version for v in relevant if v.fix_version]
        fix_version = _pick_highest_version(fix_versions)

        if not fix_version:
            installed = relevant[0].version if relevant else "unknown"
            fix_version = _osv_fix_fallback(cfg, "PyPI", pkg, installed)

        if not fix_version:
            return {"ok": False, "message": f"No fix version available for python package '{pkg}'."}

        # Required spec command (we include -m pip for PATH robustness)
        spec = f"{pkg}>={fix_version}"
        cmd = [sys.executable, "-m", "pip", "install", spec]
        code, out, err = _run_cmd(cmd, cwd=workdir, timeout_s=600)
        return {
            "ok": code == 0,
            "package": pkg,
            "ecosystem": "python",
            "fix_version": fix_version,
            "command": " ".join(shlex.quote(x) for x in cmd),
            "stdout": out,
            "stderr": err,
        }

    # npm
    npm_target = target if target.name.lower() == "package.json" else (workdir / "package.json")
    if not npm_target.exists():
        return {"ok": False, "message": "No package.json found in current directory for npm fix."}

    vulns = _npm_scan(cfg, npm_target)
    relevant = [v for v in vulns if v.package == pkg]
    if not relevant:
        return {"ok": False, "message": f"No vulnerabilities found for npm package '{pkg}'."}

    fix_versions = [v.fix_version for v in relevant if v.fix_version]
    fix_version = _pick_highest_version(fix_versions)

    if not fix_version:
        installed = relevant[0].version if relevant else "unknown"
        fix_version = _osv_fix_fallback(cfg, "npm", pkg, installed)

    if not fix_version:
        return {
            "ok": False,
            "message": (
                f"No fix version found for npm package '{pkg}'. "
                "This can be transitive; you may need to bump a parent dependency."
            ),
            "package": pkg,
            "ecosystem": "npm",
        }

    cmd = ["npm", "install", f"{pkg}@{fix_version}"]
    code, out, err = _run_cmd(cmd, cwd=workdir, timeout_s=600)
    return {
        "ok": code == 0,
        "package": pkg,
        "ecosystem": "npm",
        "fix_version": fix_version,
        "command": " ".join(shlex.quote(x) for x in cmd),
        "stdout": out,
        "stderr": err,
    }
