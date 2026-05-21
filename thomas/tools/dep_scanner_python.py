"""Python dependency scanning via pip-audit and pyproject parsing."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from .dep_scanner_core import (
    DepScanError,
    VulnRecord,
    _extract_cve,
    _extract_cve_from_text,
    _normalize_severity,
    _parse_json_from_stdout_stderr,
    _pick_highest_version,
    _run_cmd,
)
from .dep_scanner_osv import _fixed_versions_from_osv_obj, _osv_get_vuln, _severity_from_osv_obj

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
            upper = f"<{major + 1}.0.0"
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
        raise DepScanError(f"pip-audit is not installed and auto-install failed.\nstdout:\n{out}\n\nstderr:\n{err}")


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

        if isinstance(data, dict):
            dependencies = data.get("dependencies")
            if not isinstance(dependencies, list):
                raise DepScanError(
                    "Unexpected pip-audit JSON structure "
                    f"(expected list or object with `dependencies`), got: {type(data)}"
                )
            data = dependencies
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
